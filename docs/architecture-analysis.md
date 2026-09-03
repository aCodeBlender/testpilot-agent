# TestPilot V1 Architecture Analysis

Phase 0 输出文档 | 日期：2026-09-02  
Phase 0 Review 修订 | 日期：2026-09-02

---

## 1. 参考项目分析

### 1.1 AutoRestTest

#### 1.1.1 OpenAPI 如何被加载和解析？

AutoRestTest 使用 `Prance` 库（基于 `openapi-spec-validator`）加载 OpenAPI spec：

- `SpecificationParser` 类封装了 `ResolvingParser`，自动处理 `$ref` 解析
- 支持 YAML/JSON 格式，通过 `spec_path` 参数指定文件路径
- 提供 `LenientResolvingParser` 子类，在验证失败时 warning 而非 crash
- 递归引用通过 `recursion_limit` + `recursion_limit_handler` 控制，用占位 schema 替代循环引用

**关键流程**：`spec_path` → `ResolvingParser(spec_path)` → `self.resolving_parser.specification`（dict）→ 遍历 `paths` → 为每个 operation 构建 `OperationProperties`

**TestPilot 采纳**：使用成熟库（Prance）负责加载、校验、`$ref` resolution，TestPilot 自己只做 Domain Mapper。

#### 1.1.2 Endpoint / Parameter 如何建模？

AutoRestTest 使用 `dataclass` 定义了清晰的 Domain Model：

| 模型 | 职责 |
|------|------|
| `OperationProperties` | 单个 API operation：operation_id, endpoint_path, http_method, summary, parameters, request_body, responses |
| `ParameterProperties` | 参数属性：name, in_value, description, required, schema, example |
| `SchemaProperties` | Schema 细节：type, format, enum, min/max, nullable, items, properties（递归） |
| `ResponseProperties` | 响应定义：status_code, description, content (mime_type → SchemaProperties) |
| `ParameterKey` | `tuple[str, str | None]`，即 `(name, in)`，用于唯一标识参数 |

**设计亮点**：
- `ParameterKey` 用元组 `(name, in)` 做唯一键，避免同名不同位置参数冲突
- `SchemaProperties` 递归嵌套（items, properties），完整表达 JSON Schema
- 参数合并逻辑 `_merge_parameters()`：path-level 参数与 operation-level 参数合并，operation 覆盖 path

#### 1.1.3 API Dependency 如何表达？

AutoRestTest 使用图结构表达接口依赖：

- `OperationNode`：包装 `OperationProperties`，持有 `outgoing_edges` 和 `tentative_edges`
- `OperationEdge`：source → destination，携带 `similar_parameters`（参数相似度映射）
- `OperationGraph`：管理所有 node/edge，通过 `OperationDependencyComparator`（embedding 余弦相似度）自动推断依赖
- 依赖判断基于参数名/响应字段的语义相似度（embedding），非确定性

**注意**：此依赖推断方式依赖 LLM embedding，V1 不采用。V1 仅做确定性测试，不跨接口传递参数。

#### 1.1.4 测试执行结果如何组织？

- `RequestData`：封装单次请求的所有信息（endpoint, parameters, body, operation_properties）
- `RequestResponse`：配对 `RequestData` + `requests.Response` + `response_text`
- `StatusCode`：按状态码聚合（status_code, count, requests_and_responses）
- `RequestGenerator` 维护 `status_codes: Dict[int, StatusCode]` 和 `responses: Dict[str, RequestResponse]`
- 最终输出到 `data/` 目录：`report.json`, `operation_status_codes.json`, `server_errors.json` 等

#### 1.1.5 哪些设计适合 TestPilot V1，哪些明显过重？

**适合 V1**：
- `ParameterKey = (name, in)` 的参数标识方式
- `SchemaProperties` 的递归 JSON Schema 建模
- 参数合并逻辑（path-level + operation-level）
- 按状态码聚合的执行结果组织方式
- 使用 Prance 做 `$ref` resolution 的思路（TestPilot 直接用 Prance，不自研 resolver）

**明显过重（V1 不采用）**：
- Multi-Agent Reinforcement Learning（Q-learning, MARL）
- Embedding 驱动的依赖推断（`OperationDependencyComparator`）
- 图结构的接口依赖（`OperationGraph`）
- TUI dashboard（Rich 实时面板）
- 缓存系统（Q-table cache, graph cache）
- 参数组合采样策略（stratified sampling）

---

### 1.2 TestCraft API Automation Agent

