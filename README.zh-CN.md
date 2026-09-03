[English](README.md) | [简体中文](README.zh-CN.md)

# TestPilot

基于 OpenAPI 规范的确定性 REST API 自动化测试工具。

## 项目简介

TestPilot 是一个 **OpenAPI 3.0.x 驱动的 REST API 自动化测试工具**，以确定性方式（Deterministic）对 API 进行端到端验证。无需 LLM 或随机数据——相同的输入永远产生相同的测试结果。

核心思路：解析 OpenAPI 规范 → 生成确定性测试场景 → [可选] LLM 语义规划 → 构造 HTTP 请求 → 真实执行 → 响应验证 → JSON 报告。

## 当前能力

- **OpenAPI 解析** — 支持 OpenAPI 3.0.x，通过 Prance 自动解析 `$ref` 引用
- **端点发现** — 按路径、方法、标签自动识别所有 API 端点
- **确定性场景生成** — 自动生成以下测试场景：
  - `happy_path` — 使用 schema 中的 example/default/类型默认值
  - `required_missing` — 逐一移除必填字段（含 readOnly 保护）
  - `null` — 将字段设为 null（含 readOnly 保护）
  - `wrong_type` — 将字段替换为错误类型的值
- **请求构造** — 自动处理 query/header/path/cookie 参数、请求体、Content-Type
- **认证** — 通过 `TESTPILOT_BEARER_TOKEN` 环境变量注入 Bearer Token（永不打印、永不写入报告）
- **真实 HTTP 执行** — 使用 httpx 同步发送请求，记录状态码、响应时间、响应头、响应体
- **响应验证** — 状态码检查（含场景分类规则）+ JSON Schema 校验（含 writeOnly 响应语义）
- **JSON 报告** — 结构化报告，含敏感值脱敏（headers、cookies、body、query params）
- **CLI 入口** — `python -m testpilot run` 完整执行流水线
- **退出码** — 0=全部通过 / 1=存在测试失败 / 2=应用/工具错误
- **标签过滤** — `--include-tags` / `--exclude-tags` 按需选择端点

## 架构 / 执行流程

```
OpenAPI Spec (URL/文件)
        │
        ▼
┌─────────────────┐
│  Loader (Prance) │  ← 解析 & $ref 解引用
└────────┬────────┘
         ▼
┌─────────────────┐
│  Mapper          │  ← 映射为 ApiSpec / ApiEndpoint / ApiSchema
└────────┬────────┘
         ▼
┌─────────────────┐
│  Selector        │  ← 按标签过滤端点
└────────┬────────┘
         ▼
┌─────────────────┐
│  Scenario Gen    │  ← 确定性生成 happy_path / required_missing / null / wrong_type
└────────┬────────┘
         ▼
┌─────────────────┐
│  TestCase Gen    │  ← 构造具体 HTTP 请求参数
└────────┬────────┘
         ▼
┌─────────────────┐
│  RequestBuilder  │  ← 组装 method/url/headers/params/body
└────────┬────────┘
         ▼
┌─────────────────┐
│  HttpExecutor    │  ← httpx 真实发送，记录执行结果
└────────┬────────┘
         ▼
┌─────────────────┐
│  Validator       │  ← 状态码检查 + JSON Schema 校验（含 writeOnly 语义）
└────────┬────────┘
         ▼
┌─────────────────┐
│  JSON Report     │  ← 结构化报告 + 敏感值脱敏
└─────────────────┘
```

## Quick Start

### 环境要求

- Python 3.11+
- 目标 API 的 OpenAPI 3.0.x 规范（URL 或文件）

### 安装

```bash
# 克隆项目
git clone <repository-url>
cd testpilot-agent

# 安装依赖
pip install -e .
```

### 基本用法

```bash
# 最简用法
python -m testpilot run --openapi http://localhost:8080/v3/api-docs --base-url http://localhost:8080

# 指定输出路径
python -m testpilot run --openapi ./openapi.yaml --base-url https://api.example.com --output report.json

# 带 Bearer Token 认证
export TESTPILOT_BEARER_TOKEN=your-token-here
python -m testpilot run --openapi ./openapi.yaml --base-url https://api.example.com

# 按标签过滤端点
python -m testpilot run --openapi ./openapi.yaml --base-url https://api.example.com --include-tags users,orders

# 排除特定标签
python -m testpilot run --openapi ./openapi.yaml --base-url https://api.example.com --exclude-tags admin

# 超时设置（秒）
python -m testpilot run --openapi ./openapi.yaml --base-url https://api.example.com --timeout 30
```

## CLI 参数

| 参数 | 说明 | 必填 |
|------|------|------|
| `--openapi` | OpenAPI 规范的 URL 或本地文件路径 | ✅ |
| `--base-url` | 目标 API 的基础 URL | ✅ |
| `--output` | 报告输出路径（默认 `report.json`） | ❌ |
| `--goal` | 自然语言测试目标（启用 LLM 语义规划） | ❌ |
| `--include-tags` | 仅测试指定标签的端点（逗号分隔） | ❌ |
| `--exclude-tags` | 排除指定标签的端点（逗号分隔） | ❌ |
| `--max-cases` | 每个端点最大测试用例数 | ❌ |
| `--timeout` | HTTP 请求超时时间（秒） | ❌ |

## 支持的测试场景

| 场景 | 说明 | 期望结果 |
|------|------|----------|
| `happy_path` | 使用有效默认值发送请求 | 2xx |
| `required_missing` | 逐一移除必填字段 | 4xx（含 readOnly 保护） |
| `null` | 将字段设为 null | 4xx（含 readOnly 保护） |
| `wrong_type` | 将字段替换为错误类型 | 4xx |

