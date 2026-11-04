export function createInitialState() {
  return {
    screen: 'calendar',
    overlay: 'none',
    draftStatus: '未生成',
    writeStatus: '未写入',
    lastAction: '等待用户输入'
  };
}

export function transition(state, action) {
  switch (action.type) {
    case 'OPEN_AI_FLOW':
      return { ...state, overlay: 'input', lastAction: '打开 AI 安排流程' };
    case 'GENERATE':
      return action.missingCriticalInfo
        ? { ...state, overlay: 'questions', lastAction: '已汇总关键追问' }
        : { ...state, overlay: 'draft', draftStatus: '待确认', lastAction: '已生成整组草案' };
    case 'SUBMIT_QUESTIONS':
      return { ...state, overlay: 'draft', draftStatus: '待确认', lastAction: '信息完整，已生成整组草案' };
    case 'RETURN_TO_INPUT':
      return { ...state, overlay: 'input', lastAction: '返回补充输入' };
    case 'CONFIRM_DRAFT':
      return { ...state, screen: 'calendar', overlay: 'none', draftStatus: '已确认', writeStatus: '已写入 AI 日历', lastAction: '整组草案已写入 AI 日历' };
    case 'DELETE_AI_EVENT':
      return { ...state, lastAction: '已删除 1 条 AI 日程' };
    case 'EDIT_AI_EVENT':
      return { ...state, lastAction: '正在编辑 1 条 AI 日程' };
    case 'OPEN_CALENDAR':
      return { ...state, screen: 'calendar', overlay: 'none', lastAction: '查看 AI 日历' };
    default:
      return state;
  }
}
