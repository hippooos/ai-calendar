import { groupEventsByLocalDate, localDateKey } from './date-utils.mjs';

export function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function singleChoiceMarkup(question) {
  const id = escapeHtml(question.question_id);
  const options = (question.options ?? []).map(option => `
    <label class="choice">
      <input type="radio" name="${id}" value="${escapeHtml(option.value)}" required>
      <span>${escapeHtml(option.label)}</span>
    </label>`).join('');
  const custom = question.allow_custom_input ? `
    <label class="choice custom-choice">
      <input type="radio" name="${id}" value="__custom__" required>
      <span>自定义时间</span>
      <input type="text" inputmode="numeric" placeholder="例如 15:30" data-custom-for="${id}" aria-label="自定义回答：${escapeHtml(question.question)}">
    </label>` : '';
  return `<div class="choice-grid">${options}${custom}</div>`;
}

function freeTextMarkup(question) {
  return `<input class="answer-input" type="text" name="${escapeHtml(question.question_id)}" required aria-label="${escapeHtml(question.question)}">`;
}

export function questionsMarkup(questions = []) {
  return questions.map((question, index) => `
    <fieldset class="question-card" data-question-id="${escapeHtml(question.question_id)}">
      <legend><span>${String(index + 1).padStart(2, '0')}</span>${escapeHtml(question.question)}</legend>
      ${question.input_type === 'single_choice' ? singleChoiceMarkup(question) : freeTextMarkup(question)}
      <p class="question-error" hidden>请选择或填写答案</p>
    </fieldset>`).join('');
}

function localDateTime(value) {
  if (!value) return '';
  const date = new Date(value);
  return new Intl.DateTimeFormat('zh-CN', {
    month: 'long', day: 'numeric', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}

export function draftMarkup(draft) {
  if (!draft) return '';
  const windowNote = draft.window_days
    ? `<p class="draft-window">本次规划 ${escapeHtml(draft.window_days)} 天</p>`
    : '';
  const clarifications = (draft.clarifications ?? [])
    .map(entry => `<li>${escapeHtml(entry.question)}：${escapeHtml(entry.answer)}</li>`)
    .join('');
  const assumptions = (draft.assumptions ?? []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  const items = (draft.items ?? []).map(item => {
    const interval = item.start_at
      ? `${localDateTime(item.start_at)}–${localDateTime(item.end_at).split(' ')[1] ?? localDateTime(item.end_at)}`
      : '尚未排入日历';
    const instructions = item.task_template?.instructions
      ? `<p class="item-instructions">${escapeHtml(item.task_template.instructions)}</p>` : '';
    const provenance = (item.provenance ?? [])
      .filter(entry => entry.display_label)
      .map(entry => `<span class="provenance">${escapeHtml(entry.display_label)}</span>`).join('');
    const adjustment = (item.provenance ?? []).find(entry =>
      entry.field_path === 'task_template.occurrences_within_window'
      && entry.source === 'system_derived'
      && entry.reason?.includes('AI 原建议')
    );
    const adjustmentNote = adjustment ? `<p class="item-adjustment">${escapeHtml(adjustment.reason)}</p>` : '';
    const warning = item.unscheduled_reason || item.conflict_state
      ? `<p class="item-warning">${escapeHtml(item.unscheduled_reason ?? `存在冲突：${item.conflict_state}`)}</p>` : '';
    return `<article class="draft-item" data-draft-item-id="${escapeHtml(item.id)}">
      <div><small>${escapeHtml(item.kind === 'fixed' ? '明确安排' : item.kind === 'scheduled' ? '目标行动' : '未排入')}</small><h3>${escapeHtml(item.title)}</h3></div>
      <time>${escapeHtml(interval)}</time>${instructions}${provenance}${adjustmentNote}${warning}
      ${item.editable ? `<div class="item-actions"><button type="button" data-action="edit-item" data-item-id="${escapeHtml(item.id)}">编辑</button><button type="button" data-action="delete-item" data-item-id="${escapeHtml(item.id)}">删除</button></div>` : ''}
    </article>`;
  }).join('');
  return `${windowNote}${clarifications ? `<aside class="clarifications"><strong>你补充的信息</strong><ul>${clarifications}</ul></aside>` : ''}${items}${assumptions ? `<aside class="assumptions"><strong>本次采用的假设</strong><ul>${assumptions}</ul></aside>` : ''}`;
}

export function calendarMarkup(range, events = []) {
  if (!range) return '<p class="calendar-empty">正在读取日历…</p>';
  const grouped = groupEventsByLocalDate(events);
  const start = new Date(range.start);
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    const key = localDateKey(day);
    const label = new Intl.DateTimeFormat('zh-CN', { weekday: 'short' }).format(day);
    const items = (grouped[key] ?? []).map(event => `<article class="calendar-event ${event.source === 'ai' ? 'ai-event' : ''}" data-event-id="${escapeHtml(event.id)}">
      <time>${escapeHtml(event.start_at.slice(11, 16))}–${escapeHtml(event.end_at.slice(11, 16))}</time>
      <strong>${escapeHtml(event.title)}</strong>
    </article>`).join('');
    return `<section class="calendar-day" data-date="${key}">
      <header><span>${escapeHtml(label)}</span><strong>${day.getDate()}</strong></header>
      <div class="calendar-events">${items}</div>
    </section>`;
  }).join('');
}
