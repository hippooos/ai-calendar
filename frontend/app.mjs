import { createApiClient } from './api-client.mjs';
import { applySession, createInitialAppState } from './app-state.mjs';
import { calendarMarkup, draftMarkup, questionsMarkup } from './renderers.mjs';
import { weekRange } from './date-utils.mjs';
import { resolveQuestionAnswer } from './question-answers.mjs';
import { attachMouseScrub } from './video-scrub.mjs';

const api = createApiClient();
let state = createInitialAppState();
let calendarAnchor = new Date();
let pendingRetry = null;

const flow = document.querySelector('#flow');
const sheets = {
  input: document.querySelector('#input-sheet'),
  questions: document.querySelector('#questions-sheet'),
  draft: document.querySelector('#draft-sheet'),
  message: document.querySelector('#message-sheet'),
  edit: document.querySelector('#edit-sheet'),
  delete: document.querySelector('#delete-sheet'),
  access: document.querySelector('#access-sheet'),
};
const note = document.querySelector('#state-note');
const generateButton = document.querySelector('#generate-button');
const inputError = document.querySelector('#input-error');
const questionsError = document.querySelector('#questions-error');
const draftError = document.querySelector('#draft-error');
const questionsSubmit = document.querySelector('#questions-submit');
const questionsList = document.querySelector('#questions-list');
const draftList = document.querySelector('#draft-list');
const editError = document.querySelector('#edit-error');
const confirmButton = document.querySelector('#confirm-button');
const calendarGrid = document.querySelector('#calendar-grid');
const toast = document.querySelector('#toast');


function render() {
  flow.classList.toggle('visible', state.overlay !== 'none');
  for (const [name, sheet] of Object.entries(sheets)) sheet.hidden = state.overlay !== name;
  generateButton.disabled = state.requestStatus === 'submitting';
  generateButton.textContent = state.requestStatus === 'submitting' ? '正在理解…' : '生成计划';
  questionsSubmit.disabled = state.requestStatus === 'submitting';
  questionsSubmit.textContent = state.requestStatus === 'submitting' ? '正在生成…' : '生成草案';
  note.textContent = state.requestStatus === 'submitting'
    ? (state.overlay === 'questions' ? '正在生成草案' : '正在创建规划会话')
    : `规划状态：${state.planningStatus ?? '未开始'}`;
  for (const element of [inputError, questionsError, draftError]) element.hidden = true;
  const activeError = state.overlay === 'questions'
    ? questionsError
    : state.overlay === 'draft' ? draftError : inputError;
  activeError.hidden = !state.error;
  activeError.textContent = state.error?.message ?? '';
  questionsList.innerHTML = questionsMarkup(state.questions);
  draftList.innerHTML = draftMarkup(state.draft);
  calendarGrid.innerHTML = calendarMarkup(state.calendarRange, state.calendarEvents);
  if (state.calendarRange) {
    const start = new Date(state.calendarRange.start);
    const end = new Date(state.calendarRange.end);
    end.setDate(end.getDate() - 1);
    document.querySelector('#week-title').textContent = `${start.getMonth() + 1}月${start.getDate()}日 – ${end.getMonth() + 1}月${end.getDate()}日`;
  }
  confirmButton.disabled = state.requestStatus === 'confirming';
  confirmButton.textContent = state.requestStatus === 'confirming' ? '正在写入…' : '整组确认并写入';
  if (state.overlay === 'message') {
    const confirmed = state.planningStatus === 'confirmed';
    const validationFailed = state.planningStatus === 'validation_failed' || state.planningStatus === 'draft_failed';
    document.querySelector('#message-title').textContent = confirmed ? '已经写入日历' : validationFailed ? '草案生成失败' : state.planningStatus === 'manual_required' ? '需要人工判断' : '暂不支持自动处理';
    document.querySelector('#message-body').textContent = confirmed
      ? `已写入 ${state.confirmationResult?.event_ids?.length ?? 0} 条日程，下一步将读取日历核对。`
      : validationFailed
        ? '草案未生成，也没有写入日历。请返回修改后重新生成。'
      : state.planningStatus === 'manual_required'
        ? '这项内容涉及安全边界，请先咨询合适的专业人士。'
        : '当前版本暂时不能自动完成这类操作。';
  }
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 2500);
}



