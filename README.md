# AI 日历

用自然语言描述安排和目标，生成可编辑的日历草案，并在用户确认后写入日历。

面向需要同时管理工作、生活和学习安排的个人用户，减少逐条录入日程的操作，并将模糊目标转化为近期行动。应用采用原生 JavaScript 前端、FastAPI 后端、两阶段大模型理解与规划，以及独立的规则排程器。

## 界面展示

以下为应用本地运行时的首页、周日历和自然语言输入界面。

![AI 日历首页](docs/images/home.jpg)
![AI 日历周视图](docs/images/calendar.jpg)
![自然语言输入界面](docs/images/input.jpg)

## 核心流程

例如输入：“下周三下午三点和客户开会一小时，接下来两周每周一、周五晚上读书三十分钟。”

1. **理解与追问**：区分明确安排与长期目标，提取时间、频率和用户约束；关键信息不足时追问。
2. **生成行动**：模型产出固定安排和任务模板，补充的假设在草案中标明。
3. **规则排程**：结合已有日程、睡眠、指定星期与时段等约束安排时间；放不下的任务保留原因。
4. **查看与编辑**：用户检查草案，修改或删除项目。
5. **确认落库**：整组确认后写入日历；重复确认使用幂等键防止重复写入。

默认规划未来 14 天；明确提出“一个月/30 天”时使用 30 天窗口。生成的草案结合输入内容、已有日程与时间规则确定。

## 功能范围与使用限制

- 支持新增计划、追问、草案编辑与整组确认、日历查询、手动修改和删除已有日程，以及时间偏好接口。
- 日程保存在本应用中，不与飞书、Google Calendar 等外部日历同步。产品面向单用户使用，不包含多人账号隔离、提醒或自动续排；已有日程通过界面手动修改和删除。
- 部署模式使用共享访问码，访问控制不包含按用户计次、调用限流或费用硬上限，适用于受控的个人演示环境。
- 页面样式使用外部字体服务，字体无法加载时使用系统字体。

详细范围见 [产品范围](docs/PRODUCT.md)，模型、规则和用户的分工见 [架构与设计](docs/ARCHITECTURE.md)。

## 首次本地运行

以下步骤使用 Windows 和 PowerShell。先安装 Python 3.12 和 Node.js 22.12 或更高版本，再从解压后的项目根目录开始执行。

### 1. 初始化并启动后端

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

编辑 `backend/.env`，填写自己模型服务的 `LLM_API_KEY`，并设置 `LLM_BASE_URL`、`LLM_MODEL`。示例配置使用智谱兼容接口；模型的可用性、权限与计费由服务商决定。模型服务需要支持项目采用的 Chat Completions 请求格式，并返回符合输出契约的内容。密钥仅保存在后端配置中，`.env` 文件不提交到 GitHub。

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000
```

### 2. 另开终端启动前端

在项目根目录的新终端执行：

```powershell
cd frontend
node serve.mjs
```

打开 <http://127.0.0.1:4173/>。本地静态服务使用 Node.js 内置模块，无需先运行 npm 安装；它会把 `/api/` 请求转发到后端。后端接口文档位于 <http://127.0.0.1:8000/docs>。

完成首次安装和配置后，日常可以双击根目录 `启动AI日历.bat`。该入口只负责启动已有环境，不会自动安装依赖或填写密钥。不要直接双击 HTML 文件。

AI 规划使用后端配置的真实模型服务；自动化测试使用模拟模型，可在不配置模型密钥的情况下运行。

## 测试与模型评测

在 `backend` 目录运行后端测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

在 `frontend` 目录运行前端测试：

```powershell
node --test *.test.mjs
```

这些自动化测试使用模拟模型，不消耗真实模型额度。独立的真实模型 Prompt 评测见 [评测说明](tools/prompt-tests/README.md)，需要额外配置并会产生调用费用。

## 项目结构

```text
frontend/              页面、交互状态、API 客户端、前端测试和必要素材
backend/app/           接口、模型接入、Prompt、排程规则与数据库迁移
backend/tests/         单元、集成、契约、端到端测试和坏例样本
tools/prompt-tests/    当前 Prompt 评测与坏例提取工具
docs/                  产品范围、架构、部署说明和当前界面截图
render.yaml            后端云部署配置模板
启动AI日历.bat         完成首次配置后的 Windows 启动入口
```

## 关键设计与实现

| 设计问题 | 解决方式 | 代码与测试入口 |
| --- | --- | --- |
| 模型理解与排程的职责划分 | 两阶段模型分别完成理解与行动生成，规则排程器安排具体时间；模型输出经过结构校验与归一化 | `backend/app/prompts/`、`backend/app/llm/service.py`、`backend/app/planning/` |
| 用户约束与时间冲突 | 保留用户指定的星期、时段与睡眠约束，结合已有日程排程，无法排入的任务保留原因 | `backend/tests/unit/test_scheduler.py` |
| 用户控制与重复操作 | 先生成可编辑草案，整组确认后写入日历；通过幂等键避免重复确认产生重复日程 | `backend/app/planning/drafts.py`、`frontend/state-machine.mjs` |
| 模型异常与回归检查 | 对不合法输出返回可重试错误，将脱敏后的失败样本固化为回归用例 | `backend/tests/fixtures/badcases/`、`backend/tests/unit/test_badcase_regressions.py` |

## 可选部署

应用支持本地运行与云端部署，部署步骤见 [部署说明](docs/DEPLOYMENT.md)。在线运行需要分别配置前端、后端和数据库；仓库不提供公共 AI 试用入口。
