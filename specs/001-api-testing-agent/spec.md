# Feature Spec: TestPilot V1 - OpenAPI API Testing Agent

## 1. 背景

传统 Spring Boot 项目的接口测试通常依赖人工阅读 Swagger、构造请求、设计边界条件、执行测试和整理报告。

TestPilot 希望通过 OpenAPI + LLM + 确定性测试组件，降低 API 黑盒测试的人力成本。

## 2. 目标用户

- Java / Spring Boot 后端开发者
- QA / 测试工程师
- 使用 Swagger / OpenAPI 描述 REST API 的团队

## 3. 用户输入

用户至少提供：

- OpenAPI URL 或本地文件
- Target Base URL

可选：

- Bearer Token
- 自定义 Header
- Include Tags
- Exclude Tags
- 单次每个 Endpoint 最大 Case 数

## 4. 核心用户故事

### US-001 读取 OpenAPI

作为开发者，我希望提供 `/v3/api-docs` 地址后，TestPilot 自动读取并解析所有 REST Endpoint。

### US-002 选择测试范围

作为开发者，我希望按 Tag / Endpoint 选择测试范围，避免一次性测试整个系统。

### US-003 生成测试场景

作为开发者，我希望 TestPilot 结合 OpenAPI Schema 和接口语义，自动生成正常、边界和异常测试场景。

### US-004 执行 HTTP 测试

作为开发者，我希望 TestPilot 自动构造 HTTP 请求并记录 Status、Response、Headers 和耗时。

### US-005 自动判断明显错误

作为开发者，我希望 5xx、Schema 不一致、明显非法参数被接受等情况能够自动判定为失败或警告。

### US-006 分析失败原因

作为开发者，我希望失败 Case 能得到简洁的 AI 分析，包括可能原因、严重程度和排查建议。

### US-007 生成报告

作为开发者，我希望最终得到 JSON 和 HTML 报告，方便复盘和演示。

## 5. V1 支持的测试类型

至少支持：

- Happy Path
- Required Field Missing
- Null Value
- Wrong Type
- Empty String
- String Boundary
- Number Boundary
- Invalid Enum
- Invalid Path ID
- Missing Authentication

不是所有 Endpoint 都必须生成全部类型。

## 6. V1 非目标

明确不做：

- Web UI 测试
- Playwright
- Selenium
- 自动修复后端代码
- 自动 Git Commit
- 强化学习
- Multi-Agent RL
- SQL / Redis 状态联合验证
- 自动登录并维护复杂 Session
- 接口 Dependency Graph
- CI/CD 平台

以上能力进入后续版本。

## 7. 输出

每次运行至少生成：

- `report.json`
- `report.html`
- `cases.json`
- `executions.json`

## 8. 成功标准

给定一个可访问的 Spring Boot OpenAPI：

1. 能成功解析 Endpoint。
2. 能选择指定 Tag。
3. 能生成 Test Scenario。
4. 能生成可执行 TestCase。
5. 能真实发送 HTTP。
6. 能记录请求与响应。
7. 能识别至少一种故意注入的后端 Bug。
8. 能生成 HTML / JSON 报告。
9. pytest 通过。
10. 不违反 `constitution.md`。

## 9. Demo 要求

项目必须附带一个公开、可控的 intentionally buggy Demo API。

例如：

`POST /users`

请求：

```json
{
  "name": null
}
```

Demo 故意返回：

`500 Internal Server Error`

TestPilot 应稳定检测到并在报告中标记为失败。

## 10. 后续 Roadmap

V1.5：
- Schemathesis Adapter
- Coverage

V2：
- Producer-Consumer Dependency
- 跨接口参数传递
- 自动登录 / Token 获取

V2.5：
- SQL Read-only Validator
- Redis Read-only Validator
- MCP Tool

V3：
- Playwright UI Testing
