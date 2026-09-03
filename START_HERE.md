# START HERE - TestPilot

这是 TestPilot Spec Pack V2。

V2 相比上一版最重要的变化：

> 参考项目采用“阅读白名单”，禁止 Codex / Claude Code 在 Phase 0 默认全仓库扫描。

## 1. 建立工作目录

```text
workspace/
├── testpilot-agent/
└── references/
```

## 2. 下载核心参考项目

进入 `references/`：

```bash
git clone https://github.com/selab-gatech/autoresttest.git
git clone https://github.com/TestCraft-App/api-automation-agent.git
```

第一阶段先不要下载更多项目。

## 3. 可选参考项目

V2 接口依赖再下载：

```bash
git clone https://github.com/microsoft/restler-fuzzer.git
```

如果你想额外研究 Agent Harness，可选：

```bash
git clone https://github.com/DerekYRC/mini-claude-code.git
```

但 Phase 0 不要求阅读 mini-claude-code。

## 4. 把本 Spec Pack 放进 testpilot-agent

最终：

```text
workspace/
├── testpilot-agent/
│   ├── AGENTS.md
│   ├── constitution.md
│   └── specs/
│       └── 001-api-testing-agent/
│           ├── spec.md
│           ├── plan.md
│           └── tasks.md
│
└── references/
    ├── autoresttest/
    └── api-automation-agent/
```

## 5. 打开 workspace 根目录

让 AI 同时能访问：

- `testpilot-agent`
- `references`

但“能访问”不等于“允许全量读取”。

必须遵守 `AGENTS.md` 白名单。

## 6. 第一条提示词

```text
项目名称统一为 TestPilot。

命名约定：
- 项目展示名：TestPilot
- Git 仓库 / 根目录：testpilot-agent
- Python package：testpilot

请先阅读：

testpilot-agent/AGENTS.md
testpilot-agent/constitution.md
testpilot-agent/specs/001-api-testing-agent/spec.md
testpilot-agent/specs/001-api-testing-agent/plan.md
testpilot-agent/specs/001-api-testing-agent/tasks.md

然后只按照 AGENTS.md 中的“参考项目阅读白名单”阅读：

references/autoresttest
references/api-automation-agent

禁止默认全仓库扫描。
禁止为了“完整理解项目”扩大阅读范围。
如果认为白名单不足，先说明具体缺失信息、需要新增读取的具体文件，以及理由；不要直接继续读取。

现在只执行 Phase 0。

禁止写业务代码。

请输出：
1. testpilot-agent/docs/architecture-analysis.md
2. testpilot-agent/docs/implementation-plan.md
3. testpilot-agent/docs/progress.md
4. 你准备创建的完整目录树
5. 参考设计采用表
6. 参考设计明确不采用表
7. 本次实际读取的参考项目文件/目录清单

完成后停止，不进入 Phase 1。
```

## 7. Phase 0 Review 重点

你拿到结果后重点看：

### 参考范围

- 有没有偷偷把整个 AutoRestTest 扫了。
- 有没有读 `marl/` 然后想加强化学习。
- 有没有把 TestCraft 的 benchmark/template 也搬进来。
- 有没有无理由扩大白名单。

### 架构

- 有没有擅自加 Playwright。
- 有没有擅自加 SQL / Redis。
- 有没有一开始就 Multi-Agent。
- 有没有自研 Agent Runtime。
- 有没有把 LangGraph Node 写成业务层。
- 有没有造一堆 Factory / Manager / Registry。

### 命名

必须保持：

```text
TestPilot
testpilot-agent
testpilot
```

## 8. 今天的目标

今天做到：

- 目录建好。
- 参考项目 clone 好。
- Spec Pack V2 放好。
- Phase 0 完成。
- 人工 Review Phase 0。

不要急着写业务代码。
