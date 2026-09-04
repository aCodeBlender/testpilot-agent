# TestPilot Phase 3D — API Dependency & Runtime State

## 1. 背景

TestPilot 当前已经能够：

- 根据 OpenAPI 生成确定性 API 测试；
- 根据自然语言选择需要测试的 Endpoint；
- 由 LLM 提出 SemanticScenarioProposal；
- 通过 deterministic eligibility 判断语义测试是否允许执行；
- 执行安全的 stateless semantic mutation；
- 通过 CLI / Web UI 完成真实 LLM-driven E2E 测试。

当前限制是：

不同 API 仍基本独立执行。

例如：

POST /users
→ response.id = 15

GET /users/{id}
→ 当前仍可能使用 schema 自动生成的 id=1

前一个 API 的真实响应尚不能可靠地成为后一个 API 的输入。

Phase 3D 的目标是建立：

OpenAPI
→ Dependency Analysis
→ Execution Dependency
→ Runtime State
→ Cross-API Value Propagation

---

## 2. 核心架构决策

### 2.1 Dependency 与 Runtime State 必须分离

静态关系：

ApiDependency
= “哪个 API 的哪个响应值，可以提供给哪个 API 的哪个输入参数”

运行时数据：

RuntimeValue
= “这一次测试运行中，Producer 实际产生了什么值”

RuntimeState
= “当前一次 TestPilot run 中保存的 RuntimeValue 集合”

因此：

ApiDependency != RuntimeValue != RuntimeState

禁止只实现：

runtime_state["id"] = 15

因为不同资源可能同时存在：

user.id
order.id
product.id

不能依赖全局字段名进行绑定。

---

## 3. Dependency-First

TestPilot 必须优先确定 dependency，再在执行过程中捕获对应 runtime value。

标准流程：

OpenAPI
↓
Dependency Analyzer
↓
ApiDependency[]
↓
Execution Planning
↓
执行 Producer
↓
根据已知 dependency 提取 response value
↓
写入 RuntimeState
↓
构造 Consumer Request
↓
读取对应 RuntimeValue

禁止：

执行完 HTTP
↓
看到 response 中有 id
↓
临时寻找其他也叫 id 的参数
↓
猜测是否绑定

Dependency inference 与 Runtime State resolution 必须是两个阶段。

---

## 4. Dependency Source

第一阶段仅考虑明确、安全的响应来源。

例如：

POST /users

response:
{
  "id": 15
}

可表示为：

DependencySource:

- endpoint_id: createUser
- location: response_body
- path: id
- schema_type: integer

第一版仅处理 JSON scalar：

- string
- integer
- number
- boolean

不得把以下敏感信息作为普通 Runtime State：

- Authorization
- Bearer Token
- Cookie credential
- password
- api_key
- secret
- token

认证状态以后单独设计。

---

## 5. Dependency Target

Consumer 可以是：

- path
- query
- header
- cookie
- body

但每种 location 是否真正接入执行层，应按 Batch 分步实现。

例如：

GET /users/{id}

DependencyTarget:

- endpoint_id: getUserById
- location: path
- path: id
- schema_type: integer

---

## 6. ApiDependency

建议使用 typed model 表达，例如：

ApiDependency:

- source
- target
- confidence
- reason

其中：

confidence:

- explicit
- inferred

第一阶段不增加 LLM confidence。

reason 必须描述 deterministic inference 的依据。

不得使用：

metadata: dict[str, Any]

作为 dependency 信息垃圾桶。

---

## 7. Dependency Resolution 优先级

长期优先级：

1. OpenAPI 显式 dependency / links
2. TestPilot deterministic inference
3. 用户显式 dependency annotation/config
4. 未来 LLM semantic dependency inference

LLM inference 即使以后加入，也不能直接执行。

必须继续遵守：

LLM proposal
↓
structured model
↓
deterministic validation
↓
execution

---

## 8. 第一版 deterministic inference

第一版必须非常保守。

例如：

POST /users
→ response.id: integer

GET /users/{id}
→ path.id: integer

只有同时满足足够明确的条件才建立 dependency，例如：

- consumer parameter 真实存在；
- producer response property 可确定；
- 字段名称匹配；
- schema type 兼容；
- resource family 明确相关；
- producer 类型合理；
- 没有多个同等候选 Producer；
- 不涉及 secret；
- 不存在歧义。

如果无法确定：

cannot determine
→ 不建立 dependency

不得为了提高覆盖率而猜。

---

## 9. Resource Family

第一版使用 deterministic path structure 判断资源关系。

例如：

/users
/users/{id}

属于同一 resource family：

/users

/orders
/orders/{orderId}
/orders/{orderId}/cancel

属于同一 order resource family。

但是：

POST /users → response.id
GET /orders/{id}

即使字段名与类型一致，也不能仅凭 id 自动绑定。

---

## 10. Runtime State

Runtime State 是一次 run 内的工作记忆。

生命周期：

run start
↓
RuntimeState empty
↓
Producer execution
↓
capture RuntimeValue
↓
Consumer execution
↓
run end
↓
RuntimeState discarded

当前 Runtime State：

- 不持久化；
- 不跨 run；
- 不存数据库；
- 不属于长期 Memory；
- 不属于聊天记忆；
- 不承担用户偏好存储。

Persistent Memory 是未来独立能力。

---

## 11. 安全原则

Runtime State 与 Dependency 不得破坏现有安全边界。

必须继续遵守：

- Secret 不进入 LLM prompt；
- Secret 不进入普通 Runtime State；
- Secret 不进入 report/log；
- cannot determine 不执行；
- excluded HTTP methods 不得因为 dependency 被重新启用；
- dependency 不得绕过 Semantic Execution Eligibility；
- LLM 不负责 PASS/FAIL。

---

## 12. 与未来 Agent Harness 的关系

Phase 3D 不实现通用 Tool Runtime。

当前仍由 Runner 编排：

Runner
├── Dependency Analyzer
├── Runtime State
├── RequestBuilder
├── HttpExecutor
└── Validator

未来进入真正 Agent Harness 后：

Agent
↓
Tool / Policy Layer
↓
Runner capabilities

Runtime State 可以成为 Agent State 的一部分，但 Phase 3D 不应提前为 LangGraph、Claude Code Harness 或 MCP 做抽象。

---

## 13. 当前明确不做

Phase 3D 第一阶段不实现：

- Persistent Memory
- LLM Tool Calling
- Generic Tool Registry
- Permission Framework
- LangGraph
- MCP
- Database / Redis
- Stateful Semantic Scenario Execution
- duplicate_resource execution
- invalid_state execution
- complex request-sequence search
- dependency graph visualization

---

## 14. Phase 3D 初步拆分

Batch 1：

Dependency Model

+ Conservative Static Inference
+ RuntimeState Foundation

Batch 2：

Runner Wiring

+ Producer Response Capture
+ Consumer Value Injection

目标 E2E：

POST /users
→ response.id = 15
→ RuntimeState
→ GET /users/{id}
→ GET /users/15

之后再决定：

- OpenAPI links
- user dependency annotations
- multi-hop dependency
- stateful semantic testing
- LLM dependency inference

---

## 15. Source of Truth

TestPilot 自身的 specs / architecture decisions 是唯一 source of truth。

RESTler、Claude Code、mini-claude-code 等项目只用于借鉴设计思想。

参考项目不得反向决定 TestPilot 的架构。
