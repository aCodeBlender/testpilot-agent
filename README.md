# TestPilot

Deterministic REST API testing from OpenAPI specs.

## What TestPilot does

```
OpenAPI spec → Load & Resolve → Map to Domain → Generate Scenarios →
Generate Test Cases → Build Requests → Execute HTTP → Validate → JSON Report
```

TestPilot reads your OpenAPI 3.0.x spec, automatically generates deterministic test scenarios (happy path, required field missing, null values, wrong types), executes them against your real API, and produces a JSON report with pass/fail results.

## Quick Start

### 1. Start your API (Spring Boot Demo)

```bash
cd demo/springboot-demo
./mvnw spring-boot:run
```

### 2. Run TestPilot

```bash
python -m testpilot run \
  --openapi http://localhost:8080/v3/api-docs \
  --base-url http://localhost:8080
```

Output: `report.json`

## Example Result

```
POST /users
  PASS  happy_path                       201    23 ms
  FAIL  required_missing  body.name       500    11 ms
  PASS  required_missing  body.email      400     8 ms

TestPilot Summary

  Endpoints         3
  Cases            16
  Passed            7
  Failed            9
  Errors            0
  Pass rate    43.8%

Report: ./report.json
```

## CLI Options

```
python -m testpilot run [OPTIONS]

Required:
  --openapi TEXT       OpenAPI spec URL or local file path
  --base-url TEXT      Target API base URL

Optional:
  --output, -o PATH    Report output path (default: report.json)
  --max-cases INT      Max test cases per endpoint (default: 20)
  --timeout INT        HTTP timeout in seconds (default: 30)
  --include-tag TEXT   Only test endpoints with these tags (repeatable)
  --exclude-tag TEXT   Skip endpoints with these tags (repeatable)
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All tests passed |
| 1 | API defects or test failures detected |
| 2 | TestPilot could not complete the run |

## Authentication

Set bearer token via environment variable:

```bash
export TESTPILOT_BEARER_TOKEN=your-token-here
python -m testpilot run --openapi ... --base-url ...
```

Token is never printed to the console or written to the report.

## Current Scope

**Supported:**
- OpenAPI 3.0.x
- Deterministic happy path / negative API testing
- Scenarios: happy_path, required_missing, null, wrong_type
- JSON report with sensitive value redaction
- Spring Boot / Swagger / springdoc-openapi

**Not yet supported:**
- OpenAPI 3.1
- LLM semantic test planning
- API dependency propagation
- DB / Redis validation
- Browser / UI testing
- HTML report
