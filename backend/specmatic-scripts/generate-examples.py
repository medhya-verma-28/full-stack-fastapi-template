"""
generate_openapi_examples.py

Generates Specmatic external-test JSON examples (http-request / http-response
pairs) directly from a live openapi.json fetched from the running backend
(http://backend:8000/api/v1/openapi.json) -- no FastAPI app import required
and no local openapi.json file read from disk. The response is used as a
plain Python dict (SPEC) straight off the HTTP response and walked as
paths -> methods -> status codes; it's never written to a file.

Why this version exists
------------------------
A Specmatic coverage report (index.html) initially showed 37 of 42 declared
path+method+responseCode operations as "not tested". But a pytest coverage
audit (FastAPI_PyTest_Coverage.docx) shows pytest ALREADY exercises most of
those success/error scenarios directly against the app (200, 2XX, 400, 403,
404, 409 -- just not via Specmatic example files, which is why the report
flagged them). Generating success examples for those would duplicate
coverage pytest already has, not complement it. The audit's own conclusions:

  1. 422 (missing required params) is NOT tested by pytest at all, for any
     endpoint -- this is the real, universal gap.
  2. GET /api/v1/utils/health-check/ and POST /api/v1/utils/test-email/ are
     skipped by pytest ENTIRELY (no test file covers them) -- every status
     code they declare needs an example, not just 422.
  3. Exception: PATCH /api/v1/users/me/password's 200 case is deliberately
     excluded -- pytest already covers it and resets the password
     afterwards to avoid leaving the seed superuser's credentials changed;
     duplicating it in Specmatic risks exactly that side effect. Nothing
     special has to be done for this here since success statuses for this
     endpoint aren't generated anyway (see below) -- noted for clarity.

So: for the two pytest-skipped utils endpoints, generate one example per
declared status code. For every other endpoint (except access-token, which
stays fully excluded), generate 422-only examples -- pytest already covers
their success/other-error paths.

Rules
-----
1. /api/v1/login/access-token -> excluded completely, no files at all.
2. /api/v1/utils/health-check/ and /api/v1/utils/test-email/ -> one example
   per status code declared (pytest has zero coverage of these routes).
3. Every other endpoint/method -> 422 ONLY (pytest already covers their
   success/permission/not-found scenarios; 422 is the one thing it never
   tests). Built by taking a fully valid request (from the operation's real
   schema, resolved via $ref against components.schemas) and omitting
   exactly one required body property or required query param. Where an
   operation has no required body/query but declares a 422 anyway (e.g.
   GET/PATCH/DELETE .../{id}), and the path parameter's spec declares
   format: uuid, the 422 is instead forced via an invalid path value.
   If none of these apply, no 422 example is generated for that operation
   (nothing in the spec to violate).

Output
------
One JSON file per endpoint + method + status code, written to
./backend/contracts/openapi_examples/, using Specmatic's external test shape:

    {
      "http-request":  {"method": ..., "path": ..., "headers": ..., "body"/"query": ...},
      "http-response": {"status": ..., "headers": ..., "body": ...}
    }

Auth
----
Whenever an operation declares `security`, the Authorization header is
populated from OAUTH_BEARER_TOKEN, loaded via python-dotenv from a `.env`
file at the project root (one level above `backend/`).

Location
--------
This script lives at ./backend/specmatic-scripts/generate_openapi_examples.py
"""

import json
import os
import random
import re
import string
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Paths / setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent            # .../backend/specmatic-scripts
BACKEND_DIR = SCRIPT_DIR.parent                          # .../backend
PROJECT_ROOT = BACKEND_DIR.parent                         # repo root

OUTPUT_DIR = BACKEND_DIR / "contracts" / "openapi_examples"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# The spec is fetched live from the running backend, not read off disk.
OPENAPI_URL = "http://backend:8000/api/v1/openapi.json"

load_dotenv(PROJECT_ROOT / ".env")
OAUTH_BEARER_TOKEN = os.getenv("OAUTH_BEARER_TOKEN", "{{OAUTH_BEARER_TOKEN}}")