**readOnly 语义**：`readOnly` 标记的字段（如 `id`）不生成 `required_missing` / `null` / `wrong_type` 场景，因为它们是服务端生成的字段。

**writeOnly 语义**：`writeOnly` 标记的必填字段在响应验证中不要求存在——这是 OpenAPI 规范的正确行为。

## Demo: Spring Boot 示例项目

项目附带一个 Spring Boot 示例应用，用于演示和集成测试：

```bash
cd demo/springboot-demo

# 构建
./mvnw package -DskipTests

# 启动
java -jar target/testpilot-demo-0.0.1-SNAPSHOT.jar

# 运行 TestPilot
python -m testpilot run --openapi http://localhost:8080/v3/api-docs --base-url http://localhost:8080
```

示例应用故意包含一个 bug：`POST /users` 缺少 `@Valid` 注解，导致 `required_missing body.name` 场景返回 500 而非 4xx。TestPilot 能正确检测到这个 bug。

## 报告与退出码

### 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 全部测试通过 |
| `1` | 存在测试失败（FAIL） |
| `2` | 应用/工具错误（ERROR）——如 OpenAPI 加载失败、参数错误等 |

### 报告结构

```json
{
  "summary": {
    "total_endpoints": 3,
    "total_scenarios": 14,
    "total_cases": 14,
    "passed": 6,
    "failed": 8,
    "errors": 0,
    "pass_rate": 0.429
  },
  "cases": [
    {
      "case_id": "tc-sc-createUser-required_missing-body_name-1",
      "scenario_id": "sc-createUser-required_missing-body_name",
      "endpoint_id": "createUser",
      "scenario": { "category": "required_missing", "target_path": "body.name" },
      "request": { "method": "POST", "path": "/users", "body": {...} },
      "execution": { "status_code": 500, "response_time_ms": 45.2 },
      "validation": { "passed": false, "severity": "fail", "checks": [...] }
    }
  ]
}
```

### 敏感值脱敏

报告中以下字段自动脱敏：
- `Authorization` / `Cookie` headers
- 请求体中的敏感字段
- Query 参数中的 token/key

Bearer Token **永不**出现在报告或终端输出中。

## LLM 语义测试

当提供 `--goal` 时，TestPilot 使用 LLM 生成超出确定性生成范围的语义测试场景。这些场景探测格式违规、边界条件和类型混淆。

### 配置

通过环境变量或 `.env` 文件设置 LLM 凭据。

**方式 A：环境变量**

```bash
export TESTPILOT_LLM_API_KEY=sk-your-key-here
export TESTPILOT_LLM_BASE_URL=https://api.openai.com/v1
export TESTPILOT_LLM_MODEL=gpt-4o-mini
```

**方式 B：`.env` 文件**

复制示例文件并填入你的凭据：

```bash
cp .env.example .env
# 编辑 .env 填入你的凭据
```

`.env` 文件会在启动时自动加载。已定义的环境变量优先级高于 `.env` 中的值。

### 工作原理

1. **意图规划** — LLM 根据目标选择要测试的端点
2. **语义规划** — LLM 提出创造性的负面测试场景（格式违规、边界值、类型混淆）
3. **资格过滤** — 提案根据 schema 约束进行检查；仅执行确实违反约束的提案
4. **执行** — 语义测试通过与确定性测试相同的 HTTP → 验证 → 报告流水线运行

语义场景在报告中以 `"source": "llm"` 和 `"category": "semantic_negative"` 标识。

### 安全保障

- LLM 失败不会中止运行——确定性测试始终完成
- 仅尝试 body 参数变更（不变更 path/query/header）
- 无法根据 schema 验证的提案会被静默跳过
- API 密钥不会被打印或写入报告

## 当前限制

- 仅支持 OpenAPI 3.0.x（不支持 Swagger 2.0 或 OpenAPI 3.1）
- 不支持认证流程测试（OAuth2、API Key 等——仅支持静态 Bearer Token）
- 不支持多步骤 API 测试（如：先创建资源，再更新，再删除）
- 不支持文件上传/下载测试
- 不支持 WebSocket / gRPC
- 无数据库/缓存验证

## Roadmap

> **以下功能均为规划中，尚未实现。**

| 功能 | 状态 | 说明 |
|------|------|------|
| Natural Language Test Intent | ✅ 已完成 | 用自然语言描述测试意图，自动生成场景（`--goal`） |
| LLM Semantic Planner | ✅ 已完成 | 基于 LLM 的智能场景规划，补充确定性生成的盲区 |
| LangGraph Orchestration | 🔜 计划中 | 多步骤 API 测试的有向图编排 |
| API Dependency Chain | 🔜 计划中 | 自动识别 API 间依赖关系，支持链式测试（如先创建再查询） |
| Database / Redis Validation | 🔜 计划中 | 测试执行后验证数据库/缓存状态 |
| OpenAPI 3.1 Support | 🔜 计划中 | 支持 OpenAPI 3.1 规范 |
| Authentication Flow Testing | 🔜 计划中 | 支持 OAuth2、API Key 等认证流程 |
| HTML Report | 🔜 计划中 | 可视化 HTML 测试报告 |

## 工程原则

项目遵循以下核心原则（详见 `constitution.md`）：

1. **No Mocking the Core Loop** — 核心执行路径使用真实 HTTP
2. **Deterministic by Default** — 相同输入 = 相同输出
3. **Schema-Driven Generation** — 测试数据从 OpenAPI schema 生成
4. **Fail Loudly on Contract Violations** — 严格验证 API 契约
5. **Minimal Dependencies** — 只依赖必要的库
6. **No Secret Leaks** — 敏感信息永不泄露

## 许可证

TBD
