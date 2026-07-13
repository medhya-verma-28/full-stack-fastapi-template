# Introduction to Specmatic

[Specmatic](https://specmatic.io) is a spec-driven API development, testing and governance platform that turns API specifications into executable contracts. Instead of treating an OpenAPI or AsyncAPI document as static documentation, Specmatic uses industry standard API specs to automatically generate tests, mocks, compatibility checks, workflows, and governance capabilities.

## Improvements Made Through Specmatic in the PR
The original `fastapi/full-stack-fastapi-template` relies primarily on standard **Pytest** suites and **Playwright** end-to-end tests. While effective, standard testing mechanisms can let schema mismatches slide if test fixtures fall out of sync with real specifications.

By adding Specmatic to this fork branch, we introduce several improvements:

* **Decoupled API Testing**: Tests are automatically inferred directly from the `specmatic_contract.yaml` specification without writing a single line of backend test code.

* **Instant Drift Detection**: Any discrepancy between backend execution (data validation, ORM models) and the declared API specification is flagged immediately.

* **Negative & Boundary Validation**: Specmatic evaluates how the FastAPI application responds to malformed data, strict types, and missing fields.

* **Elimination of Flaky Mocking**: Upstream dependencies and internal responses are bounded firmly to actual specifications instead of manual mocks that risk becoming stale.

---

## What are Contract and Schema Resiliency Tests

### Contract Tests
**Contract tests** validate that the provider (the FastAPI application) honors the structural agreement defined in the OpenAPI specification. They ensure that every endpoint accepts the exact input fields, parameters, and headers defined, while responding with the precise data types and status codes expected by frontend consumers.

### Schema Resiliency Tests
**Schema resiliency tests** (also called generative or robustness testing) automatically fuzz the input schema. The testing engine generates an array of edge-case payloads—including boundary values, reversed types, missing optional fields, and unexpected headers. This checks whether the server handles errors gracefully (e.g., returning standard HTTP `422 Unprocessable Entity` responses via Pydantic) rather than crashing or throwing internal `500` server errors.

---

## Implementing Specmatic for Contract and Resiliency Tests
The application profile is declared across three central configuration files in the root folder:
* `specmatic.yaml`: Primary orchestration and contract pointer, generated as a Docker volume mount of `specmatic_contract.yaml` (for Contract Testing) and `specmatic_resiliency.yaml` (for Schema Resiliency Testing)

* `specmatic_contract.yaml`: The Specmatic V3 YAML configuration file for Contract Tests (Schema Resiliency Tests is set to None)

* `specmatic_resiliency.yaml`:  The Specmatic V3 YAML configuration file for Schema Resiliency Tests (Schema Resiliency Tests is set to all)

### Local Run
You can execute automated contract tests locally using python scripts or dedicated docker-compose configurations. To run authentication or direct python test triggers:

```python specmatic-auth.py```

```docker compose up --build --attach specmatic-contract-runner --attach backend --attach specmatic-resiliency-runner```

### Continuous Integration (CI)
Specmatic execution is automated within the continuous integration platform via GitHub Actions. Upon opening a PR or pushing to monitored branches, a dedicated workflow builds the backend stack and hooks Specmatic directly into the runtime pipeline. This blocks faulty builds from reaching deployment.

---

## Results
Upon running Specmatic, full execution metrics are summarized in the console and written to structured files. Test outcomes break down into the following:
* **Contract Test Pass/Fail**: A checklist of implemented endpoints matching the contract specification.
* **Resiliency Coverage**: Metrics evaluating the server's stability against generative fuzzed request data.
* **HTML Reports**: An interactive execution overview generated in the output directory.

---

## Final Docker Compose Command to See Tests Run

### LOCAL
To run the full contract suite locally inside the Docker network environment, run:

```docker compose up --build --attach specmatic-contract-runner --attach backend --attach specmatic-resiliency-runner```

### CI
The CI execution automatically handles network layers on GitHub Actions runners. The tests execute successfully using the configuration template below:

```docker compose -f compose.yml -f compose.override.yml up -d db backend```

```docker compose exec -T backend bash -c "while ! curl -s http://localhost:8000/health-check/; do sleep 1; done"```

```docker compose exec -T backend python ./specmatic-auth.py```

---

## Note to the Project Owner
> We would like to express our gratitude to the authors and maintainers of the original `fastapi/full-stack-fastapi-template` repo. This boilerplate is an exceptional, production-grade learning resource for developers looking to experiment with modern full-stack architectures. Integrating Specmatic into this environment illustrates how contract-driven pipelines secure the boundaries of production microservices. We hope you find this addition helpful, and we would deeply appreciate your review and acceptance of our contribution!