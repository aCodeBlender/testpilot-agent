# TestPilot Spring Boot Demo

Minimal Spring Boot REST API used as a **test target** for the TestPilot Resume MVP pipeline.

This is a deliberately small demo with an **intentional bug** that TestPilot should detect.

## Quick Start

```bash
cd demo/springboot-demo
mvn spring-boot:run
```

The server starts on port **8080**.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/users` | Create a new user |
| `GET` | `/users/{id}` | Get user by ID |
| `GET` | `/users` | List all users (optional `?limit=N`) |

## OpenAPI / Swagger

- **OpenAPI JSON**: http://localhost:8080/v3/api-docs
- **Swagger UI**: http://localhost:8080/swagger-ui/index.html

## Intentional Bug — `POST /users` missing name → 500

The OpenAPI spec declares `name` as **required** in the `POST /users` request body.

However, the controller does **not** use `@Valid` for Bean Validation, so a null `name` reaches the service layer and triggers a `NullPointerException` → HTTP **500**.

The correct behavior would be HTTP **400**.

### Why this matters

TestPilot's deterministic pipeline should detect this contract violation:

1. Reads OpenAPI → sees `name` is required
2. Generates `required_missing body.name` scenario
3. Sends `POST /users` without `name`
4. Expects 4xx rejection
5. Gets 500 → **FAIL**

This demonstrates TestPilot's ability to find server-side input handling defects automatically.

## Running Tests

```bash
mvn test
```

Test `intentionalBug_missingName_returns500` **locks** the bug — if someone accidentally fixes it, the test will fail, alerting us that the demo target changed.

## Tech Stack

- Java 17
- Spring Boot 3.2.5
- springdoc-openapi 2.3.0
- In-memory storage (no database)
