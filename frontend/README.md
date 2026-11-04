# AI 日历前端

原生 HTML/CSS/ES Module 前端，包括近期日程首页、周日历、自然语言输入、追问、草案编辑与确认。

## 本地启动

先按 [根目录运行说明](../README.md) 初始化并启动后端。在本目录执行：

```powershell
node serve.mjs
```

打开 <http://127.0.0.1:4173/>。开发服务器把同源 `/api/` 代理到 `127.0.0.1:8000`；本地模式免登录。`index.html` 跳转首页 `home.html`，完整周日历为 `app.html`。

## 可选构建

```powershell
npm ci
npm run build
```

构建结果位于 `dist`。本地直接运行 `serve.mjs` 不需要构建。Vite 开发入口为 `npm run dev`，与 `serve.mjs` 的默认端口不同；见 `vite.config.js`。

## 测试

```powershell
node --test *.test.mjs
```

## 核心文件

- `home.html` / `home.mjs`：近期日程首页。
- `app.html` / `app.mjs`：周日历与交互。
- `api-client.mjs`：后端请求与访问码。
- `app-state.mjs` / `state-machine.mjs`：状态管理。
- `renderers.mjs`：界面渲染。
- `hero_eyes_circle_smooth_10s.mp4`：页面实际引用的背景动画。

部署后端返回 401 时要求输入共享访问码，保存在当前浏览器的 `sessionStorage` 并通过 `X-Access-Code` 请求头发送。它不提供用户隔离或额度控制。
