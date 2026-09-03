# TestPilot V1 Implementation Plan

Phase 0 输出文档 | 日期：2026-09-02  
Phase 0 Review 修订 | 日期：2026-09-02

---

## 1. 技术栈

| 类别 | 选型 | 版本 | 理由 |
|------|------|------|------|
| 语言 | Python | 3.11+ | 生态成熟，Pydantic v2 原生支持 |
| Agent 框架 | LangGraph | latest | 轻量编排，State 管理清晰 |
| LLM 集成 | LangChain Core | latest | Structured Output，工具绑定 |
| 数据模型 | Pydantic | v2 | 类型安全，序列化，Structured Output |
| OpenAPI 解析 | Prance | latest | 成熟的 $ref resolution，支持 recursive/external ref |
| OpenAPI 校验 | openapi-spec-validator | latest | Prance 依赖，提供 spec 校验 |
| HTTP 客户端 | httpx | latest | 异步支持，比 requests 更现代 |
| YAML 解析 | PyYAML | latest | 辅助 YAML 处理 |
| JSON Schema | jsonschema | latest | 响应验证 |
| 模板引擎 | Jinja2 | latest | HTML 报告生成 |
| CLI | Typer | latest | 类型安全的 CLI 框架 |
| 终端美化 | Rich | latest | 进度条，表格，日志美化 |
| 测试框架 | pytest | latest | 标准 Python 测试 |

**说明**：
- Prance 负责 OpenAPI spec 加载、校验、`$ref` resolution（含 recursive ref、external ref）
- TestPilot 不自行实现 OpenAPI 标准能力，只做 resolved dict → Pydantic Domain Model 的薄映射
- V1 LLM 仅使用 OpenAI-Compatible API，不实现多 Provider 适配

---

## 2. 目录结构

```text
testpilot-agent/
├── AGENTS.md                          # AI Coding 工具指导文件
├── constitution.md                    # 工程原则
├── pyproject.toml                     # 项目配置，依赖管理
├── README.md                          # 项目说明
├── .env.example                       # 环境变量示例
├── config.example.yaml                # 配置文件示例
│
├── specs/
│   └── 001-api-testing-agent/
│       ├── spec.md                    # 功能规格
│       ├── plan.md                    # 实现计划（原始）
│       └── tasks.md                   # 任务清单
│
├── docs/
│   ├── architecture-analysis.md       # 架构分析
│   ├── implementation-plan.md         # 实现计划（本文档）
│   └── progress.md                    # 进度跟踪
│
├── src/
│   └── testpilot/
│       ├── __init__.py                # 包初始化
│       ├── __main__.py                # python -m testpilot 入口
│       ├── cli.py                     # Typer CLI 定义
│       ├── config.py                  # AppConfig 配置管理
│       │
│       ├── domain/                    # Domain Model（Pydantic）
│       │   ├── __init__.py
│       │   ├── spec.py                # ApiSpec, ApiEndpoint, ApiParameter
│       │   ├── schema.py              # ApiSchema, ApiRequestBody, ApiResponse
│       │   ├── scenario.py            # TestScenario
│       │   ├── testcase.py            # TestCase
│       │   ├── execution.py           # ExecutionResult
│       │   ├── validation.py          # ValidationResult, CheckResult
│       │   └── analysis.py            # FailureAnalysis
│       │
│       ├── openapi/                   # OpenAPI 处理
│       │   ├── __init__.py
│       │   ├── loader.py              # Prance 加载 + $ref resolution
│       │   ├── mapper.py              # resolved dict → Domain Model（薄映射）
│       │   └── selector.py            # Endpoint 过滤（tag/path）
│       │
│       ├── planner/                   # 测试场景生成
│       │   ├── __init__.py
│       │   ├── deterministic.py       # 确定性场景生成（10 类，Phase 2）
│       │   ├── llm_planner.py         # LLM 语义场景补充（Phase 3）
│       │   └── prompts/               # Prompt 模板文件
│       │       └── plan_tests.txt
│       │
│       ├── generator/                 # TestCase 生成
│       │   ├── __init__.py
│       │   └── generator.py           # TestScenario → TestCase
│       │
│       ├── executor/                  # HTTP 执行
│       │   ├── __init__.py
│       │   └── executor.py            # httpx 请求发送
│       │
│       ├── validator/                 # 确定性验证
│       │   ├── __init__.py
│       │   └── validator.py           # 规则引擎验证
│       │
│       ├── analyzer/                  # LLM 失败分析（Phase 4）
│       │   ├── __init__.py
│       │   ├── service.py             # Analyzer 业务逻辑
│       │   └── prompts/
│       │       └── analyze_failure.txt
│       │
│       ├── report/                    # 报告生成
│       │   ├── __init__.py
│       │   ├── json_report.py         # JSON 报告（Phase 2）
│       │   ├── html_report.py         # HTML 报告（Phase 5）
│       │   └── templates/
│       │       └── report.html
│       │
│       ├── graph/                     # LangGraph 编排（Phase 3+）
│       │   ├── __init__.py
│       │   ├── state.py               # TestAgentState 定义
│       │   └── graph.py               # LangGraph 图定义
│       │
│       └── llm/                       # LLM 客户端（Phase 3+）
│           ├── __init__.py
│           └── client.py              # 统一 LLM 调用（OpenAI-Compatible）
│
├── tests/
│   ├── __init__.py
│   ├── unit/                          # 单元测试
│   │   ├── __init__.py
│   │   ├── test_openapi_mapper.py
│   │   ├── test_deterministic_planner.py
│   │   ├── test_generator.py
│   │   ├── test_validator.py
│   │   └── test_report.py
│   ├── integration/                   # 集成测试
│   │   ├── __init__.py
│   │   └── test_springboot_demo.py
│   └── fixtures/                      # 测试数据
│       ├── petstore.yaml              # OpenAPI spec 示例
│       └── expected_results.json
│
├── examples/
│   └── springboot-demo/               # Demo Spring Boot 项目
│       ├── src/
│       ├── pom.xml
│       └── README.md
│
└── reports/                           # 运行输出目录
```

