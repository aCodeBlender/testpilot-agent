# Implementation Plan: TestPilot V1

## 1. 技术栈

- Python 3.11+
- LangGraph
- LangChain Core
- Pydantic v2
- Prance（OpenAPI 加载 + $ref resolution）
- openapi-spec-validator（Prance 依赖，spec 校验）
- httpx
- PyYAML
- jsonschema
- Jinja2
- Typer
- Rich
- pytest

可选后续：
- Schemathesis
- SQLAlchemy / psycopg
- redis
- MCP SDK
- Playwright

## 2. 总体架构

```text
CLI
 ↓
OpenAPI Loader（Prance: 加载 + $ref resolution + 校验）
 ↓
Domain Mapper（薄映射: resolved dict → Pydantic Domain Model）
 ↓
Endpoint Selector
 ↓
Scenario Generator
 ├─ Deterministic Scenario Generator（Phase 2）
 └─ LLM Semantic Planner（Phase 3）
 ↓
Test Case Generator
 ↓
HTTP Executor
 ↓
Deterministic Validator
 ↓
LLM Failure Analyzer（Phase 4）
 ↓
Report Generator（JSON: Phase 2, HTML: Phase 5）
```

## 3. 模块职责

### domain/

定义稳定的数据协议，使用 ID 引用代替层层嵌套。

建议模型：
- ApiSpec（含 servers，不含 target_base_url）
- ApiEndpoint（含 id）
- ApiParameter
- ApiRequestBody
- ApiSchema
- ApiResponse
- TestScenario（含 endpoint_id）
- TestCase（含 endpoint_id, scenario_id, method, path）
- ExecutionResult（含 case_id）
- ValidationResult（含 case_id）
- FailureAnalysis（含 case_id）

### openapi/

负责：
- loader.py：调用 Prance 加载 URL / JSON / YAML，处理 $ref resolution 和校验
- mapper.py：resolved dict → Pydantic Domain Model（薄映射，不自行实现 OpenAPI 标准）
- selector.py：按 tag / path 过滤 endpoint

不自行实现：$ref 解析、JSON Pointer、external ref、recursive ref、OpenAPI 校验。

### planner/

两个独立来源，输出统一的 TestScenario：

- deterministic.py：确定性场景生成（Phase 2）
  - happy_path, required_missing, null, wrong_type, empty_string,
    string_boundary, number_boundary, invalid_enum, invalid_path_id, missing_auth
- llm_planner.py：LLM 语义场景补充（Phase 3）
  - 补充业务语义型场景，不重复基础 Schema Case

两类 TestScenario 合并、按 (endpoint_id, category, name) 去重后进入 generator。

不引入 Factory / Strategy / Registry。两个 Generator 是两个普通函数。

### generator/

负责：
- TestScenario → TestCase
- Schema 基础合法值生成
- RequestBuilder：使用 AppConfig.target_base_url + TestCase.path 构造最终 URL

### executor/

使用 httpx。

输入：
- TestCase（含 method, path, headers, params, body）
- AppConfig.target_base_url

输出：
- ExecutionResult（含 case_id）

不调用 LLM。

### validator/

规则优先：
- unexpected 5xx
- response schema violation
- invalid input accepted
- auth bypass
- transport error

### analyzer/

仅处理失败 Case。

通过 LLM 输出 Structured FailureAnalysis。

V1 只使用一个 OpenAI-Compatible LLM Client。

### report/

生成：
- JSON（Phase 2）
- HTML（Phase 5）

### graph/

LangGraph 仅编排（Phase 3+）。

### llm/

统一 LLM 调用边界（Phase 3+）。

V1 只实现一个 OpenAI-Compatible API，不做复杂多 Provider 适配。

业务代码通过 LLMClient 调用，不直接依赖具体 Provider SDK。

## 4. 推荐目录