#### 1.2.1 API Spec 如何转成统一 Domain Model？

TestCraft 的转换分三层：

1. **加载**：`APIDefinitionLoader` 从 URL 或文件加载原始 spec
2. **拆分**：`APIDefinitionSplitter` 将 spec 拆成多个 `APIPath` / `APIVerb`，每个携带 `full_path`, `content`（YAML 片段）
3. **合并**：`APIDefinitionMerger` 合并拆分结果

最终统一到 `APIDefinition` 容器：
```python
@dataclass
class APIDefinition:
    definitions: List[APIDef]  # APIPath | APIVerb
    endpoints: Optional[List[str]]  # 过滤条件
    variables: List[Dict[str, str]]
    base_yaml: Optional[str]  # 基础 spec（不含 paths）
```

**Domain Model 层次**：
- `APIBase`：基类，持有 content, root_path, full_path, type
- `APIPath(APIBase)`：路径级定义
- `APIVerb(APIBase)`：HTTP 方法级定义，额外有 verb, prerequest, name
- `APIModel`：模型引用（path, files）
- `GeneratedModel`：LLM 生成的模型文件（path, fileContent, summary）

#### 1.2.2 Processor / Service 如何划分职责？

**Processor 层**（数据处理）：
- `APIProcessor`（ABC）：定义 spec 处理的抽象接口
- `SwaggerProcessor(APIProcessor)`：OpenAPI/Swagger 具体实现
- `PostmanProcessor(APIProcessor)`：Postman collection 具体实现

Processor 负责：加载 spec → 拆分 → 合并 → 过滤 → 返回 `APIDefinition`

**Service 层**（能力提供）：
- `LLMService`：封装所有 LLM 调用（generate_models, generate_first_test, generate_additional_tests, fix_typescript）
- `FileService`：文件操作（copy template, create files）
- `CommandService`：命令执行（TypeScript compiler, linter, formatter）
- `FrameworkStateManager`：框架状态管理

**划分原则**：Processor 是数据变换，Service 是能力提供。

**TestPilot 采纳分层思路，但 V1 不引入 DI 容器**。通过普通构造函数注入依赖即可。

#### 1.2.3 Prompt 如何管理？

- Prompt 存放在 `prompts/` 目录下的 `.txt` 文件中
- `PromptConfig` 类集中定义所有 prompt 文件路径
- `LLMService._load_prompt(prompt_path)` 从文件读取 prompt 内容
- Prompt 模板使用 `ChatPromptTemplate.from_template()` 构建

**关键点**：Prompt 与代码分离，通过文件路径引用，便于独立维护。TestPilot 采纳此方式。

#### 1.2.4 LLM 调用如何集中封装？

`LLMService` 是唯一的 LLM 入口：

- `_select_language_model()`：根据配置选择模型（Anthropic/OpenAI/Google/Bedrock）
- `create_ai_chain()`：构建 prompt → LLM → tool_call 的链式调用
- 具体方法：`generate_models()`, `generate_first_test()`, `generate_additional_tests()`, `fix_typescript()`

**TestPilot 采纳集中封装思路**，但 V1 只实现单一 OpenAI-Compatible API，不做多 Provider 适配。

#### 1.2.5 Orchestrator 如何保持薄？

`FrameworkGenerator` 是 Orchestrator，它：

1. 不直接处理数据，委托给 `APIProcessor`
2. 不直接调用 LLM，委托给 `LLMService`
3. 不直接操作文件，委托给 `FileService`
4. 只负责流程编排：process_api_definition → setup_framework → generate_models → generate_tests → run_final_checks

**薄的定义**：Orchestrator 只做"调用谁"和"顺序是什么"，不做"怎么做"。TestPilot 直接采用。

#### 1.2.6 哪些工程约束适合 TestPilot？

**适合 TestPilot**：
- Domain Model 与 OpenAPI 原始结构解耦
- Processor / Service 分层架构（通过构造函数注入，不用 DI 容器）
- Prompt 文件化管理
- LLM 调用集中封装（V1 仅 OpenAI-Compatible）
- Orchestrator 薄编排
- 结构化输出（Pydantic Structured Output）

**不适合 TestPilot V1**：
- DI 容器（dependency_injector）—— V1 规模小，直接构造函数注入
- TypeScript 框架生成
- Postman collection 支持
- Checkpoint 断点续传
- 代码质量检查链
- 多 LLM Provider 适配

---

## 2. TestPilot V1 架构设计

### 2.1 总体架构

