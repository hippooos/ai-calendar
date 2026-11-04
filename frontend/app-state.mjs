export function createInitialAppState() {
  return {
    overlay: 'none',
    requestStatus: 'idle',
    sessionId: null,
    planningStatus: null,
    questions: [],
    answers: {},
    draft: null,
    editingItemId: null,
    confirmationKey: null,
    confirmationResult: null,
    calendarRange: null,
    calendarEvents: [],
    error: null,
  };
}

export function applySession(state, session) {
  const overlay = session.status === 'needs_clarification'
    ? 'questions'
    : ['manual_required', 'unsupported', 'validation_failed'].includes(session.status)
      ? 'message'
      : state.overlay;
  return {
    ...state,
    overlay,
    requestStatus: 'idle',
    sessionId: session.id,
    planningStatus: session.status,
    questions: session.questions ?? [],
    error: session.status === 'validation_failed'
      ? { message: '草案未生成，也没有写入日历。请返回修改后重新生成。' }
      : null,
  };
}
