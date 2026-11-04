# AI 日历后端

后端实现“自然语言 → 阶段 A 理解/追问 → 阶段 B 任务模板 → 14/30 天确定性排程 → 整组确认 → AI 日历写入”。默认窗口为 14 天，用户明确要求一个月或 30 天时使用 30 天窗口。

## 本机运行

要求 Python 3.12。先在项目根目录执行 `cd backend`，以下 PowerShell 命令均在本目录运行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
# 在 .env 中填写 LLM_API_KEY；不要把 .env 提交到版本库
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

本机 `APP_MODE=local`，业务接口免登录。接口文档：http://127.0.0.1:8000/docs

随后另开终端运行 `cd ..\frontend; node serve.mjs`，浏览器打开 http://127.0.0.1:4173 。前端使用同源 `/api`，开发服务器代理到本后端。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## 坏例回归

服务层通过结构校验与归一化处理模型输出，并使用回归样本覆盖已知异常。异常样本的维护流程：

1. 在 `model_runs.diagnostic_json` 中记录模型原始输出与字段级错误。
2. 使用 `python ..\tools\prompt-tests\capture_badcases.py` 提取样本，完成隐私检查后保存至 `tests/fixtures/badcases/`。
3. 在 `tests/unit/test_badcase_regressions.py` 中验证样本包含目标异常，以及归一化后的输出符合预期。
4. 结构兼容处理集中于 `app/llm/service.py`；Prompt 与输出契约同步维护。

注意：成功运行的 `diagnostic_json` 会被存成字符串 `null`，查询时不能只用 `IS NOT NULL`。

测试使用真实 SQLite、模型网关协议模拟器和 FastAPI 应用，不消耗模型额度。真实 Prompt 评测位于 `../tools/prompt-tests/prompt_v3_test.py`，从环境变量或 `backend/.env` 读取模型配置。

## 部署

部署方式见 [部署说明](../docs/DEPLOYMENT.md)，配置采用静态前端、FastAPI 服务与 PostgreSQL 的组合。

部署版使用 PostgreSQL 和单一访问码：

```powershell
$env:POSTGRES_PASSWORD = "请使用强随机密码"
$env:APP_ACCESS_CODE = "请使用强随机访问码"
$env:LLM_API_KEY = "你的模型密钥"
docker compose up --build
```

除 `/healthz`、`/readyz` 和接口文档外，业务请求必须带：

```text
X-Access-Code: <APP_ACCESS_CODE>
```

公网部署必须在反向代理或云负载均衡器终止 HTTPS。不要把访问码、数据库密码或模型密钥写入镜像、Compose 文件或 URL。

## 核心接口

- `POST /api/planning/sessions`：提交自然语言。
- `POST /api/planning/sessions/{id}/answers`：回答阶段 A 追问。
- `POST /api/planning/sessions/{id}/generate-draft`：阶段 B 拆解并排程。
- `GET /api/drafts/{id}`：查看整组草案。
- `PATCH/DELETE /api/drafts/{id}/items/{item_id}`：编辑或删除 ready 草案项目。
- `POST /api/drafts/{id}/confirm`：携带 `Idempotency-Key` 整组确认。
- `POST /api/drafts/{id}/cancel`：放弃草案。
- `GET /api/calendar/events`：查询 AI 日程。
- `PATCH/DELETE /api/calendar/events/{event_id}`：手动修改或删除日程。
- `GET/PUT /api/profile`：维护时区、工作和睡眠设置。

## 数据与失败规则

- 时间进入领域层时必须带时区；数据库统一按配置连接。
- 未确认草案不会写入 `calendar_events`。
- 模型超时或输出不合法时保存会话失败状态，返回可重试错误，不生成残缺草案。
- 模型输出结构校验失败时，原始输出与字段级错误保存在 `model_runs.diagnostic_json`，用于定位异常与维护回归样本。
- 单任务时长上限、字段名白名单、复合事项覆盖、阶段间一一对应等约束由 `app/llm/service.py` 归一化与校验；语义覆盖或阶段转换失败时自动定向重试一次。Prompt 版本为 `phase-a-v3.7` / `phase-b-v3.6`。
- 排程器不放宽用户硬星期、硬时段、睡眠冲突或 36 小时间隔；用户明确要求的次数放不下时保留未排入项并附容量说明。
- `Idempotency-Key` 防止重复确认产生重复日程。
