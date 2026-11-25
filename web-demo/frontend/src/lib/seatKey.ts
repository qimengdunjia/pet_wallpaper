// 文件用途：从 Agent-IMU 固件的 WebSocket 文本帧识别一次性按键和触摸事件。
import type { HotzoneSlot } from "@/types";

function numberField(value: unknown): number | null {
  if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

/** 为一条设备连接建立解码器；传入固件文本帧，返回新触发的热区或 null。 */
export function createSeatKeyDecoder() {
  let lastTime: number | null = null;
  let feed: number | null = null; // 宠物界面物理短按累计值，首帧只建立基线。
  let button: number | null = null; // 旧固件仅提供 btn 电平。
  let press: number | null = null;
  let release: number | null = null;
  let stroke: {
    start: number; x: number; y: number; lastX: number; lastY: number; length: number;
  } | null = null;

  return (raw: string): HotzoneSlot | null => {
    let frame;
    try {
      frame = JSON.parse(raw);
    } catch {
      return null;
    }
    if (!frame || typeof frame !== "object" || Array.isArray(frame)) return null;
    const time = numberField(frame.t);
    if (time === null || time < 0 || lastTime === time) return null;
    if (lastTime !== null && time < lastTime) {
      // 设备重启或计时器回绕，丢弃旧手势，重新同步计数。
      feed = button = press = release = null;
      stroke = null;
    }
    lastTime = time;

    let action: HotzoneSlot | null = null;
    const nextFeed = numberField(frame.feed);
    if (nextFeed !== null) {
      if (feed !== null && nextFeed > feed) action = "center";
      feed = nextFeed;
    }
    const down = numberField(frame.btn);
    if (down !== null) {
      if (feed === null && button === 0 && down !== 0) action = "center";
      button = down;
    }

    const pn = numberField(frame.pn);
    const rn = numberField(frame.rn);
    const pd = numberField(frame.pd);
    const x = numberField(frame.px);
    const y = numberField(frame.py);
    if (pn === null || rn === null || pd === null || x === null || y === null) return action;

    if (press !== null && pn !== press) {
      stroke = { start: time, x, y, lastX: x, lastY: y, length: 0 };
    }
    if (stroke && pd) {
      const step = Math.hypot(x - stroke.lastX, y - stroke.lastY);
      if (step >= 2) {
        stroke.length += step;
        stroke.lastX = x;
        stroke.lastY = y;
      }
    }
    if (release !== null && rn !== release && stroke) {
      // 与安卓项目一致，轨迹只采按住时的点，松手帧的坐标可能已归零。
      const dx = stroke.lastX - stroke.x;
      const dy = stroke.lastY - stroke.y;
      const distance = Math.hypot(dx, dy);
      if (time - stroke.start <= 250 && distance <= 10 && stroke.length <= 10) {
        action ??= "center";
      } else if (distance >= 24 && Math.abs(dx) >= 2 * Math.abs(dy) && distance >= 0.85 * stroke.length) {
        action ??= dx < 0 ? "left" : "right";
      }
      stroke = null;
    }
    press = pn;
    release = rn;
    return action;
  };
}
