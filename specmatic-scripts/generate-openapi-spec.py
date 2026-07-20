#!/usr/bin/env python3
"""
bomb_specmatic_proxy.py
========================

Replays every request found in ./specmatic-test-requests/*.json against a
running Specmatic PROXY server, to generate real traffic for it to record
(see "Step 3: Send Test Requests" here:
https://docs.specmatic.io/contract_driven_development/generating_api_specifications#step-1-start-the-proxy-server).

Each JSON file in the directory follows the Specmatic stub/example format:

    {
      "http-request": {
        "method": "POST",
        "path": "/api/v1/items/",
        "headers": {"Content-Type": "application/json", ...},
        "body": {...}            # dict (JSON) or string (e.g. form-encoded)
      }
    }

Only the "http-request" portion is used -- this script fires that request
at the proxy and reports back what came back.

Prerequisites
-------------
1. The real backend (FastAPI app) is running, e.g. on http://localhost:8000
2. The Specmatic proxy is started in front of it, per the reference docs:

       specmatic proxy --target http://localhost:8000 ./specification

   which prints: "Proxy server is running on http://localhost:9000."

Auth handling (built in, no adapter required)
----------------------------------------------
Specmatic's `pre_specmatic_request_processor` data adapter (the one that
could otherwise inject a live Bearer token on the way through the proxy)
is an Enterprise/Commercial-only feature
(https://docs.specmatic.io/features/adapters/request_response_adapters) --
it is NOT available on the free, open-source `specmatic proxy` binary.

So this script fetches and injects the token itself:

  1. It looks through the discovered *.json files for one whose
     "http-request.path" matches `/login/access-token` (by default, the
     `00_api_v1_login_access-token.json` file) and uses its exact body/
     headers as the login call -- so it reuses whatever credentials you
     already have in that file. Override with --auth-file / --auth-path /
     --auth-username / --auth-password if you'd rather not rely on that.
  2. It POSTs that request through the proxy once, extracts
     `access_token` from the JSON response, and caches it for the run.
  3. For every other request, it strips any existing `Authorization`
     header (case-insensitively) and sets `Authorization: Bearer <token>`
     before sending -- replacing the "Bearer {{OAUTH2_BEARER_TOKEN}}"
     placeholders already in these sample files.

Use --no-auto-auth to disable this and send headers exactly as written in
each file (e.g. if you *are* on Specmatic Enterprise and want the
pre_specmatic_request_processor adapter to handle it instead).

Usage
-----
    python bomb_specmatic_proxy.py
    python bomb_specmatic_proxy.py --dir ./specmatic-test-requests --proxy-url http://localhost:9000
    python bomb_specmatic_proxy.py --iterations 5 --concurrency 10
    python bomb_specmatic_proxy.py --fail-fast
    python bomb_specmatic_proxy.py --no-auto-auth
"""

import argparse
import json
import re
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from os import PathLike
from typing import Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

# Matches the login endpoint's path regardless of any prefix (e.g.
# /api/v1/login/access-token), so we can auto-detect the login file.
LOGIN_PATH_PATTERN = re.compile(r"/login/access-token/?(\?.*)?$")

# Matches an existing Authorization header key case-insensitively, so a
# placeholder like "Bearer {{OAUTH2_BEARER_TOKEN}}" gets replaced, not
# duplicated.
AUTH_HEADER_KEY_PATTERN = re.compile(r"^authorization$", re.IGNORECASE)
BODY_TOKEN_KEY_PATTERN = re.compile(r"^token$", re.IGNORECASE)



@dataclass
class RequestResult:
    filename: str
    method: str
    path: str
    status: Optional[int]
    elapsed_seconds: float
    error: Optional[str]
    response_snippet: str = ""

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 400


def discover_test_request_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        raise FileNotFoundError(f"test-requests directory not found: {directory}")
    # Sorted so numerically-prefixed files (e.g. 00_login...) run first.
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no *.json files found under: {directory}")
    return files


def load_http_request(file_path: Path) -> dict:
    with open(file_path,"r", encoding="utf-8") as handle:
        document = json.load(handle)
    http_request = document.get("http-request")
    if not http_request:
        raise ValueError(f"{file_path.name} has no 'http-request' key")
    return http_request


def build_url(proxy_base_url: str, http_request: dict) -> str:
    path = http_request.get("path", "/")
    query = http_request.get("query")
    url = proxy_base_url.rstrip("/") + path
    if query:
        # Support the optional Specmatic "query" object even though none of
        # the sample files use it (they inline the query string in "path").
        from urllib.parse import urlencode

        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(query)}"
    return url


def build_body(http_request: dict, headers: dict) -> Optional[bytes]:
    body = http_request.get("body")
    if body is None:
        return None
    if isinstance(body, (dict, list)):
        return json.dumps(body).encode("utf-8")
    # Already-encoded string bodies, e.g. "username=...&password=..."
    return str(body).encode("utf-8")


def is_login_request(http_request: dict) -> bool:
    path = http_request.get("path", "") or ""
    return path=="/api/v1/login/access-token"


