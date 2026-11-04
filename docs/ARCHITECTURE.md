# 架构与设计

## 工作流

```mermaid
flowchart LR
    U[用户输入] --> A[阶段 A：理解与追问]
    A --> B[阶段 B：固定安排与任务模板]
    B --> V[结构校验与归一化]
    V --> S[规则排程]
    S --> D[可编辑草案]
    D --> C[用户整组确认]
    C --> DB[(日历数据库)]
    DB --> UI[刷新日历]
```

前端使用原生 HTML、CSS、ES Module；本地通过 `serve.mjs` 提供页面并代理 `/api/`。后端使用 FastAPI、Pydantic、SQLAlchemy 和 Alembic，模型接入采用兼容 Chat Completions 的接口。

## 职责划分

| 层 | 职责 | 代码入口 |
| --- | --- | --- |
| 阶段 A | 输入分类、事实抽取、关键缺口与追问 | `backend/app/prompts/phase_a.py` |
| 阶段 B | 固定安排、行动建议和任务模板 | `backend/app/prompts/phase_b.py` |
| 校验与编排 | 结构约束、兼容处理、跨阶段一致性与失败状态 | `backend/app/llm/service.py`、`backend/app/planning/orchestrator.py` |
| 排程 | 规划窗口、冲突、时段、星期、频率与间隔 | `backend/app/planning/` |
| 用户确认 | 编辑草案、整组确认、幂等写入 | `backend/app/planning/drafts.py`、`backend/app/api/routes/drafts.py` |
| 前端状态 | 请求反馈、追问、草案、确认和日历刷新 | `frontend/app-state.mjs`、`frontend/state-machine.mjs` |

## 异常处理与测试

- 模型失败或结构不合法时返回可重试错误，不把残缺结果当成已确认日程。
- 模型坏输出保留在诊断数据中，用脱敏样本回归测试；本机数据库与日志不随源码公开。
- 自动化测试使用模拟模型，覆盖输出契约、规则排程、数据库操作、草案编辑/确认与前后端流程。
- 真实 Prompt 评测调用配置的模型服务，直接导入生产 Prompt，检查模型原始输出；服务层归一化由对应的单元与回归测试覆盖。

## 运行配置

部署访问控制采用共享访问码，适用于单用户环境，不包含多用户数据隔离或用量配额。模型网关、名称和凭据通过后端环境变量配置。Python 依赖及版本范围见 `backend/pyproject.toml`，前端构建依赖由 `package-lock.json` 锁定。
