import { describe, expect, it } from "vitest";
import { resolveHotzone } from "@/lib/hotzone";

describe("resolveHotzone", () => {
  const rect = { left: 100, top: 50, width: 1000, height: 562.5 };

  it("maps 0% to <34% into left hotzone", () => {
    expect(resolveHotzone(100, 200, rect)?.slot).toBe("left");
    expect(resolveHotzone(270, 200, rect)?.slot).toBe("left");
    expect(resolveHotzone(439.9, 200, rect)?.slot).toBe("left");
  });

  it("maps exact 34% boundary and 34%~<66% into center hotzone", () => {
    expect(resolveHotzone(100 + 1000 * 0.34, 200, rect)?.slot).toBe("center");
    expect(resolveHotzone(100 + 1000 * 0.5, 200, rect)?.slot).toBe("center");
    expect(resolveHotzone(100 + 1000 * 0.6599, 200, rect)?.slot).toBe("center");
  });

  it("maps exact 66% boundary and 66%~100% into right hotzone", () => {
    expect(resolveHotzone(100 + 1000 * 0.66, 200, rect)?.slot).toBe("right");
    expect(resolveHotzone(100 + 1000 * 0.83, 200, rect)?.slot).toBe("right");
    expect(resolveHotzone(1100, 200, rect)?.slot).toBe("right");
  });

  it("returns null outside the visible 16:9 canvas (letterbox black bars)", () => {
    expect(resolveHotzone(99, 200, rect)).toBeNull();
    expect(resolveHotzone(1101, 200, rect)).toBeNull();
    expect(resolveHotzone(500, 49, rect)).toBeNull();
    expect(resolveHotzone(500, 613, rect)).toBeNull();
  });
});
