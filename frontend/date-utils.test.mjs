import test from 'node:test';
import assert from 'node:assert/strict';

import { groupEventsByLocalDate, weekRange } from './date-utils.mjs';

test('weekRange returns local Monday through next Monday', () => {
  assert.deepEqual(weekRange(new Date('2026-08-31T10:00:00+08:00')), {
    start: '2026-08-31T00:00:00+08:00',
    end: '2026-09-07T00:00:00+08:00',
  });
});

test('events are grouped by the date in their returned timezone', () => {
  const grouped = groupEventsByLocalDate([
    { id: 'e1', start_at: '2026-09-02T18:00:00+08:00', end_at: '2026-09-02T18:30:00+08:00' },
  ]);
  assert.equal(grouped['2026-09-02'][0].id, 'e1');
});
