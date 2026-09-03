# Tasks: TestPilot V1

任务必须按阶段执行。

---

## Resume MVP 摘要

Resume MVP = Phase 1 + Phase 2。

最短链路：OpenAPI → Loader/Resolver(Prance) → Domain Mapper → Deterministic Scenario/TestCase → HTTP Executor → Validator → JSON Report

不依赖 LLM、LangGraph、HTML Report。

完成标志：能真实测试 Spring Boot Demo，稳定发现故意注入的 Bug。

---

## Phase 0 - Reference Analysis

- [x] T0001 阅读 `constitution.md`
- [x] T0002 阅读 `spec.md`
- [x] T0003 阅读 `plan.md`
- [x] T0004 按 `AGENTS.md` 白名单阅读 AutoRestTest
- [x] T0005 按 `AGENTS.md` 白名单阅读 TestCraft API Automation Agent
- [x] T0006 禁止默认扫描两个参考仓库的其余目录
- [x] T0007 输出 `docs/architecture-analysis.md`
- [x] T0008 输出 `docs/implementation-plan.md`
- [x] T0009 创建 `docs/progress.md`
- [x] T0010 给出计划目录树
- [x] T0011 输出"参考设计采用表"
- [x] T0012 输出"参考设计明确不采用表"
- [x] T0013 对照 constitution 做首次架构自检
- [x] T0014 检查是否存在无必要参考范围扩张
- [x] T0015 Phase 0 Review 修订：Domain Model ID 引用、Prance Loader、ApiSpec/Config 解耦、Resume MVP、无 DI、单一 LLM Client

Phase 0 完成后停止编码，等待人工 Review。

---

## Phase 1 - Foundation（Resume MVP 前半段）

- [x] T0101 初始化 `pyproject.toml`（含 Prance 依赖）
- [x] T0102 创建 `src/testpilot/` 目录结构
- [x] T0103 创建 AppConfig（含 `target_base_url`，与 ApiSpec 解耦）
- [x] T0104 定义 ApiSpec（含 servers，不含 target_base_url）
- [x] T0105 定义 ApiEndpoint（含 `id` 字段）
- [x] T0106 定义 ApiParameter（字段名 `param_schema`）
- [x] T0107 定义 ApiRequestBody（`body_schema`）/ ApiSchema / ApiResponse（`content_schema`）
- [x] T0108 定义 TestScenario（含 `endpoint_id` 引用）
- [x] T0109 定义 TestCase（含 `endpoint_id`, `scenario_id`, `method`, `path`）
- [x] T0110 定义 ExecutionResult（含 `case_id` 引用）
- [x] T0111 定义 ValidationResult / CheckResult（含 `case_id` 引用）
- [x] T0112 实现 OpenAPI Loader（Prance 加载 + $ref resolution + 校验）
- [x] T0113 实现 Domain Mapper（resolved dict → Pydantic Domain Model，薄映射）
- [x] T0114 实现 Endpoint Selector（tag / path 过滤）
- [x] T0115 添加 Mapper 单元测试（petstore.yaml fixture）
- [x] T0116 Phase 1 全量 pytest
- [x] T0117 更新 progress.md

---

## Phase 2 - Deterministic Testing Pipeline（Resume MVP 后半段）

- [x] T0201 实现 Deterministic Scenario Generator（happy_path, required_missing, null, wrong_type 等）
- [x] T0202 实现 TestCase Generator（TestScenario → TestCase，含合法值/边界值/错误值填充）
- [x] T0203 实现 RequestBuilder（使用 `AppConfig.target_base_url + TestCase.path` 构造最终 URL）
- [x] T0204 实现 HTTP Executor（httpx 同步，含 transport error handling）
- [x] T0205 实现 Validator（5xx, response schema, invalid input accepted, auth bypass）
- [x] T0206 实现 JSON Report
- [x] T0207 创建 intentionally buggy Spring Boot Demo
- [x] T0208 完成集成测试（检测 Demo 中故意注入的 Bug）
- [x] T0209 完善 CLI（`python -m testpilot run`）
- [x] T0210 Phase 2 全量 pytest
- [x] T0211 更新 progress.md

**Resume MVP 完成标志**：
- `python -m testpilot run --openapi <url> --base-url <url>` 可执行
- 真实发送 HTTP 到 Spring Boot Demo
- 稳定检测到至少 1 个故意注入的 Bug
- 生成 `report.json`
- pytest 全部通过

---

## Phase 3 - LLM Test Planner

- [ ] T0301 实现 LLMClient（OpenAI-Compatible API，统一调用边界）
- [ ] T0302 定义 Planner Structured Output（Pydantic schema）
- [ ] T0303 编写 Planner Prompt
- [ ] T0304 实现 LLM Semantic Planner Service（补充业务语义场景，不重复基础 Schema Case）
- [ ] T0305 实现 Scenario 合并去重（Deterministic + LLM → 统一 TestScenario 列表）
- [ ] T0306 接入 LangGraph（State 定义 + Graph 编排）
- [ ] T0307 实现 LLM 超时 / 错误降级（失败时仅使用确定性场景）
- [ ] T0308 添加 Planner 测试
- [ ] T0309 Phase 3 全量 pytest
- [ ] T0310 更新 progress.md

---

## Phase 4 - Failure Analyzer

- [ ] T0401 定义 FailureAnalysis Model（含 `case_id` 引用）
- [ ] T0402 编写 Failure Analyzer Prompt
- [ ] T0403 实现 Failure Analyzer（通过同一 LLMClient 调用）
- [ ] T0404 仅对失败 Case 调用 LLM
- [ ] T0405 标记 AI Analysis / Possible Cause
- [ ] T0406 添加 Analyzer 测试
- [ ] T0407 Phase 4 全量 pytest
- [ ] T0408 更新 progress.md

---

## Phase 5 - Report & Demo

- [ ] T0501 实现 HTML Report Template
- [ ] T0502 展示 Summary
- [ ] T0503 展示 Endpoint / Case
- [ ] T0504 展示 Request / Response
- [ ] T0505 展示 Validation Result
- [ ] T0506 展示 AI Failure Analysis
- [ ] T0507 完善 `python -m testpilot` CLI
- [ ] T0508 完善 README Quick Start
- [ ] T0509 完善 Demo 文档
- [ ] T0510 全量测试
- [ ] T0511 Constitution 最终检查
- [ ] T0512 生成 V1 Release Checklist

---

## V1.5 - 暂不执行

- [ ] Schemathesis Adapter
- [ ] API Coverage
- [ ] Stateful Testing

## V2 - 暂不执行

- [ ] Producer-Consumer Dependency
- [ ] Dependency Graph
- [ ] response value extraction
- [ ] cross-endpoint parameter injection
- [ ] auto login/token

## V2.5 - 暂不执行

- [ ] SQL read-only validator
- [ ] Redis read-only validator
- [ ] MCP integration

## V3 - 暂不执行

- [ ] Playwright
- [ ] Browser Testing
