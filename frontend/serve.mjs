import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer, request as httpRequest } from 'node:http';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = normalize(fileURLToPath(new URL('.', import.meta.url)));
const types = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.png': 'image/png',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
};

export function createPrototypeServer({ backendPort = 8000 } = {}) {
  return createServer((incoming, response) => {
    if (incoming.url?.startsWith('/api/')) {
      const proxy = httpRequest({
        hostname: '127.0.0.1',
        port: backendPort,
        path: incoming.url,
        method: incoming.method,
        headers: { ...incoming.headers, host: `127.0.0.1:${backendPort}` },
      }, backendResponse => {
        response.writeHead(backendResponse.statusCode ?? 502, backendResponse.headers);
        backendResponse.pipe(response);
      });
      proxy.on('error', () => {
        if (response.headersSent) return response.end();
        response.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end(JSON.stringify({
          error_code: 'DEV_PROXY_ERROR',
          message: '后端服务未启动',
          retryable: true,
          request_id: null,
        }));
      });
      incoming.pipe(proxy);
      return;
    }

    const pathname = incoming.url === '/' ? '/home.html' : new URL(incoming.url ?? '/', 'http://localhost').pathname;
    const target = normalize(join(root, pathname));
    if (!target.startsWith(root) || !existsSync(target)) {
      response.writeHead(404).end('Not found');
      return;
    }
    const headers = { 'Content-Type': types[extname(target)] ?? 'application/octet-stream' };
    if ((target.endsWith('.html') || target.endsWith('.mjs') || target.endsWith('.css'))) {
      headers['Cache-Control'] = 'no-cache, no-store, must-revalidate';
      headers['Pragma'] = 'no-cache';
      headers['Expires'] = '0';
    }

    /* 视频必须支持 Range（206 Partial Content + Accept-Ranges）。
       否则浏览器会禁用 seek，video.currentTime 永远设不进去，scrub 与人物眼神跟随全部失效。 */
    const size = statSync(target).size;
    headers['Accept-Ranges'] = 'bytes';

    const rangeHeader = incoming.headers.range;
    const match = rangeHeader ? /^bytes=(\d*)-(\d*)$/.exec(rangeHeader) : null;
    if (match) {
      const start = match[1] === '' ? 0 : Number(match[1]);
      const end = match[2] === '' ? size - 1 : Math.min(Number(match[2]), size - 1);
      if (Number.isNaN(start) || Number.isNaN(end) || start > end || start >= size) {
        response.writeHead(416, { 'Content-Range': `bytes */${size}` }).end();
        return;
      }
      response.writeHead(206, {
        ...headers,
        'Content-Range': `bytes ${start}-${end}/${size}`,
        'Content-Length': end - start + 1,
      });
      createReadStream(target, { start, end }).pipe(response);
      return;
    }

    response.writeHead(200, { ...headers, 'Content-Length': size });
    createReadStream(target).pipe(response);
  });
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url))) {
  const frontendPort = Number(process.env.FRONTEND_PORT ?? 4173);
  const backendPort = Number(process.env.BACKEND_PORT ?? 8000);
  createPrototypeServer({ backendPort }).listen(frontendPort, '127.0.0.1', () => {
    console.log(`Prototype available at http://127.0.0.1:${frontendPort}`);
  });
}