async function loadCalendar(anchor = calendarAnchor) {
  calendarAnchor = new Date(anchor);
  const range = weekRange(calendarAnchor);
  try {
    const events = await api.getCalendarEvents(range.start, range.end);
    state = { ...state, calendarRange: range, calendarEvents: events, error: null };
  } catch (error) {
    if (error.status === 401) {
      pendingRetry = () => loadCalendar(calendarAnchor);
      state = { ...state, overlay: 'access', error: null };
    } else {
      state = { ...state, error };
    }
  }
  render();
}

function saveAccessCode() {
  const input = document.querySelector('#access-code');
  const accessError = document.querySelector('#access-error');
  if (!input.value) {
    accessError.hidden = false;
    accessError.textContent = '请输入访问码';
    return;
  }
  sessionStorage.setItem('accessCode', input.value);
  input.value = '';
  accessError.hidden = true;
  state = { ...state, overlay: 'none' };
  const retry = pendingRetry;
  pendingRetry = null;
  render();
  if (retry) void retry();
}

function localParts(value) {
  const date = new Date(value);
  const pad = number => String(number).padStart(2, '0');
  return {
    date: `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    time: `${pad(date.getHours())}:${pad(date.getMinutes())}`,
  };
}

function localIso(dateValue, timeValue) {
  const local = new Date(`${dateValue}T${timeValue}:00`);
  const offset = -local.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  const pad = number => String(Math.abs(number)).padStart(2, '0');
  return `${dateValue}T${timeValue}:00${sign}${pad(Math.trunc(offset / 60))}:${pad(offset % 60)}`;
}

function openEdit(itemId) {
  const item = state.draft.items.find(candidate => candidate.id === itemId);
  if (!item?.start_at || !item?.end_at) return;
  const start = localParts(item.start_at);
  const end = localParts(item.end_at);
  state = { ...state, overlay: 'edit', editingItemId: itemId, error: null };
  render();
  document.querySelector('#edit-title').value = item.title;
  document.querySelector('#edit-date').value = start.date;
  document.querySelector('#edit-start').value = start.time;
  document.querySelector('#edit-end').value = end.time;
  editError.hidden = true;
}

async function saveEdit() {
  const title = document.querySelector('#edit-title').value.trim();
  const date = document.querySelector('#edit-date').value;
  const start = document.querySelector('#edit-start').value;
  const end = document.querySelector('#edit-end').value;
  if (!title || !date || !start || !end) {
    editError.hidden = false;
    editError.textContent = '请填写完整的标题和时间';
    return;
  }
  try {
    const draft = await api.updateDraftItem(state.draft.id, state.editingItemId, {
      title,
      start_at: localIso(date, start),
      end_at: localIso(date, end),
    });
    state = { ...state, draft, overlay: 'draft', editingItemId: null, error: null };
  } catch (error) {
    editError.hidden = false;
    editError.textContent = error.message;
    return;
  }
  render();
}

function openDelete(itemId) {
  const item = state.draft.items.find(candidate => candidate.id === itemId);
  state = { ...state, overlay: 'delete', editingItemId: itemId };
  render();
  document.querySelector('#delete-title').textContent = item?.title ?? '这条安排';
}

async function confirmDelete() {
  try {
    await api.deleteDraftItem(state.draft.id, state.editingItemId);
    const draft = await api.getDraft(state.draft.id);
    state = { ...state, draft, overlay: 'draft', editingItemId: null, error: null };
  } catch (error) {
    state = { ...state, overlay: 'draft', editingItemId: null, error };
  }
  render();
}

async function confirmDraft() {
  state = { ...state, requestStatus: 'confirming', error: null };
  render();
  try {
    const result = await api.confirmDraft(state.draft.id, state.confirmationKey);
    state = { ...state, requestStatus: 'idle', planningStatus: 'confirmed', confirmationResult: result };
    await loadCalendar(calendarAnchor);
    state = { ...state, overlay: 'none' };
    showToast(`已写入并显示 ${result.event_ids.length} 条日程`);
  } catch (error) {
    state = { ...state, requestStatus: 'failed', error, overlay: 'draft' };
  }
  render();
}

async function buildDraft(sessionId) {
  state = { ...state, requestStatus: 'submitting', error: null };
  render();
  try {
    const created = await api.generateDraft(sessionId);
    const draft = await api.getDraft(created.id);
    state = { ...state, requestStatus: 'idle', planningStatus: 'draft_ready', draft, overlay: 'draft', confirmationKey: crypto.randomUUID() };
  } catch (error) {
    state = { ...state, requestStatus: 'failed', planningStatus: 'draft_failed', error, overlay: 'message' };
  }
  render();
}

function collectAnswers() {
  const answers = {};
  let valid = true;
  for (const card of questionsList.querySelectorAll('[data-question-id]')) {
    const questionId = card.dataset.questionId;
    const selected = card.querySelector(`input[type="radio"][name="${CSS.escape(questionId)}"]:checked`);
    const text = card.querySelector(`input[type="text"][name="${CSS.escape(questionId)}"]`);
    const custom = card.querySelector(`[data-custom-for="${CSS.escape(questionId)}"]`);
    const value = resolveQuestionAnswer({
      selectedValue: selected?.value,
      customValue: custom?.value,
      freeTextValue: text?.value,
    });
    const error = card.querySelector('.question-error');
    error.hidden = Boolean(value);
    if (!value) valid = false;
    else answers[questionId] = value;
  }
  return valid ? answers : null;
}

async function submitQuestionAnswers() {
  const answers = collectAnswers();
  if (!answers) return;
  state = { ...state, requestStatus: 'submitting', error: null };
  render();
  try {
    const session = await api.submitAnswers(state.sessionId, answers);
    state = applySession(state, session);
    if (session.status === 'a_ready') return await buildDraft(session.id);
  } catch (error) {
    state = { ...state, requestStatus: 'failed', error, overlay: 'questions' };
  }
  render();
}

async function createPlanning() {
  const rawInput = document.querySelector('#planning-input').value.trim();
  if (!rawInput) {
    state = { ...state, error: { message: '请先输入想安排的内容' } };
    return render();
  }
  state = { ...state, requestStatus: 'submitting', error: null };
  render();
  try {
    const session = await api.createPlanningSession(rawInput, new Date().toISOString());
    state = applySession(state, session);
    if (session.status === 'a_ready') {
      return await buildDraft(session.id);
    }
  } catch (error) {
    state = { ...state, requestStatus: 'failed', error, overlay: 'input' };
  }
  render();
}

document.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  const calendarButton = event.target.closest('[data-calendar-action]');
  if (calendarButton) {
    const action = calendarButton.dataset.calendarAction;
    if (action === 'today') calendarAnchor = new Date();
    else calendarAnchor.setDate(calendarAnchor.getDate() + (action === 'next' ? 7 : -7));
    void loadCalendar(calendarAnchor);
    return;
  }
  if (!button) return;
  const action = button.dataset.action;
  if (action === 'open') state = { ...state, overlay: 'input', error: null };
  if (action === 'close') state = { ...state, overlay: 'none', error: null };
  if (action === 'back') state = { ...state, overlay: 'input', error: null };
  if (action === 'generate') void createPlanning();
  if (action === 'questions') return void submitQuestionAnswers();
  if (action === 'edit-item') return openEdit(button.dataset.itemId);
  if (action === 'delete-item') return openDelete(button.dataset.itemId);
  if (action === 'cancel-edit' || action === 'cancel-delete') state = { ...state, overlay: 'draft', editingItemId: null };
  if (action === 'save-edit') void saveEdit();
  if (action === 'confirm-delete') void confirmDelete();
  if (action === 'confirm') void confirmDraft();
  if (action === 'save-access') saveAccessCode();
  render();
});

document.addEventListener('input', event => {
  const questionId = event.target.dataset?.customFor;
  if (!questionId || !event.target.value.trim()) return;
  const card = event.target.closest('[data-question-id]');
  const customRadio = card?.querySelector(`input[type="radio"][name="${CSS.escape(questionId)}"][value="__custom__"]`);
  if (customRadio) customRadio.checked = true;
});

document.querySelector('#today-number').textContent = String(new Date().getDate()).padStart(2, '0');
render();
void loadCalendar(calendarAnchor);

/* ---------- 背景视频：鼠标视线跟随 ---------- */
/* 鼠标水平位置映射到对应帧，人物看向与鼠标方向对齐；背景不做位移/旋转。 */
const bgVideo = document.querySelector('#bg-video');
attachMouseScrub(bgVideo);

/* 从入口页带 ?compose=1 跳进来时，直接打开 AI 输入浮层 */
if (new URLSearchParams(window.location.search).has('compose')) {
  state = { ...state, overlay: 'input' };
  render();
}