---

## 3. 开发阶段规划

### 3.1 Resume MVP（最短可演示闭环）

**目标**：尽快形成可运行、可演示的端到端闭环。能真实测试一个 Spring Boot Demo，稳定发现故意注入的 Bug。

**最短链路**：

```text
OpenAPI → Loader/Resolver(Prance) → Domain Mapper → Deterministic Scenario/TestCase → HTTP Executor → Validator → JSON Report
```

**包含**：
- Python 工程骨架 + pyproject.toml
- Pydantic Domain Model（ID 引用关系）
- OpenAPI Loader（Prance）+ Domain Mapper
- Endpoint Selector
- Deterministic Scenario Generator（至少覆盖 happy_path, required_missing, null, wrong_type, 5xx 检测）
- TestCase Generator + Request Builder
- HTTP Executor（httpx 同步）
- Deterministic Validator（5xx, schema 不一致, invalid input accepted）
- JSON Report
- Spring Boot Demo（intentionally buggy）
- 集成测试：能检测到 Demo 中故意注入的 Bug

**不要求**：
- 完整 10 类测试场景全部做到很复杂
- HTML 精美报告
- LLM Planner
- Failure Analyzer
- LangGraph 完整工作流
- 多 LLM Provider

**验收标准**：
1. `python -m testpilot run --openapi <url> --base-url <url>` 可执行
2. 真实发送 HTTP 到 Spring Boot Demo
3. 稳定检测到至少 1 个故意注入的 Bug
4. 生成 `report.json`，包含 test case、执行结果、验证结果
5. pytest 全部通过
6. 不违反 constitution

---

### 3.2 Phase 1 - Foundation（Resume MVP 的前半段）

**目标**：项目骨架 + Domain Model + OpenAPI 解析。

