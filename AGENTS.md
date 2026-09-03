# AGENTS.md

本文件用于指导 Claude Code / Codex 等 AI Coding 工具维护 TestPilot。

## 项目命名约定

- 项目展示名：`TestPilot`
- Git 仓库 / 根目录：`testpilot-agent`
- Python package：`testpilot`

禁止自行引入其他项目级品牌名称。

## 项目目标

构建一个 OpenAPI 3.0.x 驱动的 REST API 自动化测试工具。

Phase 2 Resume MVP 已冻结，当前稳定 deterministic pipeline：

```text
OpenAPI Loader
→ Domain Mapper
→ Endpoint Selector
→ Deterministic Scenario Generator
→ TestCase Generator
→ RequestBuilder
→ HTTP Executor
→ Deterministic Validator
→ Report
```

后续 AI/Agent 能力必须建立在该核心之上，而不是替换它。

---

## Source of Truth

权威信息优先级：

1. `constitution.md` — 不可违反的长期工程原则
2. `specs/<feature>/spec.md` — 功能需求和非目标
3. `specs/<feature>/plan.md` — 架构和技术设计
4. `specs/<feature>/tasks.md` — 当前任务拆分
5. `AGENTS.md` — AI Coding 的长期执行纪律
6. `docs/` — 分析、进度和说明，不作为需求 source of truth

如果参考项目与 TestPilot specs 冲突，必须以 TestPilot 为准。

---

## 开始编码前必须阅读

1. `constitution.md`
2. `specs/001-api-testing-agent/spec.md`
3. `specs/001-api-testing-agent/plan.md`
4. `specs/001-api-testing-agent/tasks.md`

参考仓库必须按下方"阅读白名单"定点阅读，禁止默认全仓库扫描。

---

## Phase-Gated Development

必须小批次开发。

- 只实现当前明确指定的 task/batch。
- 不提前实现下一 Phase。
- 不因为"以后可能需要"而增加抽象层。
- 不擅自扩大 scope。
- 完成当前任务、测试和汇报后停止。
- 不允许一次性重写整个架构。

---

## Preserve the Deterministic Core

除非当前任务明确要求，否则禁止大规模重构：

- OpenAPI Loader / Mapper
- Scenario Generator
- TestCase Generator
- RequestBuilder
- HttpExecutor
- Validator
- Report

---

## Deterministic First, LLM Second

> 能通过明确规则可靠完成的事情，不交给 LLM。

Deterministic 层负责：

- OpenAPI/schema parsing
- 基础测试数据生成
- request construction
- HTTP execution
- schema validation
- status validation
- PASS/FAIL 判断
- report serialization
- security/redaction rules

LLM 可以负责：

- natural-language intent understanding
- endpoint semantic selection
- semantic test planning
- future failure explanation
- future dependency semantic inference

LLM 不得直接成为事实裁判。

---

## LLM Boundary

LLM 不允许：

- 自己直接发送 HTTP 请求
- 自己判断最终 PASS/FAIL
- 绕过 Validator
- 随意创建不存在的 endpoint/schema field
- 修改 deterministic execution result
- 输出未经验证的数据直接进入执行层

所有 LLM 输出必须经过：

```text
LLM output → structured schema → deterministic validation → domain model → execution
```

永远不要信任自由文本输出直接驱动执行。

---

## Agent Architecture

禁止为了"Agent 感"增加不必要复杂度。

- 不自研 Claude Code 风格 Agent Runtime。
- 不自研复杂 Tool Runtime。
- 不实现不必要的 permission framework。
- 不创建多 Agent hierarchy，除非 spec 明确要求。
- LangGraph 只用于 orchestration/state management。
- 普通业务组件保持普通 Python service/function。
- 不把每个模块包装成 Agent/Node/Tool。
- LangGraph Node 必须薄。
- LLM 必须 Structured Output。
- HTTP Executor 不得调用 LLM。
- Validator 优先规则判断。

---

## LLM Provider Design

保持轻量。优先支持 OpenAI-compatible API。

禁止提前实现：

- Provider registry
- 多层 factory hierarchy
- plugin framework
- elaborate provider abstraction

除非后续明确出现真实需求。

---

## Security

任何情况下都不得：

- commit API key
- commit Bearer token
- 把 secret 写入 report
- 把 secret 打印到 console/log
- 把 secret 放入 exception
- 把被测系统的 Bearer Token/custom auth headers 发送给 LLM

两类凭证必须严格区分：

```text
TESTPILOT_LLM_*        → TestPilot 调用模型
TESTPILOT_BEARER_TOKEN  → TestPilot 调用被测 API
```

未来数据库凭证也不得进入 LLM prompt/report/git。

---

## Database Safety

数据库功能尚未实现，但长期安全规则提前固定：

