# Specmatic Contract and Resiliency Tests

This project keeps the Specmatic setup outside the FastAPI application code. The backend contract lives in `backend/contracts/openapi.yaml`, shared schemas live in `backend/schema/schemas.json`, and concrete examples live in `backend/contracts/openapi_examples/`.

## What This Adds

- Contract tests for every FastAPI backend route without changing route handlers, models, or tests.
- Resiliency checks through Specmatic generative tests, useful for discovering validation and schema edge cases early.
- External Specmatic example files with complete `http-request` and `http-response` pairs, which keeps the OpenAPI contract readable and makes executable examples easy to review or download from a PR.
- A single schema source in `backend/schema/schemas.json`, so response and request definitions do not drift across route-specific files.
- A mock-server-ready contract. Because Specmatic can serve the backend contract as a mock API, frontend and backend development can happen in parallel without waiting on each other.

## Files

- `specmatic.yaml`: Specmatic project configuration.
- `backend/contracts/openapi.yaml`: OpenAPI contract used by Specmatic.
- `backend/schema/schemas.json`: Shared schema definitions referenced by the OpenAPI contract.
- `backend/contracts/openapi_examples/*.json`: External Specmatic examples in request-response pair format.
- `compose.override.yml`: Adds Specmatic contract and resiliency runner services only.

## Running Contract Tests

Start the backend stack and run the contract tests from Docker Compose:

```bash
docker compose up specmatic-contract-runner
```

Run resiliency tests after the contract runner:

```bash
docker compose up specmatic-resiliency-runner
```

Reports are written under `build/reports/specmatic-contract-tests/` and `build/reports/specmatic-resiliency-tests/`.

## Authentication Token

Do not commit a bearer token. This template creates JWT access tokens using `ACCESS_TOKEN_EXPIRE_MINUTES`, which defaults to `60 * 24 * 8` minutes, or 8 days, in `backend/app/core/config.py`. A token copied into source control will eventually expire and is also a credential leak.

For local runs, generate a fresh token with the login endpoint and export it before running Specmatic:

```bash
export SPECMATIC_AUTH_TOKEN="Bearer <fresh-token>"
docker compose up specmatic-contract-runner
```

On Windows PowerShell:

```powershell
$env:SPECMATIC_AUTH_TOKEN = "Bearer <fresh-token>"
docker compose up specmatic-contract-runner
```

In CI, store the token or token generation step in the CI secret manager. For a production-quality PR, the preferred approach is to generate short-lived credentials during the workflow instead of checking in static secrets.

## Mock Server Workflow For Frontend Later

Once the frontend is ready to consume the contract, run Specmatic in mock mode from the same OpenAPI file. The frontend can point its API base URL to the Specmatic mock server instead of the live backend.

A typical workflow is:

1. Backend developers update `openapi.yaml`, `schemas.json`, and examples when API behavior changes.
2. Frontend developers run the Specmatic mock server from the contract and build screens against predictable responses.
3. Contract tests validate that the real FastAPI backend still satisfies the same contract.
4. Resiliency tests explore edge cases beyond the curated examples.

This separates API agreement from implementation timing, so frontend work can continue while backend endpoints are still being implemented.

## PR Notes

The compose override intentionally avoids application-code changes. The only Compose additions are the Specmatic runner services, and authentication is read from `SPECMATIC_AUTH_TOKEN` rather than a committed JWT.
