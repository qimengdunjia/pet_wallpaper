// 文件用途：用固件协议帧验证按键基线、计数去重、触摸方向与重新连接。
import { describe, expect, it } from "vitest";
import { createSeatKeyDecoder } from "@/lib/seatKey";

describe("Agent-IMU", () => {
  it("同步累积值，丢弃重复帧及设备重启之前的状态", () => {
    const read = createSeatKeyDecoder();
    expect(read('{"t":100,"feed":2,"btn":1}')).toBeNull();
    expect(read('{"t":120,"feed":2,"btn":0}')).toBeNull();
    expect(read('{"t":140,"feed":2,"btn":1}')).toBeNull();
    expect(read('{"t":160,"feed":3,"btn":0}')).toBe("center");
    expect(read('{"t":160,"feed":3}')).toBeNull();
    expect(read('{"t":1,"feed":0,"btn":1}')).toBeNull();
    expect(read('{"t":21,"feed":1}')).toBe("center");
  });
  it("仅有 btn 时，每次按下只触发一次", () => {
    const read = createSeatKeyDecoder();
    expect(["bad", "null", "[]", "{}", '{"t":1,"btn":1}', '{"t":2,"btn":0}'].map(read)).toEqual(Array(6).fill(null));
    expect(read('{"t":3,"btn":"1"}')).toBe("center");
    expect(read('{"t":4,"btn":1}')).toBeNull();
    expect(read('{"t":5,"btn":0}')).toBeNull();
  });
  it.each([
    [40, 83, 100, "right"], [40, 12, 100, "left"], [40, 41, 100, "center"],
    [40, 41, 400, null], [40, 54, 100, null],
  ])("触摸轨迹从 %i 到 %i，耗时 %i 毫秒，得到 %s", (x, end, ms, expected) => {
    const read = createSeatKeyDecoder();
    const frame = (t: number, px: number, pd: number, pn: number, rn: number) =>
      JSON.stringify({ t, px, py: 20, pd, pn, rn, feed: 0 });
    expect(read(frame(1, 0, 0, 5, 5))).toBeNull();
    expect(read(frame(50, Number(x), 1, 6, 5))).toBeNull();
    expect(read(frame(70, Number(end), 1, 6, 5))).toBeNull();
    expect(read(frame(50 + Number(ms), 0, 0, 6, 6))).toBe(expected);
    expect(read(frame(500, 0, 0, 6, 6))).toBeNull();
  });
  it("同帧内按下松开可以轻点，首次连接时已按住的手势不能触发", () => {
    const read = createSeatKeyDecoder();
    const frame = (t: number, pd: number, pn: number, rn: number) =>
      JSON.stringify({ t, px: 20, py: 20, pd, pn, rn });
    expect(read(frame(1, 1, 7, 6))).toBeNull();
    expect(read(frame(20, 0, 7, 7))).toBeNull();
    expect(read(frame(40, 0, 8, 8))).toBe("center");
  });
});