# The only endpoint excluded entirely, per instruction.
EXCLUDED_PATHS = {"/api/v1/login/access-token"}

# Entirely skipped by pytest (no test file covers them at all) -> generate
# every declared status code, not just 422.
ALL_STATUS_PATHS = {"/api/v1/utils/health-check/", "/api/v1/utils/test-email/"}

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

SEEDED_USER_ID = "3dcc3432-0289-482a-bae2-46937a2ae78e"
SEEDED_EMAIL = "admin@example.com"

# ---------------------------------------------------------------------------
# Mock value generators, keyed by property / parameter name. Factory
# functions (not plain values) so every generated example gets a fresh,
# independent value rather than one value reused everywhere.
# ---------------------------------------------------------------------------
mock_generators = {
    "title": lambda: f"Test Item {random.randint(1, 1000)}",
    "description": lambda: random.choice(
        ["Sample description for testing", "Mock item description"]
    ),
    "message": lambda: "Operation successful",
    "token": lambda: uuid.uuid4().hex,
    "access_token": lambda: f"Bearer {OAUTH_BEARER_TOKEN}",
    "token_type": lambda: "bearer",
    "sub": lambda: str(uuid.uuid4()),
    "password": lambda: f"Password@{random.randint(1000, 9999)}",
    "current_password": lambda: f"OldPassword@{random.randint(1000, 9999)}",
    "new_password": lambda: "changethis",
    "hashed_password": lambda: f"$2b$12${uuid.uuid4().hex}",
    "user_id": lambda: SEEDED_USER_ID,
    "id": lambda: SEEDED_USER_ID,
    "owner_id": lambda: SEEDED_USER_ID,
    "email": lambda: SEEDED_EMAIL,
    "email_to": lambda: SEEDED_EMAIL,
    "username": lambda: SEEDED_EMAIL,
    "full_name": lambda: random.choice(["John Doe", "Alice Smith", "Robert Johnson"]),
    "is_active": lambda: True,
    "is_superuser": lambda: False,
    "is_verified": lambda: True,
    "created_at": lambda: datetime.now(timezone.utc).isoformat(),
    "count": lambda: random.randint(1, 20),
    "skip": lambda: 0,
    "limit": lambda: 100,
}

_TYPE_DEFAULTS = {
    "string": lambda: "".join(random.choices(string.ascii_lowercase, k=8)),
    "integer": lambda: random.randint(1, 100),
    "number": lambda: round(random.uniform(1, 100), 2),
    "boolean": lambda: True,
    "array": lambda: [],
    "object": lambda: {},
}


def mock_value_for(name: str, schema: dict):
    """Mock value for a property/param: prefer a name-based generator,
    fall back to a type/format-based default."""
    if name in mock_generators:
        return mock_generators[name]()
    schema = schema or {}
    schema_type = schema.get("type", "string")
    fmt = schema.get("format")
    if schema_type == "string" and fmt == "email":
        return SEEDED_EMAIL
    if schema_type == "string" and fmt == "uuid":
        return str(uuid.uuid4())
    factory = _TYPE_DEFAULTS.get(schema_type, lambda: f"mock_{name}")
    return factory()


# ---------------------------------------------------------------------------
# openapi.json -- fetched live from the running backend and used directly
# as a dict; never written to disk.
# ---------------------------------------------------------------------------
def fetch_openapi_spec(url: str) -> dict:
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


SPEC = fetch_openapi_spec(OPENAPI_URL)

COMPONENTS_SCHEMAS = SPEC.get("components", {}).get("schemas", {})


def resolve_ref(ref: str) -> dict:
    name = ref.split("/")[-1]
    return COMPONENTS_SCHEMAS.get(name, {})


def resolve_schema(schema: dict) -> dict:
    if schema and "$ref" in schema:
        return resolve_ref(schema["$ref"])
    return schema or {}


