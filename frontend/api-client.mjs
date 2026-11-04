export class ApiError extends Error {
  constructor(status, payload = {}) {
    super(payload.message ?? `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.errorCode = payload.error_code ?? 'HTTP_ERROR';
    this.retryable = Boolean(payload.retryable);
    this.requestId = payload.request_id ?? null;
  }
}

export function createApiClient({
  fetchImpl = fetch,
  getAccessCode = () => globalThis.sessionStorage?.getItem('accessCode'),
} = {}) {
  async function request(path, init = {}) {
    const headers = new Headers(init.headers);
    if (init.body !== undefined) headers.set('Content-Type', 'application/json');
    const accessCode = getAccessCode?.();
    if (accessCode) headers.set('X-Access-Code', accessCode);
    const response = await fetchImpl(path, { ...init, headers });
    if (!response.ok) {
      let payload = {};
      try { payload = await response.json(); } catch { payload = {}; }
      throw new ApiError(response.status, payload);
    }
    return response.status === 204 ? null : response.json();
  }

  return {
    createPlanningSession: (rawInput, referenceNow) => request('/api/planning/sessions', {
      method: 'POST',
      body: JSON.stringify({ raw_input: rawInput, reference_now: referenceNow }),
    }),
    submitAnswers: (sessionId, answers) => request(`/api/planning/sessions/${encodeURIComponent(sessionId)}/answers`, {
      method: 'POST',
      body: JSON.stringify({ answers }),
    }),
    generateDraft: sessionId => request(`/api/planning/sessions/${encodeURIComponent(sessionId)}/generate-draft`, {
      method: 'POST',
    }),
    getDraft: draftId => request(`/api/drafts/${encodeURIComponent(draftId)}`),
    updateDraftItem: (draftId, itemId, payload) => request(`/api/drafts/${encodeURIComponent(draftId)}/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
    deleteDraftItem: (draftId, itemId) => request(`/api/drafts/${encodeURIComponent(draftId)}/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    }),
    confirmDraft: (draftId, idempotencyKey) => request(`/api/drafts/${encodeURIComponent(draftId)}/confirm`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
    }),
    getCalendarEvents: (start, end) => request(`/api/calendar/events?${new URLSearchParams({ start, end })}`),
  };
}
