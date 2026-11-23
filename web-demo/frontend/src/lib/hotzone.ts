import type { HotzoneSlot } from "@/types";

export interface StageRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface HotzoneResult {
  slot: HotzoneSlot;
  ratioX: number;
}

/**
 * 根据 16:9 可见画布矩形计算点击命中的横向热区。
 * 边界规则（按 PRD 与开发文档）：
 * - [0, 34%) -> left
 * - [34%, 66%) -> center（34% 归中区）
 * - [66%, 100%] -> right（66% 归右区）
 * - 画布之外（留黑区）返回 null
 */
export function resolveHotzone(clientX: number, clientY: number, rect: StageRect): HotzoneResult | null {
  if (rect.width <= 0 || rect.height <= 0) {
    return null;
  }
  if (
    clientX < rect.left ||
    clientX > rect.left + rect.width ||
    clientY < rect.top ||
    clientY > rect.top + rect.height
  ) {
    return null;
  }
  const ratioX = (clientX - rect.left) / rect.width;
  if (ratioX < 0.34) {
    return { slot: "left", ratioX };
  }
  if (ratioX < 0.66) {
    return { slot: "center", ratioX };
  }
  return { slot: "right", ratioX };
}

export function hotzoneLabel(slot: HotzoneSlot): string {
  if (slot === "left") return "左热区";
  if (slot === "center") return "中热区";
  return "右热区";
}