- TestPilot 数据库访问默认只读。
- 优先使用 readonly database account。
- Agent 不得获得 unrestricted SQL write capability。
- 禁止模型自由执行 INSERT / UPDATE / DELETE / DROP。
- 数据库写能力若未来确实需要，必须另行 spec 和显式授权。

---

## 参考项目阅读白名单

参考项目只用于局部学习，禁止整体复制架构或引入无关 runtime。

### A. AutoRestTest

仓库位置：`../references/autoresttest`

Phase 0 必须阅读：

- `README.md`
- `src/autoresttest/specification/`
- `src/autoresttest/models/`
- `src/autoresttest/graph/`

重点回答：OpenAPI 如何加载解析？Endpoint/Parameter 如何建模？API dependency 如何表达？哪些设计适合 TestPilot V1？

禁止深入：`marl/`、`ablation/`、`tui/`、论文实验代码、Q-learning 相关实现。

明确不采用：Multi-Agent Reinforcement Learning、Q-learning、训练流程。

### B. TestCraft API Automation Agent

仓库位置：`../references/api-automation-agent`

Phase 0 必须阅读：

- `README.md`、`CLAUDE.md`（若存在）
- `src/models/`、`src/processors/`、`src/services/`
- `src/container.py`、`src/framework_generator.py`（若存在）

重点回答：API Spec 如何转 Domain Model？Processor/Service 如何划分？Prompt 如何管理？LLM 调用如何封装？

暂不阅读：`evaluations/`、`benchmarks/`、`api-framework-template/`。

### C. RESTler

仓库位置：`../references/restler-fuzzer`

V1 Phase 0 不要求阅读。只有进入 V2 "Producer-Consumer Dependency" 后，才允许定点阅读 OpenAPI compilation、dependency inference、producer-consumer relation、request sequence generation。

禁止提前把 RESTler 的复杂状态空间设计引入 V1。

### D. mini-claude-code

仅作为 Agent Harness 学习资料。Phase 0 不要求阅读。

后续仅在明确需要时参考：Agent Loop、Tool Registry、Subagent、Skill、MCP、Context Management。

禁止：复制其 Coding Agent Runtime、在 LangGraph 之外再造 Agent Loop、把 Coding Agent 的 Permission/Todo/Hooks 整套搬入 TestPilot。

### 白名单扩展规则

若白名单内容不足：

1. 先说明"为什么必须查看更多文件"。
2. 指定准备增加的具体文件或目录。
3. 只扩大到最小必要范围。
4. 不允许用"为了完整理解项目"作为全仓库阅读理由。

---

## Testing Discipline

每个功能修改必须有对应 regression test。

- 新 bug fix 必须增加能复现该 bug 的测试。
- LLM 单元测试必须 mock，不调用真实 API、不消耗 token。
- deterministic 测试必须保持 deterministic。
- 不通过删除/弱化测试来"修复"失败。
- 不通过 report filter 隐藏 false positive。
- 集成测试创建的外部进程必须可靠清理。
- warnings 应保持为 0。

---

## Backward Compatibility

新增 Agent/LLM 能力时：

- 原有 deterministic CLI 必须继续可用。
- 不使用 LLM 功能时，不应要求 LLM API Key。
- 不使用新功能时，不应初始化不必要组件。
- 新能力优先作为 optional layer 接到已有 pipeline。

---

## Documentation

- `README.md` 为英文主 README。
- `README.zh-CN.md` 为简体中文 README。
- 用户可见功能、CLI、配置和 Roadmap 发生变化时，两份 README 必须同步。
- 不得把 planned feature 写成 implemented feature。
- 当前实现和未来 Roadmap 必须明确区分。

---

## Code Quality

- 优先简单 constructor/function wiring。
- 不引入 DI container。
- 不为单一实现设计多层 interface hierarchy。
- 错误必须使用清晰的 domain exception。
- 不吞掉未知 programming error。
- domain model 应保持明确、可验证、尽量 immutable/deterministic。
- 不做与当前任务无关的 cleanup/refactor。
- 新增抽象前说明必要性。
- 优先复用成熟库。

---

## 任务完成规则

每次收到开发任务后：

1. 阅读当前相关 spec/plan/tasks。
2. 只实现当前 batch。
3. 添加/更新测试。
4. 运行相关 unit/integration tests。
5. 检查 warnings、安全和 backward compatibility。
6. 更新必要文档。
7. 汇报修改内容、测试结果和 unresolved issues。
8. 停止。

禁止自动进入下一阶段。

每个阶段完成时必须输出：

1. 已完成任务编号。
2. 测试执行结果。
3. 是否违反 constitution。
4. 新增技术债。
5. 下一阶段建议。

---

## Phase 0 特殊规则

Phase 0 禁止写业务代码。只允许：

- 阅读 Spec。
- 按白名单阅读参考项目。
- 创建 `docs/` 下的分析文档。
- 给出准备创建的目录树。

完成后停止，等待人工 Review。
