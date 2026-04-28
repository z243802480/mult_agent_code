# 多智能体自主开发系统 - 中文文档导航

## 1. 文档定位

本文档是中文文档入口。

当前文档分为两类：

- **主文档**：用于长期维护、评审和进入实现。
- **归档分册**：早期讨论沉淀的细分文档，放在 `archive/` 目录，保留为详细参考，不随意删除需求。

建议日常优先阅读主文档。

## 2. 推荐阅读顺序

### 2.1 快速理解项目

1. [PRODUCT_SPEC.md](./PRODUCT_SPEC.md)
2. [ARCHITECTURE.md](./ARCHITECTURE.md)
3. [DELIVERY_PLAN.md](./DELIVERY_PLAN.md)

### 2.2 准备进入实现

1. [DATA_MODEL.md](./DATA_MODEL.md)
2. [RUNTIME_COMMANDS.md](./RUNTIME_COMMANDS.md)
3. [MODEL_PROVIDER_SPEC.md](./MODEL_PROVIDER_SPEC.md)
4. [COST_SECURITY_RISK.md](./COST_SECURITY_RISK.md)
5. [QUALITY_AND_EVALUATION.md](./QUALITY_AND_EVALUATION.md)

### 2.3 具体开发时查阅

1. [RUNTIME_COMMANDS.md](./RUNTIME_COMMANDS.md)
2. [DATA_MODEL.md](./DATA_MODEL.md)
3. [DELIVERY_PLAN.md](./DELIVERY_PLAN.md)
4. [DEVELOPMENT.md](./DEVELOPMENT.md)

## 3. 主文档

| 文档 | 作用 | 来源 |
| --- | --- | --- |
| [PRODUCT_SPEC.md](./PRODUCT_SPEC.md) | 产品目标、需求、使用场景、成功标准 | 合并 `PROJECT_GOAL.md`、`REQUIREMENTS.md` |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 架构、技术方案、运行时分层、模块边界 | 合并 `DESIGN.md`、`TECHNICAL_PLAN.md` |
| [DATA_MODEL.md](./DATA_MODEL.md) | 核心数据对象、schema、状态转移、落盘结构 | 单独保留 |
| [RUNTIME_COMMANDS.md](./RUNTIME_COMMANDS.md) | 命令规格、任务拆解规则、工作流 | 合并 `COMMAND_SPECS.md`、`TASK_DECOMPOSITION_GUIDE.md` |
| [DELIVERY_PLAN.md](./DELIVERY_PLAN.md) | MVP 范围、阶段路线图、实施任务 | 合并 `MVP_SCOPE.md`、`IMPLEMENTATION_TASKS.md` |
| [QUALITY_AND_EVALUATION.md](./QUALITY_AND_EVALUATION.md) | 验收指标、评估体系、测试策略 | 合并 `EVALUATION.md`、`TEST_STRATEGY.md` |
| [COST_SECURITY_RISK.md](./COST_SECURITY_RISK.md) | 成本控制、安全策略、风险治理 | 基于 `COST_AND_RISK.md` |
| [MODEL_PROVIDER_SPEC.md](./MODEL_PROVIDER_SPEC.md) | MiniMax/OpenAI-compatible 模型接口、路由、重试、日志 | 新增模型适配规格 |
| [DEVELOPMENT.md](./DEVELOPMENT.md) | 本地开发、运行、测试和模型配置说明 | 新增开发指南 |

## 4. 原始分册

以下文档保留为详细参考：

- [archive/PROJECT_GOAL.md](./archive/PROJECT_GOAL.md)
- [archive/REQUIREMENTS.md](./archive/REQUIREMENTS.md)
- [archive/DESIGN.md](./archive/DESIGN.md)
- [archive/TECHNICAL_PLAN.md](./archive/TECHNICAL_PLAN.md)
- [archive/COMMAND_SPECS.md](./archive/COMMAND_SPECS.md)
- [archive/TASK_DECOMPOSITION_GUIDE.md](./archive/TASK_DECOMPOSITION_GUIDE.md)
- [archive/MVP_SCOPE.md](./archive/MVP_SCOPE.md)
- [archive/IMPLEMENTATION_TASKS.md](./archive/IMPLEMENTATION_TASKS.md)
- [archive/EVALUATION.md](./archive/EVALUATION.md)
- [archive/TEST_STRATEGY.md](./archive/TEST_STRATEGY.md)
- [archive/COST_AND_RISK.md](./archive/COST_AND_RISK.md)

## 5. 当前阶段

当前项目处于：

```text
Phase 1B：可复现运行环境和执行闭环加固
```

当前验证方式：

1. 本机：`python -m pip install -e ".[dev]"` 后执行 `.\scripts\verify.ps1`。
2. Docker：`docker build -t agent-runtime:verify .` 后执行 `docker run --rm agent-runtime:verify`。
3. CI：GitHub Actions 使用同一套验证脚本，覆盖 Python 3.11 和 3.13。
4. 离线模型：设置 `AGENT_MODEL_PROVIDER=fake` 后可不依赖 API key 跑 CLI smoke。
5. 本地模型：设置 `AGENT_MODEL_PROVIDER=ollama` 和 `AGENT_MODEL_NAME=qwen2.5-coder:7b` 后可连接本机 OpenAI-compatible 服务。

## 6. 文档维护原则

- 主文档用于执行和评审。
- 原始分册用于追溯和细节参考。
- 需求不能因为合并而消失。
- 暂缓需求必须进入路线图、风险处理或后续任务池。
- 高风险能力必须在设计层有控制机制。