def build_full_body(schema: dict) -> dict:
    """Build a fully populated, valid request body from a JSON schema."""
    schema = resolve_schema(schema)
    props = schema.get("properties", {})
    body = {}
    for prop_name, prop_schema in props.items():
        prop_schema = resolve_schema(prop_schema)
        body[prop_name] = mock_value_for(prop_name, prop_schema)
    return body


def request_body_schema(operation: dict):
    """Return (schema, required_fields, content_type) for an operation's
    requestBody, or (None, [], None) if it doesn't take a body."""
    request_body = operation.get("requestBody")
    if not request_body:
        return None, [], None
    content = request_body.get("content", {})
    for content_type, media in content.items():
        schema = resolve_schema(media.get("schema", {}))
        return schema, schema.get("required", []), content_type
    return None, [], None


def fill_path(path: str, overrides: dict | None = None) -> str:
    """Replace {param} placeholders in a path with mock values, optionally
    forcing a specific (e.g. deliberately invalid) value for one or more
    param names via `overrides`."""
    overrides = overrides or {}

    def _sub(match):
        param_name = match.group(1)
        if param_name in overrides:
            return str(overrides[param_name])
        return str(mock_value_for(param_name, {"type": "string"}))

    return re.sub(r"{([^{}]+)}", _sub, path)


def query_param_type_violation(query_params: list):
    """If any query param (required or not) declares a non-string type
    (integer/number/boolean), return (param_name, invalid_value,
    response_body) for sending a value of the WRONG type -- the type
    constraint applies whether or not the field is required, so this
    works even for optional params like `skip`/`limit`. Otherwise None.
    """
    type_to_error = {
        "integer": ("int_parsing", "Input should be a valid integer, unable to parse string as an integer"),
        "number": ("float_parsing", "Input should be a valid number, unable to parse string as a number"),
        "boolean": ("bool_parsing", "Input should be a valid boolean, unable to interpret input"),
    }
    for p in query_params:
        schema = p.get("schema", {})
        schema_type = schema.get("type")
        if schema_type in type_to_error:
            name = p["name"]
            invalid_value = "not-a-valid-value"
            error_type, msg = type_to_error[schema_type]
            return name, invalid_value, {
                "detail": [
                    {"type": error_type, "loc": ["query", name], "msg": msg, "input": invalid_value}
                ],
            }
    return None


_FORMAT_INVALID_VALUES = {
    "email": ("not-a-valid-email", "value_error", "value is not a valid email address: An email address must have an @-sign."),
    "uuid": ("not-a-valid-uuid", "uuid_parsing", "Input should be a valid UUID, unable to parse string as UUID"),
    "date": ("not-a-valid-date", "date_parsing", "Input should be a valid date"),
    "date-time": ("not-a-valid-datetime", "datetime_parsing", "Input should be a valid datetime"),
}


def body_property_format_violation(body_schema: dict):
    """If the body schema has any property (required or not) that declares
    a recognized string `format` -- either directly or inside an `anyOf`
    (the shape Pydantic v2 produces for `Optional[EmailStr]` etc.) --
    return (prop_name, invalid_value, response_body) for violating that
    format. Otherwise None.
    """
    schema = resolve_schema(body_schema)
    for prop_name, prop_schema in schema.get("properties", {}).items():
        prop_schema = resolve_schema(prop_schema)
        candidates = prop_schema.get("anyOf", [prop_schema])
        for candidate in candidates:
            if candidate.get("type") == "string" and candidate.get("format") in _FORMAT_INVALID_VALUES:
                fmt = candidate["format"]
                invalid_value, error_type, msg = _FORMAT_INVALID_VALUES[fmt]
                return prop_name, invalid_value, {
                    "detail": [
                        {"type": error_type, "loc": ["body", prop_name], "msg": msg, "input": invalid_value}
                    ],
                }
    return None


