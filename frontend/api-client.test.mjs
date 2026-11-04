import test from 'node:test';
import assert from 'node:assert/strict';

import { ApiError, createApiClient } from './api-client.mjs';

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

test('createPlanningSession posts the user input and keeps the returned session id', async () => {
  const calls = [];
  const client = createApiClient({
    getAccessCode: () => null,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse({ id: 's1', status: 'needs_clarification', questions: [], error_code: null }, 201);
    },
  });

  const result = await client.createPlanningSession('周三下午开会', '2026-08-31T10:00:00+08:00');

  assert.equal(calls[0].url, '/api/planning/sessions');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    raw_input: '周三下午开会',
    reference_now: '2026-08-31T10:00:00+08:00',
  });
  assert.equal(result.id, 's1');
});

test('api errors preserve the backend request id and retryability', async () => {
  const client = createApiClient({
    getAccessCode: () => null,
    fetchImpl: async () => jsonResponse({
      error_code: 'MODEL_UNAVAILABLE',
      message: '模型服务暂时不可用',
      retryable: true,
      request_id: 'r1',
    }, 503),
  });

  await assert.rejects(
    () => client.createPlanningSession('安排会议', '2026-08-31T10:00:00+08:00'),
    error => error instanceof ApiError
      && error.errorCode === 'MODEL_UNAVAILABLE'
      && error.retryable === true
      && error.requestId === 'r1',
  );
});

test('submitAnswers posts answers to the active planning session', async () => {
  const calls = [];
  const client = createApiClient({
    getAccessCode: () => null,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse({ id: 's1', status: 'a_ready', questions: [], error_code: null });
    },
  });

  const result = await client.submitAnswers('s1', { q_start_time: '15:00' });

  assert.equal(calls[0].url, '/api/planning/sessions/s1/answers');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), { answers: { q_start_time: '15:00' } });
  assert.equal(result.status, 'a_ready');
});

test('draft API creates and reloads a draft by id', async () => {
  const calls = [];
  const client = createApiClient({
    getAccessCode: () => null,
    fetchImpl: async (url, init = {}) => {
      calls.push({ url, init });
      return jsonResponse({ id: 'd1', status: 'ready', assumptions: [], items: [] }, init.method === 'POST' ? 201 : 200);
    },
  });

  await client.generateDraft('s1');
  await client.getDraft('d1');

  assert.equal(calls[0].url, '/api/planning/sessions/s1/generate-draft');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[1].url, '/api/drafts/d1');
});

test('draft item API updates and deletes the selected item', async () => {
  const calls = [];
  const client = createApiClient({
    getAccessCode: () => null,
    fetchImpl: async (url, init = {}) => {
      calls.push({ url, init });
      return init.method === 'DELETE' ? new Response(null, { status: 204 }) : jsonResponse({ id: 'd1', items: [] });
    },
  });
  const payload = {
    title: '客户方案沟通',
    start_at: '2026-09-02T15:30:00+08:00',
    end_at: '2026-09-02T16:30:00+08:00',
  };

  await client.updateDraftItem('d1', 'i1', payload);
  await client.deleteDraftItem('d1', 'i1');

  assert.equal(calls[0].url, '/api/drafts/d1/items/i1');
  assert.equal(calls[0].init.method, 'PATCH');
  assert.deepEqual(JSON.parse(calls[0].init.body), payload);
  assert.equal(calls[1].url, '/api/drafts/d1/items/i1');
  assert.equal(calls[1].init.method, 'DELETE');
});

test('confirmDraft sends the caller supplied idempotency key', async () => {
  const calls = [];
  const client = createApiClient({
    getAccessCode: () => null,
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse({ draft_id: 'd1', event_ids: ['e1'] });
    },
  });

  await client.confirmDraft('d1', 'stable-key');

  assert.equal(calls[0].url, '/api/drafts/d1/confirm');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.headers.get('Idempotency-Key'), 'stable-key');
});

test('getCalendarEvents encodes the requested range and access code', async () => {
  const calls = [];
  const client = createApiClient({
    getAccessCode: () => 'owner-code',
    fetchImpl: async (url, init) => {
      calls.push({ url, init });
      return jsonResponse([]);
    },
  });
  await client.getCalendarEvents('2026-08-31T00:00:00+08:00', '2026-09-07T00:00:00+08:00');

  const url = new URL(calls[0].url, 'http://local.test');
  assert.equal(url.pathname, '/api/calendar/events');
  assert.equal(url.searchParams.get('start'), '2026-08-31T00:00:00+08:00');
  assert.equal(url.searchParams.get('end'), '2026-09-07T00:00:00+08:00');
  assert.equal(calls[0].init.headers.get('X-Access-Code'), 'owner-code');
});