def find_login_file(files: list[Path]) -> Optional[Path]:
    """Locate the *.json file whose http-request targets /login/access-token."""
    for file_path in files:
        try:
            http_request = load_http_request(file_path)
        except (ValueError, json.JSONDecodeError):
            continue
        if is_login_request(http_request):
            return file_path
    return None

def inject_token_in_header(file_path:Path, access_token: str) -> None:
    with open(file_path, "r", encoding="utf-8") as fp:
        json_schema = json.load(fp)
    json_schema["http-request"]["headers"]["Authorization"] = "Bearer " + access_token
    with open(file_path, "w", encoding="utf-8") as fp:
        json.dump(json_schema, fp, indent=2)

def inject_token_in_body(file_path:Path, access_token: str) -> None:
    with open(file_path, "r", encoding="utf-8") as fp:
        json_schema = json.load(fp)
    json_schema["http-request"]["body"]["token"] = "Bearer " + access_token
    with open(file_path, "w", encoding="utf-8") as fp:
        json.dump(json_schema, fp, indent=2)


def fetch_access_token(
    proxy_base_url: str,
    login_request_file: Path,
    timeout: float,
) -> Optional[str]:
    http_request = load_http_request(login_request_file)
    path = http_request["path"]
    headers = http_request.get("headers", {})
    body = http_request.get("body")
    url = proxy_base_url.rstrip("/") + path
    response = requests.post(
            url,
            headers=headers,
            data=body,
            timeout=timeout,
        )

    print("Login response status:", response.status_code)
    print("Login response:", response.text)

    token = response.json().get("access_token")
    print("Extracted token:", token)

    if not token:
        raise ValueError("No access_token found in login response.")

    return token

def has_authorization_header(file_path: Path) -> bool:
    with open(file_path,"r", encoding="utf-8") as fp:
        json_schema=json.load(fp)
    if "Authorization" in json_schema["http-request"]["headers"]:
        return True
    else:
        return False

def has_token_body_parameter(file_path: Path) -> bool:
    with open(file_path, "r", encoding="utf-8") as fp:
        json_schema=json.load(fp)

    if "body" in json_schema["http-request"]:         
        if "token" in json_schema["http-request"]["body"]:
            return True
        else:
            return False
    else:
        return False


def fire_request(
    proxy_base_url: str,
    file_path: Path,
    timeout: float,
    bearer_token: Optional[str],
) -> RequestResult:
    http_request = load_http_request(file_path)
    method = http_request.get("method", "GET").upper()
    headers = http_request.get("headers", {})
    body = http_request.get("body", {})

    # Inject a live token only if this request originally expects an
    # Authorization header (Bearer {{OAUTH2_BEARER_TOKEN}}).
    if (bearer_token and not is_login_request(http_request) and has_authorization_header(file_path)):
        inject_token_in_header(file_path=file_path, access_token=bearer_token)
    elif (bearer_token and not is_login_request(http_request) and has_token_body_parameter(file_path)):
        inject_token_in_body(file_path=file_path, access_token=bearer_token)
    
    http_request = load_http_request(file_path)
    headers = dict(http_request.get("headers", {}))
    url = build_url(proxy_base_url, http_request)
    data = build_body(http_request, headers)

    print("\n==========")
    print(file_path.name)
    print("Bearer token:", bearer_token)
    print("Headers before inject:", dict(http_request.get("headers", {})))
    print("Headers after inject :", headers)
    request = urllib_request.Request(url, data=data, method=method, headers=headers)

    start = time.perf_counter()
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            elapsed = time.perf_counter() - start
            snippet = response.read(200).decode("utf-8", "replace")
            return RequestResult(
                filename=file_path.name,
                method=method,
                path=http_request.get("path", ""),
                status=response.status,
                elapsed_seconds=elapsed,
                error=None,
                response_snippet=snippet,
            )
    except urllib_error.HTTPError as exc:
        elapsed = time.perf_counter() - start
        snippet = exc.read().decode("utf-8", "replace")[:200]
        return RequestResult(
            filename=file_path.name,
            method=method,
            path=http_request.get("path", ""),
            status=exc.code,
            elapsed_seconds=elapsed,
            error=None,
            response_snippet=snippet,
        )
    except urllib_error.URLError as exc:
        elapsed = time.perf_counter() - start
        return RequestResult(
            filename=file_path.name,
            method=method,
            path=http_request.get("path", ""),
            status=None,
            elapsed_seconds=elapsed,
            error=str(exc.reason),
        )


def print_result(result: RequestResult) -> None:
    status_label = result.status if result.status is not None else "ERROR"
    marker = "OK " if result.ok else "FAIL"
    print(
        f"[{marker}] {result.method:<7} {result.path:<55} "
        f"status={status_label} time={result.elapsed_seconds * 1000:.1f}ms "
        f"({result.filename})"
    )
    if not result.ok:
        detail = result.error or result.response_snippet
        if detail:
            print(f"        -> {detail}")


