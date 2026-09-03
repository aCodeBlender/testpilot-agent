# TestPilot Constitution

本文件定义 TestPilot 项目不可轻易违反的工程原则。若实现方案、参考项目或 AI Coding 建议与本文件冲突，优先遵循本文件。

## 1. Deterministic First, LLM Second

确定性问题优先使用普通代码、规则或成熟库解决。

LLM 只用于：
- 理解接口语义。
- 生成高层测试场景。
- 推测业务边界。
- 分析失败原因。
- 后续辅助识别接口依赖。

LLM 不用于：
- 发送 HTTP。
- JSON Parsing。
- status code 判断。
- JSON Schema Validation。
- 文件读写。
- 直接执行危险 SQL。

## 2. LangGraph 只负责 Orchestration

LangGraph Node 不承载大量业务逻辑。

业务逻辑必须进入明确的 Service / Parser / Executor / Validator。

禁止出现几百行的 Node。

## 3. Domain Model 与 OpenAPI 原始结构解耦

OpenAPI 原始 dict 只能存在于 Loader / Parser 边界。

后续模块统一使用 Pydantic Domain Model。

## 4. 单一职责

至少明确拆分：
- OpenAPI Loader / Parser
- Planner
- Test Case Generator
- HTTP Executor
- Validator
- Failure Analyzer
- Report Generator

禁止出现万能：
- utils.py
- common.py
- agent.py
- 超大 main.py

## 5. Structured Output

LLM 输出必须使用 Pydantic / Structured Output。

禁止依赖自由文本 + 正则作为核心模块协议。

## 6. V1 功能边界

V1 只实现：

OpenAPI
→ Parse
→ Test Planning
→ Test Case
→ HTTP Execution
→ Deterministic Validation
→ LLM Failure Analysis
→ HTML / JSON Report

V1 禁止：
- Playwright
- Selenium
- UI Testing
- SQL / Redis 写操作
- 自动修改被测项目代码
- 强化学习 / Q-learning
- 自研 Agent Runtime
- 多 Agent 群聊
- Kubernetes / CI 平台化

## 7. 分阶段开发

必须按 Phase 开发：

Phase 0：只读分析  
Phase 1：项目骨架 + Domain + OpenAPI Parser  
Phase 2：确定性执行链  
Phase 3：LLM Test Planner  
Phase 4：LLM Failure Analyzer  
Phase 5：HTML Report  

上一阶段测试未通过，不得进入下一阶段。

## 8. 参考项目采用“定点阅读”

参考仓库只作为架构老师，不允许默认全仓库阅读。

第一轮必须遵守 `AGENTS.md` 中的参考项目阅读白名单。

原则：
- 只读与当前 Phase 有关的目录。
- 不因“看起来高级”引入额外架构。
- 不把参考项目的历史包袱复制进 TestPilot。
- 需要查看更多文件时，先说明目的，再扩大阅读范围。

## 9. 可测试性

公共核心模块必须具备单元测试。

每个 Phase 完成后必须：
1. 运行测试。
2. 更新 docs/progress.md。
3. 检查目录职责。
4. 记录新增技术债。

## 10. 安全边界

测试目标默认视为开发 / 测试环境。

数据库能力后续默认只读。

公司内部源码、真实 Token、数据库密码、真实业务数据不得提交到公开仓库。

## 11. 不为“Agent 味”增加复杂度

不是所有组件都需要成为 Agent。

Parser、Executor、Validator 本质上是普通确定性组件。

只有具备独立决策目标、独立上下文和工具集时，才考虑拆成 Subagent。
