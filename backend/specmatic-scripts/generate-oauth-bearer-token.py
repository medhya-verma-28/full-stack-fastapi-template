#!/usr/bin/env python3
"""
specmatic-scripts/generate_access_token.py

Logs in to the full-stack-fastapi-template backend and writes a real
AUTH_TOKEN into the .env file that already exists at the project root
(one level up from this script), so Specmatic can pick it up via the
template your examples already use:

    "Authorization": "Bearer ${OAUTH_BEARER_TOKEN:test-token}"

It does NOT create a new .env -- it updates the existing one in place:
  - If an AUTH_TOKEN= line already exists, it's replaced.
  - Otherwise, a new AUTH_TOKEN= line is appended.
  - Every other line in .env is left untouched.

--------------------------------------------------------------------------
CREDENTIALS
--------------------------------------------------------------------------
By default this reads FIRST_SUPERUSER / FIRST_SUPERUSER_PASSWORD directly
out of the project's own root .env (the same variables the template uses
to seed its first superuser), so it logs in with whatever superuser your
project is actually configured with -- no need to duplicate values.
You can override any of this via env vars (see CONFIG below) without
touching .env.

--------------------------------------------------------------------------
USAGE
--------------------------------------------------------------------------
From the project root:

    python3 specmatic-scripts/generate_access_token.py

Then run Specmatic as usual -- it will read AUTH_TOKEN from .env:

    specmatic test --spec-file openapi.json --testBaseURL http://localhost:8000

Or combine both in one line:

    python3 specmatic-scripts/generate_access_token.py && \\
      specmatic test --spec-file openapi.json --testBaseURL http://localhost:8000

--------------------------------------------------------------------------
CONFIG (env vars, all optional)
--------------------------------------------------------------------------
  BACKEND_BASE_URL     default: http://localhost:8000
  SUPERUSER_EMAIL      default: value of FIRST_SUPERUSER in root .env
  SUPERUSER_PASSWORD   default: value of FIRST_SUPERUSER_PASSWORD in root .env
  ENV_FILE_PATH        default: <project root>/.env  (i.e. ../.env from this script)
  MAX_WAIT_SECONDS     default: 30
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.dirname(SCRIPT_DIR)))
  # specmatic-scripts/ -> project root

ENV_FILE_PATH = os.path.join(PROJECT_ROOT,".env")
BACKEND_BASE_URL = "http://backend:8000"
MAX_WAIT_SECONDS = int(os.environ.get("MAX_WAIT_SECONDS", "30"))

def read_env_file(path):
    """Returns (lines, dict_of_values). Preserves original line order/formatting."""
    if not os.path.exists(path):
        sys.exit(
            f"!! {path} does not exist.\n"
            f"   This script expects the project's .env to already be created at "
            f"the project root (one level up from specmatic-scripts/)."
        )
    with open(path) as f:
        lines = f.readlines()

    values = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return lines, values


def upsert_env_var(lines, key, value):
    """Replaces an existing KEY= line in-place, or appends one if not found."""
    pattern = re.compile(rf"^{re.escape(key)}=")
    new_line = f"{key}={value}\n"
    for i, line in enumerate(lines):
        if pattern.match(line.strip()):
            lines[i] = new_line
            return lines, True
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    lines.append(new_line)
    return lines, False


def wait_for_backend():
    url = f"{BACKEND_BASE_URL}/api/v1/utils/health-check/"
    deadline = time.time() + MAX_WAIT_SECONDS
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    print(f"==> Backend is up at {BACKEND_BASE_URL}")
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        print(f"==> Waiting for backend at {BACKEND_BASE_URL} ...")
        time.sleep(2)
    sys.exit(f"!! Backend did not become ready within {MAX_WAIT_SECONDS}s")


def fetch_access_token(email, password):
    url = f"{BACKEND_BASE_URL}/api/v1/login/access-token"
    form = urllib.parse.urlencode({
        "grant_type": "password",
        "username": email,
        "password": password,
    }).encode()
    req = urllib.request.Request(
        url, data=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read())
            return body["access_token"]
    except urllib.error.HTTPError as e:
        detail = e.read().decode()
        sys.exit(
            f"!! Login failed ({e.code}): {detail}\n"
            f"   Check that SUPERUSER_EMAIL/SUPERUSER_PASSWORD (or "
            f"FIRST_SUPERUSER/FIRST_SUPERUSER_PASSWORD in .env) match a real "
            f"user on {BACKEND_BASE_URL}."
        )


def main():
    lines, env_values = read_env_file(ENV_FILE_PATH)

    email = os.environ.get("SUPERUSER_EMAIL") or env_values.get("FIRST_SUPERUSER")
    password = os.environ.get("SUPERUSER_PASSWORD") or env_values.get("FIRST_SUPERUSER_PASSWORD")

    if not email or not password:
        sys.exit(
            "!! Could not determine login credentials.\n"
            "   Set SUPERUSER_EMAIL/SUPERUSER_PASSWORD env vars, or make sure "
            "FIRST_SUPERUSER/FIRST_SUPERUSER_PASSWORD are set in .env."
        )

    wait_for_backend()

    print(f"==> Logging in as {email} ...")
    access_token = fetch_access_token(email, password)
    print(f"==> Got AUTH_TOKEN (first 12 chars): {access_token[:12]}...")

    lines, existed = upsert_env_var(lines, "OAUTH_BEARER_TOKEN", access_token)
    with open(ENV_FILE_PATH, "w") as f:
        f.writelines(lines)

    action = "Updated" if existed else "Added"
    print(f"==> {action} AUTH_TOKEN in {ENV_FILE_PATH}")


if __name__ == "__main__":
    main()