```text
CLI (Typer)
  ↓
OpenAPI Loader (Prance: 加载 + $ref resolution)
  ↓
Domain Mapper (薄映射: resolved dict → Pydantic Domain Model)
  ↓
Endpoint Selector (确定性过滤)
  ↓
Scenario Generator
  ├─ Deterministic Scenario Generator (Phase 2)
  └─ LLM Semantic Planner (Phase 3)
  ↓
Test Case Generator (确定性 + Schema 驱动)
  ↓
HTTP Executor (httpx)
  ↓
Deterministic Validator (规则引擎)
  ↓
LLM Failure Analyzer (Phase 4)
  ↓
Report Generator (JSON: Phase 2, HTML: Phase 5)
```

### 2.2 模块职责

| 模块 | 职责 | 是否调用 LLM | 输入 | 输出 |
|------|------|:------------:|------|------|
| `openapi/loader` | 加载 URL/JSON/YAML，Prance 处理 $ref | ✗ | spec URL/path | resolved dict |
| `openapi/mapper` | resolved dict → Pydantic Domain Model | ✗ | resolved dict | ApiSpec |
| `openapi/selector` | 按 tag/path 过滤 endpoint | ✗ | ApiSpec, filters | list[ApiEndpoint] |
| `planner/det_scenario` | 确定性场景生成（Schema 驱动） | ✗ | ApiEndpoint | list[TestScenario] |
| `planner/llm_planner` | LLM 语义场景补充 | ✓ | ApiEndpoint | list[TestScenario] |
| `generator/` | 场景 → 可执行 TestCase | ✗ | TestScenario | list[TestCase] |
| `executor/` | 发送 HTTP，记录响应 | ✗ | TestCase | list[ExecutionResult] |
| `validator/` | 规则判断 pass/fail/warn | ✗ | ExecutionResult | list[ValidationResult] |
| `analyzer/` | LLM 分析失败原因 | ✓ | ValidationResult(failed) | list[FailureAnalysis] |
| `report/` | 生成 JSON/HTML 报告 | ✗ | State 中全部结果 | report.json, report.html |
| `graph/` | LangGraph 编排上述模块 | ✗ | config | report_path |
| `llm/client` | 统一 LLM 调用边界 | - | prompt + schema | structured output |

**关键变化**：
- `openapi/parser` 拆为 `openapi/loader`（Prance 负责）+ `openapi/mapper`（TestPilot 薄映射）
- `planner/` 拆为 `planner/det_scenario`（确定性）+ `planner/llm_planner`（LLM），共享同一 `TestScenario` 输出
- `llm/client` 作为独立边界，业务代码不直接依赖具体 LLM Provider

### 2.3 Domain Model 设计

#### 2.3.1 核心原则

- **ID 引用代替嵌套对象**：下游模型通过 `*_id` 字段引用上游模型，不嵌套完整对象
- **State 集中保存**：所有完整对象在 LangGraph State 中以扁平列表保存
- **Spec 与 Config 解耦**：`ApiSpec` 描述"API 是什么"，`AppConfig` 描述"这次测试哪个环境"
- **TestCase 不存完整 URL**：只存 `method` + `path`，最终 URL 由 RequestBuilder 用 `target_base_url + path` 构造

#### 2.3.2 模型定义

