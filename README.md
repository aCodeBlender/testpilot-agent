[English](README.md) | [简体中文](README.zh-CN.md)

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
  --goal TEXT          Natural-language testing goal (enables LLM semantic planning)
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

## LLM Semantic Testing

When `--goal` is provided, TestPilot uses an LLM to generate additional semantic test scenarios beyond the deterministic ones. These scenarios probe for format violations, boundary conditions, and type confusion that deterministic generation cannot cover.

### Configuration

Set LLM credentials via environment variables or a `.env` file.

**Option A: Environment variables**

```bash
export TESTPILOT_LLM_API_KEY=sk-your-key-here
export TESTPILOT_LLM_BASE_URL=https://api.openai.com/v1
export TESTPILOT_LLM_MODEL=gpt-4o-mini
```

**Option B: `.env` file**

Copy the example and fill in your values:

```bash
cp .env.example .env
# Edit .env with your credentials
```

The `.env` file is loaded automatically at startup. Explicitly defined environment variables always take precedence over `.env` values.

### How it works

1. **Intent Planning** — The LLM selects which endpoints to test based on your goal
2. **Semantic Planning** — The LLM proposes creative negative test scenarios (format violations, boundary values, type confusion)
3. **Eligibility Filtering** — Proposals are checked against schema constraints; only those that provably violate a constraint are executed
4. **Execution** — Semantic tests run through the same HTTP → Validate → Report pipeline as deterministic tests

Semantic scenarios appear in the report with `"source": "llm"` and `"category": "semantic_negative"`.

### Safety

- LLM failures never abort the run — deterministic tests always complete
- Only body-parameter mutations are attempted (no path/query/header mutations)
- Proposals that cannot be verified against the schema are silently skipped
- API keys are never printed or written to the report

## Current Scope

**Supported:**
- OpenAPI 3.0.x
- Deterministic happy path / negative API testing
- Scenarios: happy_path, required_missing, null, wrong_type
- LLM-powered semantic negative testing (with `--goal`)
- JSON report with sensitive value redaction and source provenance
- Spring Boot / Swagger / springdoc-openapi

**Not yet supported:**
- OpenAPI 3.1
- API dependency propagation
- DB / Redis validation
- Browser / UI testing
- HTML report