| 任务 | 描述 | 依赖 | 验收标准 |
|------|------|------|----------|
| T0101 | 初始化 pyproject.toml（含 Prance 依赖） | 无 | 可安装 |
| T0102 | 创建 src/testpilot/ 目录结构 | T0101 | 目录存在 |
| T0103 | 定义 AppConfig（含 target_base_url） | T0102 | 可从 YAML 加载 |
| T0104-T0111 | 定义所有 Domain Model（ID 引用关系） | T0102 | Pydantic 可序列化 |
| T0112 | 实现 OpenAPI Loader（Prance） | T0104 | 支持 URL/JSON/YAML |
| T0113 | 实现 Domain Mapper（薄映射） | T0112 | petstore.yaml → ApiSpec |
| T0114 | 实现 Endpoint Selector | T0113 | 按 tag/path 过滤 |
| T0115-T0116 | 添加 Mapper 测试 | T0114 | pytest 通过 |
| T0117 | Phase 1 全量 pytest | T0116 | 全部通过 |
| T0118 | 更新 progress.md | T0117 | 记录完成状态 |

**关键决策**：
- OpenAPI 解析：使用 **Prance**，不自研 `$ref` resolver
- Prance 负责：加载 spec、校验、`$ref` resolution、recursive ref 处理
- TestPilot 自己只做：resolved dict → Pydantic Domain Model 的薄映射
- Domain Model 使用 ID 引用，不嵌套完整对象

---

### 3.3 Phase 2 - Deterministic Testing Pipeline（Resume MVP 的后半段）

**目标**：完整的确定性测试链路，不依赖 LLM。形成 Resume MVP 闭环。

| 任务 | 描述 | 依赖 | 验收标准 |
|------|------|------|----------|
| T0201 | 实现 Deterministic Scenario Generator | Phase 1 | 生成 TestScenario |
| T0202 | 实现 TestCase Generator（含 RequestBuilder） | T0201 | TestCase 可构建完整请求 |
| T0203 | 实现 HTTP Executor（httpx 同步） | T0202 | 真实发送 HTTP |
| T0204 | 实现 transport error handling | T0203 | 超时/连接错误被捕获 |
| T0205 | 实现 Validator 规则（5xx, schema, input） | T0204 | 自动判定 pass/fail |
| T0206 | 实现 JSON Report | T0205 | report.json 生成 |
| T0207 | 创建 Spring Boot Demo（intentionally buggy） | 无 | 可运行 |
| T0208 | 集成测试（检测 Demo 中的 Bug） | T0207 | 至少 1 个 Bug 被发现 |
| T0209 | 完善 CLI（`python -m testpilot run`） | T0208 | 命令行可执行 |
| T0210 | Phase 2 全量 pytest | T0209 | 全部通过 |
| T0211 | 更新 progress.md | T0210 | 记录完成状态 |

**确定性 Scenario 类型**（Phase 2 至少实现前 4 类，其余逐步完善）：

| 类型 | 优先级 | 说明 |
|------|:------:|------|
| happy_path | P0 | 使用 example/default 合法值 |
| required_missing | P0 | 缺失必填字段 |
| null | P0 | 必填字段传 null |
| wrong_type | P0 | 字段类型错误 |
| 5xx 检测 | P0 | 服务端错误自动 fail |
| empty_string | P1 | 空字符串 |
| string_boundary | P1 | 字符串长度边界 |
| number_boundary | P1 | 数值范围边界 |
| invalid_enum | P1 | 无效枚举值 |
| invalid_path_id | P2 | 无效路径 ID |
| missing_auth | P2 | 缺失认证 |

---

### 3.4 Phase 3 - LLM Test Planner（V1 Complete 的一部分）

**目标**：接入 LLM，生成语义层面的补充测试场景。接入 LangGraph 编排。

| 任务 | 描述 | 依赖 | 验收标准 |
|------|------|------|----------|
| T0301 | 实现 LLMClient（OpenAI-Compatible） | Resume MVP | 可调用 LLM |
| T0302 | 定义 Planner Structured Output | T0301 | Pydantic schema |
| T0303 | 编写 Planner Prompt | T0302 | 含 endpoint 信息 |
| T0304 | 实现 LLM Planner Service | T0303 | 返回 TestScenario |
| T0305 | 实现 Scenario 合并去重 | T0304 | 确定性 + LLM 场景合并 |
| T0306 | 实现 LangGraph State + Graph | T0305 | Node 编排正确 |
| T0307 | 实现 LLM 超时/错误降级 | T0306 | 失败时降级到确定性 |
| T0308 | 添加 Planner 测试 | T0307 | pytest 通过 |
| T0309 | Phase 3 全量 pytest | T0308 | 全部通过 |
| T0310 | 更新 progress.md | T0309 | 记录完成状态 |