```python
# ============ Spec 层 ============

class ApiSpec(BaseModel):
    """OpenAPI spec 的顶层表示（不含运行环境信息）"""
    title: str
    version: str
    servers: list[str]           # OpenAPI servers 原始信息，不做运行时选择
    endpoints: list[ApiEndpoint]

class ApiEndpoint(BaseModel):
    """单个 API endpoint"""
    id: str                      # 稳定唯一 ID，格式: "{method}_{path}" 或 operation_id
    path: str
    method: str                  # GET, POST, PUT, DELETE, PATCH
    operation_id: str | None
    summary: str | None
    description: str | None
    tags: list[str]
    parameters: list[ApiParameter]
    request_body: ApiRequestBody | None
    responses: dict[str, ApiResponse]

class ApiParameter(BaseModel):
    """请求参数"""
    name: str
    location: str                # path, query, header, cookie
    required: bool
    schema: ApiSchema

class ApiRequestBody(BaseModel):
    """请求体"""
    required: bool
    content_type: str
    schema: ApiSchema

class ApiSchema(BaseModel):
    """JSON Schema 的简化表示（递归）"""
    type: str | None
    format: str | None
    properties: dict[str, ApiSchema] | None
    items: ApiSchema | None
    required: list[str]
    enum: list[Any]
    minimum: float | None
    maximum: float | None
    min_length: int | None
    max_length: int | None
    nullable: bool
    example: Any | None

class ApiResponse(BaseModel):
    """响应定义"""
    status_code: str
    description: str | None
    content_schema: ApiSchema | None

# ============ Scenario 层 ============

class TestScenario(BaseModel):
    """测试场景（确定性或 LLM 生成）"""
    id: str                      # 稳定唯一 ID
    endpoint_id: str             # 引用 ApiEndpoint.id
    name: str
    description: str
    category: str                # happy_path, required_missing, null, wrong_type,
                                 # empty_string, string_boundary, number_boundary,
                                 # invalid_enum, invalid_path_id, missing_auth, semantic
    source: str                  # "deterministic" | "llm"
    rationale: str

# ============ TestCase 层 ============

class TestCase(BaseModel):
    """可执行的测试用例"""
    id: str                      # 稳定唯一 ID
    endpoint_id: str             # 引用 ApiEndpoint.id
    scenario_id: str             # 引用 TestScenario.id
    method: str                  # HTTP method
    path: str                    # URL path（不含 base_url）
    headers: dict[str, str]
    query_params: dict[str, str]
    path_params: dict[str, str]
    body: Any | None
    expected_status: int | None
    expected_schema: ApiSchema | None
    tags: list[str]

# ============ Execution 层 ============

class ExecutionResult(BaseModel):
    """执行结果"""
    id: str                      # 稳定唯一 ID
    case_id: str                 # 引用 TestCase.id
    status_code: int
    response_headers: dict[str, str]
    response_body: Any | None
    response_time_ms: float
    error: str | None

# ============ Validation 层 ============

class ValidationResult(BaseModel):
    """验证结果"""
    id: str                      # 稳定唯一 ID
    case_id: str                 # 引用 TestCase.id
    passed: bool
    severity: str                # pass, fail, warn, error
    checks: list[CheckResult]

class CheckResult(BaseModel):
    """单项检查结果"""
    name: str
    passed: bool
    expected: str
    actual: str
    message: str

# ============ Analysis 层 ============

class FailureAnalysis(BaseModel):
    """LLM 生成的失败分析"""
    id: str                      # 稳定唯一 ID
    case_id: str                 # 引用 TestCase.id
    possible_causes: list[str]
    severity: str                # low, medium, high, critical
    suggestions: list[str]
    ai_generated: bool

# ============ Config 层 ============

class AppConfig(BaseModel):
    """运行时配置（与 ApiSpec 解耦）"""
    openapi_source: str          # URL 或文件路径
    target_base_url: str         # 实际测试目标地址
    bearer_token: str | None
    custom_headers: dict[str, str]
    include_tags: list[str]
    exclude_tags: list[str]
    max_cases_per_endpoint: int
    llm_api_key: str | None
    llm_base_url: str | None     # OpenAI-Compatible API base URL
    llm_model: str | None
    timeout_seconds: int
```

#### 2.3.3 引用关系图

```text
ApiSpec
  └── ApiEndpoint (id)
        ├── TestScenario (endpoint_id)     ← 确定性 + LLM 两种来源
        │     └── TestCase (endpoint_id, scenario_id)
        │           ├── ExecutionResult (case_id)
        │           │     └── ValidationResult (case_id)
        │           │           └── FailureAnalysis (case_id)
        │           └── FailureAnalysis (case_id)  ← 也直接关联 case
        └── TestCase (endpoint_id)         ← 也可直接从 endpoint 生成
```

### 2.4 LangGraph State

```python
class TestAgentState(TypedDict):
    config: AppConfig
    api_spec: ApiSpec | None
    endpoints: list[ApiEndpoint]           # 所有解析出的 endpoint
    selected_endpoints: list[ApiEndpoint]  # 经过过滤的 endpoint
    scenarios: list[TestScenario]          # 确定性 + LLM 合并去重后的场景
    test_cases: list[TestCase]
    execution_results: list[ExecutionResult]
    validation_results: list[ValidationResult]
    failure_analyses: list[FailureAnalysis]
    report_path: str | None
    errors: list[str]
```

所有集合以扁平列表保存，通过 ID 互相引用。为后续持久化、Regression Memory 和跨运行历史记录留出空间，但 V1 不实现长期 Memory。

### 2.5 Scenario 来源设计

TestScenario 有两个独立来源，合并去重后统一进入 TestCase Generator：