def path_param_type_violation(operation: dict):
    """If this operation's 422 can only be forced via a path parameter
    whose spec declares a parseable constraint (currently: format: uuid),
    return (param_name, invalid_value, response_body). Otherwise None.

    Deliberately conservative: a bare {"type": "string"} path param (e.g.
    the email path params, which declare no format) gives no spec-backed
    way to construct an invalid value, so those are left uncovered rather
    than guessing at app-internal validation the spec doesn't declare.
    """
    for p in operation.get("parameters", []):
        if p.get("in") != "path":
            continue
        schema = p.get("schema", {})
        if schema.get("type") == "string" and schema.get("format") == "uuid":
            name = p["name"]
            invalid_value = "not-a-valid-uuid"
            return name, invalid_value, {
                "detail": [
                    {
                        "type": "uuid_parsing",
                        "loc": ["path", name],
                        "msg": "Input should be a valid UUID, unable to parse string as UUID",
                        "input": invalid_value,
                    }
                ],
            }
    return None


def needs_auth(operation: dict) -> bool:
    return bool(operation.get("security"))


def build_headers(operation: dict, content_type: str | None, path: str) -> dict:
    headers = {}
    if content_type:
        headers["Content-Type"] = content_type
    if path not in ["/api/v1/utils/test-email/", "/api/v1/utils/health-check/"]:
        headers["Accept"] = "application/json"
    if needs_auth(operation):
        headers["Authorization"] = f"Bearer {OAUTH_BEARER_TOKEN}"
    return headers


def missing_body_error(field: str) -> dict:
    return {
        "detail": [
            {"type": "missing", "loc": ["body", field], "msg": "Field required", "input": None}
        ]
    }


def missing_query_error(field: str) -> dict:
    return {
        "detail": [
            {"type": "missing", "loc": ["query", field], "msg": "Field required", "input": None}
        ]
    }


def slug_for(method: str, path: str, suffix: str) -> str:
    base = path.strip("/").replace("/", "_").replace("{", "").replace("}", "")
    return f"{method.upper()}_{base}__{suffix}.json"