**关键决策**：
- LLM 仅使用 OpenAI-Compatible API（通过 `llm_base_url` + `llm_model` 配置）
- 业务代码通过 `LLMClient` 统一边界调用，不直接依赖具体 Provider SDK
- 降级策略：LLM 超时或失败时，仅使用确定性场景，不阻塞流程

---

### 3.5 Phase 4 - Failure Analyzer（V1 Complete 的一部分）

**目标**：LLM 分析失败测试用例的原因。

| 任务 | 描述 | 依赖 | 验收标准 |
|------|------|------|----------|
| T0401 | 定义 FailureAnalysis Model | Phase 3 | Pydantic schema |
| T0402 | 编写 Analyzer Prompt | T0401 | 含请求/响应信息 |
| T0403 | 实现 Analyzer Service | T0402 | 返回 FailureAnalysis |
| T0404 | 仅对失败 Case 调用 LLM | T0403 | 性能优化 |
| T0405 | 标记 AI 分析来源 | T0404 | 报告中可区分 |
| T0406 | 添加 Analyzer 测试 | T0405 | pytest 通过 |
| T0407 | Phase 4 全量 pytest | T0406 | 全部通过 |
| T0408 | 更新 progress.md | T0407 | 记录完成状态 |

---

### 3.6 Phase 5 - Report & Demo（V1 Complete 的一部分）

**目标**：HTML 报告，完善 CLI，文档。

| 任务 | 描述 | 依赖 | 验收标准 |
|------|------|------|----------|
| T0501 | 实现 HTML Report Template | Phase 4 | Jinja2 模板 |
| T0502-T0506 | 报告内容完善 | T0501 | Summary/Endpoint/Case/Request/Response/Analysis |
| T0507 | 完善 CLI 参数 | T0502 | 完整参数支持 |
| T0508 | 完善 README | T0507 | Quick Start 可跟随 |
| T0509 | 完善 Demo 文档 | T0508 | Demo 可运行 |
| T0510 | 全量测试 | T0509 | pytest 通过 |
| T0511 | Constitution 最终检查 | T0510 | 无违反 |
| T0512 | 生成 V1 Release Checklist | T0511 | 清单完整 |

---

## 4. 依赖关系

```text
Phase 1 (Foundation)
  ↓
Phase 2 (Deterministic Pipeline)  ← Resume MVP 完成
  ↓
Phase 3 (LLM Planner + LangGraph) ← V1 Complete 开始
  ↓
Phase 4 (Failure Analyzer)
  ↓
Phase 5 (Report & Demo)
```

Resume MVP = Phase 1 + Phase 2，完成后即可演示端到端闭环。

---

## 5. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Prance 对某些复杂 spec 兼容性不足 | 解析失败 | Prance 支持 lenient 模式；必要时记录跳过的 spec 部分 |
| LLM 输出不稳定 | Planner/Analyzer 结果不一致 | Structured Output + 重试 + 降级到确定性 |
| Spring Boot Demo 难以构建 | 集成测试受阻 | 使用现有公开 API（如 Petstore）作为备选 |
| httpx 异步复杂度 | Executor 实现困难 | Resume MVP 用同步模式 |
| LLM API 不可用 | Phase 3/4 阻塞 | 降级策略：LLM 失败时仅使用确定性场景 |

---

## 6. 验收标准

### Resume MVP 验收

1. `python -m testpilot run --openapi <url> --base-url <url>` 可执行
2. 真实发送 HTTP 到 Spring Boot Demo
3. 稳定检测到至少 1 个故意注入的 Bug
4. 生成 `report.json`
5. pytest 全部通过
6. 不违反 constitution

### V1 Complete 验收

1. 包含 Resume MVP 全部能力
2. LLM Planner 补充语义场景
3. Failure Analyzer 分析失败原因
4. LangGraph 编排完整工作流
5. HTML 报告生成
6. 全量 pytest 通过
7. 无 constitution 违反
8. 目录职责清晰
9. 无跨层依赖
10. LLM 输出 Structured
11. 更新 progress.md
12. 记录新增技术债