def print_summary(results: list[RequestResult]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    failed = total - passed
    avg_ms = (sum(r.elapsed_seconds for r in results) / total * 1000) if total else 0.0
    max_ms = max((r.elapsed_seconds for r in results), default=0.0) * 1000
    min_ms = min((r.elapsed_seconds for r in results), default=0.0) * 1000

    print("\n" + "=" * 70)
    print("Summary")
    print("=" * 70)
    print(f"Total requests : {total}")
    print(f"Succeeded      : {passed}")
    print(f"Failed         : {failed}")
    print(f"Latency (ms)   : avg={avg_ms:.1f}  min={min_ms:.1f}  max={max_ms:.1f}")
    print("=" * 70)


def run_sequential(
    proxy_base_url: str,
    files: list[Path],
    timeout: float,
    delay: float,
    fail_fast: bool,
    bearer_token: Optional[str],
) -> list[RequestResult]:
    results = []
    for file_path in files:
        http_request = load_http_request(file_path=file_path)
        if bearer_token and is_login_request(http_request):
            continue
        result = fire_request(proxy_base_url, file_path, timeout, bearer_token)
        print_result(result)
        results.append(result)
        if fail_fast and not result.ok:
            print("Stopping: --fail-fast set and a request failed.")
            break
        if delay > 0:
            time.sleep(delay)
    return results


def run_concurrent(
    proxy_base_url: str,
    files: list[Path],
    timeout: float,
    concurrency: int,
    bearer_token: Optional[str],
) -> list[RequestResult]:
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {}
        for file_path in files:
            http_request = load_http_request(file_path=file_path)
            if bearer_token and is_login_request(http_request):
                continue
            future = executor.submit(
                fire_request,
                proxy_base_url,
                file_path,
                timeout,
                bearer_token,
            )
            futures[future] = file_path

        for future in as_completed(futures):
            result = future.result()
            print_result(result)
            results.append(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bomb a Specmatic proxy server with test requests from JSON files."
    )
    parser.add_argument(
        "--dir",
        default="./specmatic-test-requests",
        help="Directory containing *.json Specmatic example files (default: %(default)s)"
    )
    parser.add_argument(
        "--proxy-url",
        default="http://localhost:9000",
        help="Base URL of the running Specmatic proxy server (default: %(default)s)"
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="How many times to replay the full set of requests (default: %(default)s)"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of requests to fire in parallel per iteration. "
        "1 = sequential (default: %(default)s)"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Delay in seconds between requests when running sequentially (default: %(default)s)"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="Per-request timeout in seconds (default: %(default)s)"
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on the first failed request (sequential mode only)"
    )
    parser.add_argument(
        "--no-auto-auth",
        action="store_true",
        help="Disable built-in token fetch/injection; send headers exactly as "
        "written in each file. Use this if a licensed Specmatic Enterprise "
        "pre_specmatic_request_processor adapter is already handling auth."
    )
    parser.add_argument(
        "--auth-file",
        default="specmatic-test-requests/00_POST_api_v1_login_access-token.json",
        help="Explicit path to the login/access-token request JSON file "
        "(default: auto-detected among --dir's *.json files)"
    )
    args = parser.parse_args()

    try:
        files = discover_test_request_files(Path(args.dir))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(files)} test request file(s) in {args.dir}")
    print(f"Target proxy: {args.proxy_url}")
    print(f"Iterations={args.iterations} Concurrency={args.concurrency}\n")

    bearer_token: Optional[str] = None
    if not args.no_auto_auth:
        login_file = AUTH_FILE_PATH
        
        if login_file:
            print(f"Auth: using login request file '{login_file.name}'")
        else:
            print("Auth: no login/access-token file found, using --auth-* overrides")
        try:
            bearer_token = fetch_access_token(
                proxy_base_url="http://localhost:9000",
                timeout=15,
                login_request_file=login_file
            )
            print("Auth: access token obtained, will inject into subsequent requests\n")
        except (urllib_error.URLError, urllib_error.HTTPError, ValueError, KeyError) as exc:
            print(f"Auth: failed to obtain access token ({exc}); "
                  f"continuing WITHOUT auto-injecting Authorization headers\n")

    all_results: list[RequestResult] = []
    for iteration in range(1, args.iterations + 1):
        if args.iterations > 1:
            print(f"--- Iteration {iteration}/{args.iterations} ---")

        if args.concurrency > 1:
            iteration_results = run_concurrent(
                args.proxy_url, files, args.timeout, args.concurrency, bearer_token
            )
        else:
            iteration_results = run_sequential(
                args.proxy_url,
                files,
                args.timeout,
                args.delay,
                args.fail_fast,
                bearer_token
            )

        all_results.extend(iteration_results)

        if args.fail_fast and any(not r.ok for r in iteration_results):
            break

    print_summary(all_results)

    if any(not r.ok for r in all_results):
        sys.exit(1)


if __name__ == "__main__":
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    sys.path.append(str(PROJECT_ROOT))

    AUTH_FILE_PATH = PROJECT_ROOT / "specmatic-test-requests" / "00_POST_api_v1_login_access-token.json"
    sys.path.append(str(AUTH_FILE_PATH))

    main()
