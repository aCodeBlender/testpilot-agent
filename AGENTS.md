# AGENTS.md

本文件用于指导 Codex / Claude Code 等 AI Coding 工具维护 TestPilot。

## 项目命名约定

- 项目展示名：`TestPilot`
- Git 仓库 / 根目录：`testpilot-agent`
- Python package：`testpilot`

禁止自行引入其他项目级品牌名称。

## 项目目标

构建一个面向 Spring Boot / OpenAPI 3.x 的智能 REST API Testing Agent。

核心流程：

OpenAPI
→ Parse
→ Plan
→ Generate Test Case
→ HTTP Execute
→ Validate
→ Analyze Failure
→ Report

## 开始编码前必须阅读

1. `constitution.md`
2. `specs/001-api-testing-agent/spec.md`
3. `specs/001-api-testing-agent/plan.md`
4. `specs/001-api-testing-agent/tasks.md`

参考仓库必须按下方“阅读白名单”定点阅读，禁止默认全仓库扫描。

---

# 参考项目阅读白名单

## A. AutoRestTest

仓库位置：

`../references/autoresttest`

### Phase 0 必须阅读

- `README.md`
- `src/autoresttest/specification/`
- `src/autoresttest/models/`
- `src/autoresttest/graph/`
- 与上述模块直接相关的主入口 / 调用链文件

### Phase 0 重点回答

只需要回答：

1. OpenAPI 如何被加载和解析？
2. Endpoint / Parameter 如何建模？
3. API dependency 如何表达？
4. 测试执行结果如何组织？
5. 哪些设计适合 TestPilot V1，哪些明显过重？

### Phase 0 禁止主动深入

除非为理解上述调用链确有必要，否则第一轮不要深入：

- `marl/`
- `ablation/`
- 大部分 `tui/`
- 论文实验相关代码
- baseline / benchmark / evaluation
- 训练与 Q-learning 相关实现
- 与 V1 无关的 service

### 明确不采用

- Multi-Agent Reinforcement Learning
- Q-learning
- 训练流程
- 论文实验框架
- 为实验对比而存在的复杂抽象

---

## B. TestCraft API Automation Agent

仓库位置：

`../references/api-automation-agent`

### Phase 0 必须阅读

- `README.md`
- `CLAUDE.md`（若存在）
- `src/models/`
- `src/processors/`
- `src/services/`
- `src/container.py`（若存在）
- `src/framework_generator.py`（若存在）
- 与上述模块直接相关的入口文件

### Phase 0 重点回答

只需要回答：

1. API Spec 如何转成统一 Domain Model？
2. Processor / Service 如何划分职责？
3. Prompt 如何管理？
4. LLM 调用如何集中封装？
5. Orchestrator 如何保持薄？
6. 哪些工程约束适合 TestPilot？

### Phase 0 暂不阅读

- `evaluations/`
- `benchmarks/`
- `api-framework-template/`
- 大部分 `tests/`
- `.cursor/`
- `.windsurf/`
- `.vscode/`
- 与核心架构无关的 scripts

如需看 tests，只允许为理解某个核心模块的行为定点打开相关测试文件。

---

## C. RESTler

仓库位置：

`../references/restler-fuzzer`

V1 Phase 0 不要求存在，也不要求阅读。

只有进入 V2 “Producer-Consumer Dependency” 后，才允许定点阅读：
- OpenAPI compilation
- dependency inference
- producer-consumer relation
- request sequence generation

禁止提前把 RESTler 的复杂状态空间设计引入 V1。

---

## D. mini-claude-code

若本地存在，仅作为 Agent Harness 学习资料。

Phase 0 不要求阅读。

后续仅在明确需要时参考：
- Agent Loop
- Tool Registry
- Subagent
- Skill
- MCP
- Context Management

禁止：
- 复制其 Coding Agent Runtime
- 在 LangGraph 之外再造一套 Agent Loop
- 把 Coding Agent 的 Permission/Todo/Hooks 整套搬入 TestPilot

---

# 参考项目阅读扩展规则

若白名单内容不足：

1. 先说明“为什么必须查看更多文件”。
2. 指定准备增加的具体文件或目录。
3. 只扩大到最小必要范围。
4. 不允许用“为了完整理解项目”作为全仓库阅读理由。

参考代码目标是回答设计问题，不是复刻仓库。

---

## 开发规则

- 不得一次性实现整个项目。
- 严格按 `tasks.md` 顺序工作。
- 每次只完成一个小批次任务。
- 修改前先阅读相关模块。
- 新增抽象前说明必要性。
- 优先复用成熟库。
- 不创建万能工具文件。
- 不做未来功能的过度设计。
- LangGraph Node 必须薄。
- LLM 必须 Structured Output。
- HTTP Executor 不得调用 LLM。
- Validator 优先规则判断。

## 每个阶段完成时必须输出

1. 已完成任务编号。
2. 当前目录树。
3. 测试执行结果。
4. 是否违反 constitution。
5. 新增技术债。
6. 下一阶段建议。

## Phase 0 特殊规则

Phase 0 禁止写业务代码。

只允许：
- 阅读 Spec。
- 按白名单阅读参考项目。
- 创建 `docs/architecture-analysis.md`
- 创建 `docs/implementation-plan.md`
- 创建 `docs/progress.md`
- 给出准备创建的目录树。

完成后停止，等待人工 Review。
