/**
 * 鼠标视线跟随 —— 把鼠标方向映射到视频时间轴。
 *
 * 素材 hero_eyes_circle_smooth_10s.mp4 是"眼睛沿圆周平滑扫视"的动画，
 * 10 秒正好转完一整圈，每个时刻对应一个注视方向。
 * 这里把鼠标相对屏幕中心的方向角（0~2π）映射到时间轴（0~duration），
 * 鼠标指向哪个方位，人物视线就看向哪个方位。
 *
 * 响应策略（为什么不灵敏）：
 * 早期用"固定间隔 + setTimeout 排队重试"，鼠标动完还要等一个间隔才换帧，
 * 期间的目标还会积压排队，表现为明显迟滞。
 * 现在改成 rAF 驱动：mousemove 只记下最新目标，每帧检查，
 * 上一次 seek 一完成就立刻追到最新位置 —— 不排队、不等候。
 *
 * phase：相位偏移（单位：圈）。素材 0 秒方向与鼠标方位对不上时整体校正
 *       （差 90° 设 0.25，差 180° 设 0.5）。
 * epsilon：小于这个秒数的变化就跳过，避免为肉眼不可见的位移白白解码。
 */
export function attachMouseScrub(video, { minInterval = 0, phase = 0, epsilon = 0.008 } = {}) {
  if (!video) return;

  /* 定格，不做连续播放；画面切换完全由 seek 控制 */
  video.pause();

  const hasDuration = () => Number.isFinite(video.duration) && video.duration > 0;

  let seeking = false;
  let pendingTime = null;
  let lastSeekAt = 0;

  /* rAF 泵：每帧尝试追到最新目标 */
  function pump() {
    requestAnimationFrame(pump);
    if (!hasDuration() || seeking) return;
    if (pendingTime === null) return;

    const now = performance.now();
    if (now - lastSeekAt < minInterval) return;

    if (Math.abs(pendingTime - video.currentTime) < epsilon) {
      pendingTime = null;
      return;
    }

    const time = pendingTime;
    pendingTime = null;
    seeking = true;
    lastSeekAt = now;
    video.currentTime = time;
  }
  requestAnimationFrame(pump);

  /* seek 完成的瞬间，下一帧 pump 会立刻追到最新目标 */
  video.addEventListener('seeked', () => {
    seeking = false;
  });

  window.addEventListener('mousemove', event => {
    if (!hasDuration()) return;

    /* 只更新目标，不做任何节流 —— 开销极小。
       必须按各自半宽/半高分别归一化：若直接用像素差算 atan2，
       宽屏会把垂直方向压扁（右上角只有约 -29° 而非 -45°），
       上下方向的转动幅度会明显偏小。 */
    const nx = (event.clientX / window.innerWidth - 0.5) * 2;
    const ny = (event.clientY / window.innerHeight - 0.5) * 2;
    const angle = Math.atan2(ny, nx);
    const ratio = (angle + Math.PI) / (2 * Math.PI);
    pendingTime = ((ratio + phase + 1) % 1) * video.duration;
  });

  /* 初始停在正中一帧 */
  const seekInitial = () => {
    if (!hasDuration()) return;
    pendingTime = video.duration * 0.5;
  };
  if (video.readyState >= 1) seekInitial();
  else video.addEventListener('loadedmetadata', seekInitial);
}
