import { createApiClient } from './api-client.mjs';
import { localIso as isoLocal } from './date-utils.mjs';
import { escapeHtml } from './renderers.mjs';
import { attachMouseScrub } from './video-scrub.mjs';

const api = createApiClient();
const entryEvents = document.querySelector('#entry-events');
const homeCompose = document.querySelector('#home-compose');
const todayNumber = document.querySelector('#today-number');

if (todayNumber) {
  todayNumber.textContent = String(new Date().getDate()).padStart(2, '0');
}

function renderUpcoming(events) {
  if (!entryEvents) return;
  if (!events.length) {
    entryEvents.innerHTML = '<tr><td class="entry-empty" colspan="2">最近还没有日程</td></tr>';
    return;
  }
  const format = new Intl.DateTimeFormat('zh-CN', {
    month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  });
  entryEvents.innerHTML = events.map(event => {
    const start = new Date(event.start_at);
    return `<tr><td class="entry-time">${escapeHtml(format.format(start))}</td><td class="entry-title">${escapeHtml(event.title)}</td></tr>`;
  }).join('');
}

async function loadUpcoming() {
  const now = Date.now();
  try {
    const aheadStart = new Date();
    const aheadEnd = new Date(now + 7 * 86400000);
    const ahead = await api.getCalendarEvents(isoLocal(aheadStart), isoLocal(aheadEnd));
    const upcoming = ahead
      .filter(event => new Date(event.end_at).getTime() >= now)
      .sort((left, right) => new Date(left.start_at) - new Date(right.start_at))
      .slice(0, 5);

    if (upcoming.length) {
      renderUpcoming(upcoming);
      return;
    }

    const pastStart = new Date(now - 30 * 86400000);
    const past = await api.getCalendarEvents(isoLocal(pastStart), isoLocal(new Date(now)));
    const recent = past
      .sort((left, right) => new Date(right.start_at) - new Date(left.start_at))
      .slice(0, 5)
      .reverse();
    renderUpcoming(recent);
  } catch {
    renderUpcoming([]);
  }
}

/* 去主页面，并直接打开 AI 输入浮层 */
if (homeCompose) {
  homeCompose.addEventListener('click', () => {
    window.location.href = './app.html?compose=1';
  });
}

/* ============================================================
   背景视频：鼠标视线跟随
   素材是"人物左右看"的动画，鼠标水平位置 → 对应帧，
   人物看向方向即与鼠标方向对齐。
   背景不位移、不旋转、不播放，只逐帧定位。
   ============================================================ */
const bgVideo = document.querySelector('#bg-video');
attachMouseScrub(bgVideo);

void loadUpcoming();
