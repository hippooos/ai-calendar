import test from 'node:test';
import assert from 'node:assert/strict';

import { resolveQuestionAnswer } from './question-answers.mjs';

test('a filled custom answer is accepted even when its radio was not selected', () => {
  const answer = resolveQuestionAnswer({
    selectedValue: '',
    customValue: '明天下午两点',
    freeTextValue: '',
  });

  assert.equal(answer, '明天下午两点');
});

test('a selected preset takes precedence over a stale custom value', () => {
  const answer = resolveQuestionAnswer({
    selectedValue: '15:00',
    customValue: '14:00',
    freeTextValue: '',
  });

  assert.equal(answer, '15:00');
});
