import test from 'node:test';
import assert from 'node:assert/strict';

import { createPrototypeServer } from './serve.mjs';

test('api proxy reports a structured 502 when the backend is unavailable', async (t) => {
  const server = createPrototypeServer({ frontendPort: 0, backendPort: 65534 });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();

  const response = await fetch(`http://127.0.0.1:${port}/api/calendar/events?start=x&end=y`);
  const body = await response.json();

  assert.equal(response.status, 502);
  assert.equal(body.error_code, 'DEV_PROXY_ERROR');
  assert.equal(body.retryable, true);
});

test('root serves the home page and links to the connected calendar application', async (t) => {
  const server = createPrototypeServer({ backendPort: 65534 });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();

  const html = await (await fetch(`http://127.0.0.1:${port}/`)).text();

  assert.match(html, /id="entry-events"/);
  assert.match(html, /src="\.\/home\.mjs"/);
  assert.match(html, /href="\.\/app\.html"/);

  const calendarResponse = await fetch(`http://127.0.0.1:${port}/app.html`);
  assert.equal(calendarResponse.status, 200);
  const calendarHtml = await calendarResponse.text();
  assert.match(calendarHtml, /id="planning-input"/);
  assert.match(calendarHtml, /src="\.\/app\.mjs"/);
});

test('stylesheets are served with a browser-compatible CSS content type', async (t) => {
  const server = createPrototypeServer({ backendPort: 65534 });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const { port } = server.address();

  const response = await fetch(`http://127.0.0.1:${port}/app.css`);

  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type') ?? '', /^text\/css\b/);
});
