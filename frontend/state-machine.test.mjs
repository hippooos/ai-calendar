import assert from 'node:assert/strict';
import { createInitialState, transition } from './state-machine.mjs';

let state = createInitialState();
assert.equal(state.screen, 'calendar');
assert.equal(state.overlay, 'none');

state = transition(state, { type: 'OPEN_AI_FLOW' });
assert.equal(state.screen, 'calendar');
assert.equal(state.overlay, 'input');

state = transition(state, { type: 'GENERATE', missingCriticalInfo: true });
assert.equal(state.overlay, 'questions');
assert.equal(state.writeStatus, '未写入');

state = transition(state, { type: 'SUBMIT_QUESTIONS' });
assert.equal(state.overlay, 'draft');
assert.equal(state.draftStatus, '待确认');

state = transition(state, { type: 'CONFIRM_DRAFT' });
assert.equal(state.screen, 'calendar');
assert.equal(state.overlay, 'none');
assert.equal(state.writeStatus, '已写入 AI 日历');
assert.equal(state.draftStatus, '已确认');

state = transition(state, { type: 'DELETE_AI_EVENT' });
assert.equal(state.lastAction, '已删除 1 条 AI 日程');

state = transition(state, { type: 'EDIT_AI_EVENT' });
assert.equal(state.lastAction, '正在编辑 1 条 AI 日程');

console.log('phase-one state machine: all assertions passed');