```text
testpilot-agent/
├── AGENTS.md
├── constitution.md
├── pyproject.toml
├── README.md
├── .env.example
├── config.example.yaml
│
├── specs/
│   └── 001-api-testing-agent/
│       ├── spec.md
│       ├── plan.md
│       └── tasks.md
│
├── docs/
│   ├── architecture-analysis.md
│   ├── implementation-plan.md
│   └── progress.md
│
├── src/
│   └── testpilot/
│       ├── __init__.py
│       ├── __main__.py
│       ├── cli.py
│       ├── config.py
│       ├── domain/
│       ├── openapi/
│       │   ├── loader.py
│       │   ├── mapper.py
│       │   └── selector.py
│       ├── planner/
│       │   ├── deterministic.py
│       │   ├── llm_planner.py
│       │   └── prompts/
│       ├── generator/
│       ├── executor/
│       ├── validator/
│       ├── analyzer/
│       ├── report/
│       ├── graph/
│       └── llm/
│
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│
├── examples/
│   └── springboot-demo/
│
└── reports/
```

## 5. CLI 命名

统一使用：

```bash
python -m testpilot run \
  --openapi http://localhost:8080/v3/api-docs \
  --base-url http://localhost:8080
```

## 6. 数据生成优先级

```text
OpenAPI example
→ OpenAPI default
→ Deterministic Schema Generator
→ LLM Semantic Value
```

LLM 不应承担基础值生成。

## 7. Auth

V1 支持：
- Bearer Token
- Static Headers

V1 不实现自动登录链。

## 8. LangGraph State

```python
class TestAgentState(TypedDict):
    config: AppConfig
    api_spec: ApiSpec | None
    endpoints: list[ApiEndpoint]
    selected_endpoints: list[ApiEndpoint]
    scenarios: list[TestScenario]
    test_cases: list[TestCase]
    execution_results: list[ExecutionResult]
    validation_results: list[ValidationResult]
    failure_analyses: list[FailureAnalysis]
    report_path: str | None
    errors: list[str]
```

所有集合以扁平列表保存，通过 ID 互相引用（endpoint_id, scenario_id, case_id）。
为后续持久化、Regression Memory 和跨运行历史记录留出空间，但 V1 不实现长期 Memory。

## 9. Phase 规划

### Resume MVP

最短可演示闭环（Phase 1 + Phase 2）：

OpenAPI → Loader/Resolver(Prance) → Domain Mapper → Deterministic Scenario/TestCase → HTTP Executor → Validator → JSON Report

不依赖 LLM、LangGraph、HTML Report。

### Phase 1 - Foundation

- Python 工程骨架
- Pydantic Domain Model（ID 引用关系）
- OpenAPI Loader（Prance）
- Domain Mapper（薄映射）
- Endpoint Selector
- Unit Tests

### Phase 2 - Deterministic Testing Pipeline

- Deterministic Scenario Generator（10 类场景）
- Test Case Generator + RequestBuilder
- HTTP Executor
- Validator
- JSON Report
- Spring Boot Demo Integration Test

此阶段不接 LLM。完成此阶段即 Resume MVP。

### Phase 3 - LLM Test Planner

- LLM Client（OpenAI-Compatible）
- Structured Output
- LLM Semantic Planner
- Scenario 合并去重
- LangGraph 编排
- LLM 超时 / 错误降级

### Phase 4 - Failure Analyzer

- FailureAnalysis Model
- Failure Analyzer Prompt
- Failure Analyzer
- 仅对失败 Case 调用 LLM

### Phase 5 - Report & Demo

- HTML Report
- README
- Demo 文档

## 10. 参考项目映射

AutoRestTest：
- 参考 OpenAPI → Domain Model 转换思路、ParameterKey、SchemaProperties 建模
- 直接使用 Prance 做 $ref resolution，不自研
- Phase 0 不读 RL / MARL / 实验代码

TestCraft API Automation Agent：
- 参考 Processor / Service 分层、Prompt 文件化、LLM 集中封装、Orchestrator 薄编排
- V1 不引入 DI 容器，通过构造函数注入
- Phase 0 不读 benchmark / evaluation / template

RESTler：
- V2 才参考 Producer-Consumer dependency

Schemathesis：
- V1.5 属性测试与 Stateful Testing

mini-claude-code：
- 后续按需参考 Agent Harness，不作为 Runtime

## 11. 架构验收问题

每个 Phase 结束必须回答：

1. 是否出现跨层依赖？
2. Node 是否过厚？
3. 是否有普通逻辑被错误包装成 Agent？
4. 是否有重复模型？
5. 是否有无法测试的全局状态？
6. 是否存在无必要抽象？
7. 是否出现万能 utils/common？
8. 是否超出当前 Phase 的参考项目阅读范围？
