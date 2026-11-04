import test from 'node:test';
import assert from 'node:assert/strict';

import { applySession, createInitialAppState } from './app-state.mjs';

test('needs_clarification session opens the questions overlay and stores its id', () => {
  const state = applySession(createInitialAppState(), {
    id: 'session-1',
    status: 'needs_clarification',
    questions: [{ question_id: 'q1' }],
    error_code: null,
  });

  assert.equal(state.sessionId, 'session-1');
  assert.equal(state.overlay, 'questions');
  assert.deepEqual(state.questions, [{ question_id: 'q1' }]);
  assert.equal(state.requestStatus, 'idle');
});

test('manual_required session stays visible as a stopped flow', () => {
  const state = applySession(createInitialAppState(), {
    id: 'session-2', status: 'manual_required', questions: [], error_code: null,
  });

  assert.equal(state.overlay, 'message');
  assert.equal(state.planningStatus, 'manual_required');
});

test('model validation failure opens an error state instead of unsupported messaging', () => {
  const state = applySession(createInitialAppState(), {
    id: 'session-3', status: 'validation_failed', questions: [], error_code: 'MODEL_OUTPUT_INVALID',
  });

  assert.equal(state.overlay, 'message');
  assert.equal(state.planningStatus, 'validation_failed');
  assert.equal(state.error.message, '草案未生成，也没有写入日历。请返回修改后重新生成。');
});