def write_example(filename: str, http_request: dict, status: int, response_body) -> None:
    payload = {
        "http-request": http_request,
        "http-response": {
            "status": status,
            "headers": {"Content-Type": "application/json"},
            "body": response_body,
        },
    }
    out_path = OUTPUT_DIR / filename
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\033[92mgenerated {filename}\033[0m")


# ---------------------------------------------------------------------------
# Success (non-422) response body, shaped by that response's own schema.
# ---------------------------------------------------------------------------
def success_response_body(response_schema: dict):
    if not response_schema:
        return None
    schema = resolve_schema(response_schema)
    schema_type = schema.get("type")
    if schema_type == "boolean":
        return True
    if schema_type in (None, "object"):
        return build_full_body(schema)
    return mock_value_for("value", schema)


# ---------------------------------------------------------------------------
# Builder #1: every status code declared for the operation.
# Used only for the two endpoints pytest skips entirely.
# ---------------------------------------------------------------------------
def build_all_status_examples(path: str, method: str, operation: dict) -> None:
    query_params = [p for p in operation.get("parameters", []) if p.get("in") == "query"]
    required_query = [p["name"] for p in query_params if p.get("required")]
    body_schema, required_body_fields, content_type = request_body_schema(operation)

    for status, response in operation.get("responses", {}).items():
        # Fresh valid body/query per status so different examples don't
        # accidentally share mutable state.
        full_query = {
            p["name"]: mock_value_for(p["name"], p.get("schema", {})) for p in query_params
        }
        full_body = build_full_body(body_schema) if body_schema else None

        headers = build_headers(operation, content_type, path)
        http_request = {"method": method.upper(), "path": fill_path(path), "headers": headers}
        if full_query:
            http_request["query"] = dict(full_query)
        if full_body is not None:
            http_request["body"] = dict(full_body)

        if status == "422":
            if required_query:
                dropped = required_query[0]
                remaining = {k: v for k, v in full_query.items() if k != dropped}
                if remaining:
                    http_request["query"] = remaining
                else:
                    http_request.pop("query", None)
                response_body = missing_query_error(dropped)
            elif required_body_fields:
                dropped = required_body_fields[0]
                http_request["body"] = {k: v for k, v in full_body.items() if k != dropped}
                response_body = missing_body_error(dropped)
            else:
                violation = path_param_type_violation(operation)
                if violation is not None:
                    param_name, invalid_value, response_body = violation
                    http_request["path"] = fill_path(path, {param_name: invalid_value})
                else:
                    violation = query_param_type_violation(query_params)
                    if violation is not None:
                        param_name, invalid_value, response_body = violation
                        http_request["query"] = {**full_query, param_name: invalid_value}
                    else:
                        violation = body_property_format_violation(body_schema) if body_schema else None
                        if violation is not None:
                            prop_name, invalid_value, response_body = violation
                            http_request["body"] = {**(full_body or {}), prop_name: invalid_value}
                        else:
                            continue
            write_example(slug_for(method, path, "422"), http_request, 422, response_body)
        else:
            response_content = response.get("content", {}).get("application/json", {})
            response_body = success_response_body(response_content.get("schema"))
            write_example(
                slug_for(method, path, str(status)), http_request, int(status), response_body
            )


# ---------------------------------------------------------------------------
# Builder #2: 422 ONLY. Used for every endpoint except the two above and
# access-token -- pytest already covers their success/permission/not-found
# scenarios directly against the app, so generating those here would
# duplicate rather than complement that coverage. 422 is the one scenario
# the pytest audit found untested for every endpoint, so it's the only one
# built here.
# ---------------------------------------------------------------------------
def build_422_only_examples(path: str, method: str, operation: dict) -> None:
    if "422" not in operation.get("responses", {}):
        return  # this operation doesn't even declare a 422 -> nothing to do

    query_params = [p for p in operation.get("parameters", []) if p.get("in") == "query"]
    required_query = [p["name"] for p in query_params if p.get("required")]
    body_schema, required_body_fields, content_type = request_body_schema(operation)

    full_query = {p["name"]: mock_value_for(p["name"], p.get("schema", {})) for p in query_params}
    full_body = build_full_body(body_schema) if body_schema else None

    headers = build_headers(operation, content_type, path)
    http_request = {"method": method.upper(), "path": fill_path(path), "headers": headers}
    if full_query:
        http_request["query"] = dict(full_query)
    if full_body is not None:
        http_request["body"] = dict(full_body)

    if required_query:
        dropped = required_query[0]
        remaining = {k: v for k, v in full_query.items() if k != dropped}
        if remaining:
            http_request["query"] = remaining
        else:
            http_request.pop("query", None)
        response_body = missing_query_error(dropped)
    elif required_body_fields:
        dropped = required_body_fields[0]
        http_request["body"] = {k: v for k, v in full_body.items() if k != dropped}
        response_body = missing_body_error(dropped)
    else:
        # Nothing REQUIRED to omit -- fall back to violating a declared
        # constraint on an otherwise-optional field/param, in priority
        # order: path param format (e.g. uuid) -> query param type
        # (e.g. skip/limit are typed integer even though optional) ->
        # body property format inside an optional field (e.g. an
        # Optional[EmailStr] that still declares format: email).
        violation = path_param_type_violation(operation)
        if violation is not None:
            param_name, invalid_value, response_body = violation
            http_request["path"] = fill_path(path, {param_name: invalid_value})
        else:
            violation = query_param_type_violation(query_params)
            if violation is not None:
                param_name, invalid_value, response_body = violation
                http_request["query"] = {**full_query, param_name: invalid_value}
            else:
                violation = body_property_format_violation(body_schema) if body_schema else None
                if violation is not None:
                    prop_name, invalid_value, response_body = violation
                    http_request["body"] = {**(full_body or {}), prop_name: invalid_value}
                else:
                    # Genuinely nothing in the spec to violate.
                    return

    write_example(slug_for(method, path, "422"), http_request, 422, response_body)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    for path, methods in SPEC.get("paths", {}).items():
        if path in EXCLUDED_PATHS:
            continue
        for method, operation in methods.items():
            if method not in HTTP_METHODS:
                continue
            if path in ALL_STATUS_PATHS:
                build_all_status_examples(path, method, operation)
            else:
                build_422_only_examples(path, method, operation)

    print(f"\nExamples written to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