```text
ApiEndpoint
  ├─→ Deterministic Scenario Generator (Phase 2, 确定性)
  │     输出 10 类基础场景：
  │       happy_path, required_missing, null, wrong_type,
  │       empty_string, string_boundary, number_boundary,
  │       invalid_enum, invalid_path_id, missing_auth
  │
  └─→ LLM Semantic Planner (Phase 3, LLM)
        输出业务语义型场景（补充，不重复基础 Schema Case）

两类 TestScenario 合并、按 (endpoint_id, category, name) 去重
  ↓
TestScenario → TestCase Generator → TestCase
```

**不引入 Factory / Strategy / Registry**。两个 Scenario Generator 是两个普通函数，返回 `list[TestScenario]`，在调用侧简单合并即可。

### 2.6 数据生成优先级

```text
OpenAPI example
→ OpenAPI default
→ Deterministic Schema Generator
→ LLM Semantic Value
```

LLM 不应承担基础值生成。只有当确定性方式无法生成有意义的测试值时，才调用 LLM。

### 2.7 OpenAPI 库选型

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 自研 Parser + $ref Resolver | 零外部依赖 | 重新实现 OpenAPI 标准，复杂度高，容易遗漏 edge case | ❌ 不采用 |
| Prance | 成熟稳定，$ref resolution 完整，支持 recursive ref / external ref，AutoRestTest 已验证 | 依赖 openapi-spec-validator，较重 | ✅ **推荐** |
| openapi-core | 功能完整 | 功能超出需求（包含 request/response 验证），API 复杂 | ❌ 过重 |
| openapi-spec-validator | 轻量 | 只做验证，不做 $ref resolution | ❌ 功能不足 |

**选型决策**：使用 **Prance** 作为 OpenAPI 加载和 `$ref` resolution 的基础设施。

**TestPilot 自己只做**：
- `loader.py`：调用 Prance 加载 spec，处理 lenient/strict 模式
- `mapper.py`：将 Prance 输出的 resolved dict 映射为 Pydantic Domain Model
- `selector.py`：按 tag/path 过滤 endpoint

**TestPilot 不自己做**：
- `$ref` 解析
- JSON Pointer 处理
- external reference 加载
- recursive reference 检测
- OpenAPI spec 校验

---

## 3. Constitution 自检

| 条目 | 是否满足 | 说明 |
|------|:--------:|------|
| 1. Deterministic First, LLM Second | ✓ | 10 类确定性场景优先；LLM 仅补充语义场景和失败分析 |
| 2. LangGraph 只负责 Orchestration | ✓ | Node 薄编排，业务逻辑在 Service 层 |
| 3. Domain Model 与 OpenAPI 原始结构解耦 | ✓ | OpenAPI dict 仅在 Loader/Mapper 边界，后续使用 Pydantic model |
| 4. 单一职责 | ✓ | 明确拆分模块，无万能 utils/common |
| 5. Structured Output | ✓ | LLM 输出全部通过 Pydantic Structured Output |
| 6. V1 功能边界 | ✓ | 不含 Playwright/Selenium/SQL/Redis/RL/多 Agent/多 Provider |
| 7. 分阶段开发 | ✓ | Resume MVP → V1 Complete，严格按 Phase 执行 |
| 8. 参考项目定点阅读 | ✓ | 仅阅读白名单指定目录 |
| 9. 可测试性 | ✓ | 每个模块独立可测 |
| 10. 安全边界 | ✓ | 默认测试环境，不提交敏感信息 |
| 11. 不为 Agent 味增加复杂度 | ✓ | Parser/Executor/Validator 是普通组件；无 DI 容器；无多 Provider 适配 |

---

## 4. 架构验收问题回答

1. **是否出现跨层依赖？** — 否。每层只依赖 Domain Model，不依赖其他层的实现。
2. **Node 是否过厚？** — 否。LangGraph Node 只做调用编排，逻辑在 Service 层。
3. **是否有普通逻辑被错误包装成 Agent？** — 否。Parser/Executor/Validator 是普通组件。
4. **是否有重复模型？** — 否。统一使用 Pydantic Domain Model，ID 引用避免冗余嵌套。
5. **是否有无法测试的全局状态？** — 否。State 通过 LangGraph State 传递。
6. **是否存在无必要抽象？** — 否。每个抽象都有明确职责。不引入 DI 容器、多 Provider 适配层。
7. **是否出现万能 utils/common？** — 否。禁止创建此类文件。
8. **是否超出当前 Phase 的参考项目阅读范围？** — 否。严格遵守白名单。
