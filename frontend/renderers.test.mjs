import test from 'node:test';
import assert from 'node:assert/strict';

import { calendarMarkup, draftMarkup, questionsMarkup } from './renderers.mjs';

test('single-choice questions render every backend option and a custom input', () => {
  const html = questionsMarkup([{
    question_id: 'q_start_time',
    question: '会议几点开始？',
    input_type: 'single_choice',
    options: [{ label: '13:00', value: '13:00' }, { label: '15:00', value: '15:00' }],
    allow_custom_input: true,
  }]);

  assert.match(html, /name="q_start_time"/);
  assert.match(html, /value="15:00"/);
  assert.match(html, /自定义时间/);
  assert.match(html, /data-custom-for="q_start_time"/);
});

test('free-text questions render a required answer field', () => {
  const html = questionsMarkup([{
    question_id: 'q_location',
    question: '在哪里见面？',
    input_type: 'free_text',
    options: [],
    allow_custom_input: true,
  }]);

  assert.match(html, /name="q_location"/);
  assert.match(html, /required/);
});

test('draft markup renders API items, instructions, conflicts, and assumptions', () => {
  const html = draftMarkup({
    status: 'ready',
    assumptions: ['AI猜测，可修改'],
    clarifications: [{ question: '面试几点开始？', answer: '14:00' }],
    items: [
      { id: 'a', kind: 'scheduled', title: '快走', start_at: '2026-09-02T18:00:00+08:00', end_at: '2026-09-02T18:30:00+08:00', conflict_state: null, unscheduled_reason: null, editable: true, task_template: { instructions: '以舒适速度快走30分钟' }, provenance: [] },
      { id: 'b', kind: 'unscheduled', title: '阅读', start_at: null, end_at: null, conflict_state: 'unscheduled', unscheduled_reason: '没有可用时段', editable: true, task_template: null, provenance: [] },
    ],
  });

  assert.match(html, /快走/);
  assert.match(html, /以舒适速度快走30分钟/);
  assert.match(html, /没有可用时段/);
  assert.match(html, /AI猜测，可修改/);
  assert.match(html, /你补充的信息/);
  assert.match(html, /面试几点开始？/);
  assert.match(html, /14:00/);
});

test('draft markup states the planning horizon returned by the API', () => {
  const html = draftMarkup({
    window_days: 30,
    items: [],
  });

  assert.match(html, /本次规划 30 天/);
});

test('draft markup explains when an AI-suggested occurrence count was reduced', () => {
  const html = draftMarkup({
    items: [{
      id: 'a', kind: 'scheduled', title: '面试准备',
      start_at: '2026-09-03T10:00:00+08:00', end_at: '2026-09-03T10:30:00+08:00',
      conflict_state: null, unscheduled_reason: null, editable: true,
      task_template: { instructions: '复习核心知识点' },
      provenance: [{
        field_path: 'task_template.occurrences_within_window', source: 'system_derived',
        reason: 'AI 原建议 4 次，受截止时间限制，已调整为 2 次。', display_label: '系统推导',
      }],
    }],
  });

  assert.match(html, /AI 原建议 4 次，受截止时间限制，已调整为 2 次。/);
});

test('calendar markup renders seven dynamic days and API event ids', () => {
  const html = calendarMarkup({ start: '2026-08-31T00:00:00+08:00', end: '2026-09-07T00:00:00+08:00' }, [
    { id: 'e1', source: 'ai', title: '客户会议', start_at: '2026-09-02T15:00:00+08:00', end_at: '2026-09-02T16:00:00+08:00' },
  ]);
  assert.equal((html.match(/class="calendar-day/g) ?? []).length, 7);
  assert.match(html, /data-event-id="e1"/);
  assert.match(html, /客户会议/);
  assert.match(html, /15:00/);
});
