import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

// 纯原生 ESM 项目的多页构建：源码保持零构建可直接运行，
// 这里只负责产出压缩 + hash 文件名的 dist，不引入任何框架。
const root = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig({
  root,
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: resolve(root, 'index.html'),
        home: resolve(root, 'home.html'),
        app: resolve(root, 'app.html'),
      },
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      // 必须带结尾斜杠：'/api' 会误伤 api-client.mjs 这类静态模块，
      // 把它们当成后端接口转发而返回 404，导致整个 app.mjs 加载失败。
      '/api/': 'http://127.0.0.1:8000',
    },
  },
});
