# 部署说明

应用采用静态前端、FastAPI 后端与 PostgreSQL 数据库分离的部署方式。仓库提供部署配置模板，使用时填写自己的服务地址与服务器环境变量。

## 服务分工

- 前端：托管 `frontend` 下的静态页面，或者运行 `npm ci`、`npm run build` 后托管 `frontend/dist`。
- 后端：运行 `backend/Dockerfile` 中的 FastAPI 服务，先执行数据库迁移。
- 数据库：部署配置使用 PostgreSQL，例如自行管理的数据库或 Supabase 提供的 PostgreSQL。

## 后端配置

在部署平台的服务器环境变量中配置 `APP_MODE=deployed`、`APP_ACCESS_CODE`、`DATABASE_URL`、`LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`。变量模板见 `backend/.env.production.example`；不要提交填好秘密信息的副本。

PostgreSQL 连接字符串应使用 SQLAlchemy 的 `postgresql+psycopg://` 格式，实际主机、端口、用户名及连接模式以数据库服务提供的信息为准。

`render.yaml` 提供 Render Blueprint 模板，默认根目录为 `backend`；也可以在其他支持 Docker 的环境运行。后端容器监听 8000，部署平台需正确映射该端口；公网访问需配置 HTTPS。`/readyz` 用于检查数据库连接，模型连通性通过业务请求检查。

## 前端配置

使用 Vercel 时，以 `frontend` 为根目录。`vercel.json` 中 `/api/:path*` 指向占位后端域名，必须换成自己的后端地址。可使用静态源码托管，或使用 Vite 构建并发布 `dist`；部署配置需要与所选方式一致。

浏览器通过同源 `/api/` 访问后端，不应拿到模型密钥。纯 GitHub Pages 不会运行 FastAPI，也不提供此配置中的 API 反向代理；仅开启 Pages 不足以让 AI 功能工作。

## 本地容器方式

在 `backend` 目录设置 `POSTGRES_PASSWORD`、`APP_ACCESS_CODE`、`LLM_API_KEY` 后运行 `docker compose up --build`。必要时同时设置模型名称和网关地址。该配置启动数据库与后端，前端仍需单独提供页面。

## 部署验收

1. 使用演示数据验证输入、追问、草案、确认和刷新后的数据保存。
2. 验证无访问码或错误访问码无法调用部署版业务接口。
3. 访问范围限定为持有码的受控环境；配置不包含调用配额、限流或费用硬上限。
4. 私人日程、模型运行记录、数据库、`.env` 与本地日志不放进仓库。

