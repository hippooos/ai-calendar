function pad(value) {
  return String(value).padStart(2, '0');
}

export function localDateKey(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function localIso(date) {
  const offset = -date.getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '-';
  return `${localDateKey(date)}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}${sign}${pad(Math.trunc(Math.abs(offset) / 60))}:${pad(Math.abs(offset) % 60)}`;
}

export function weekRange(anchor = new Date()) {
  const start = new Date(anchor);
  const weekday = start.getDay() || 7;
  start.setDate(start.getDate() - weekday + 1);
  start.setHours(0, 0, 0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  return { start: localIso(start), end: localIso(end) };
}

export function groupEventsByLocalDate(events = []) {
  return events.reduce((grouped, event) => {
    const key = String(event.start_at).slice(0, 10);
    (grouped[key] ??= []).push(event);
    return grouped;
  }, {});
}
