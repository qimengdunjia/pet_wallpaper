// 文件用途：管理 Demo 导航、驾驶状态、演示配置和提示。
import { reactive } from "vue";
import type { AppConfig, DrivingMode, RouteView } from "@/types";

export type MockPreset = "fast" | "over10s" | "staggered" | "fail";
export type CutoutStrategy = "after_first_round" | "immediate";

export interface ToastMessage {
  id: number;
  type: "info" | "success" | "warning" | "error";
  text: string;
}

const VALID_ROUTES = new Set<RouteView>([
  "welcome",
  "home",
  "onboarding-species",
  "onboarding-upload",
  "generating",
  "wallpaper",
]);

function readRouteFromHash(): RouteView {
  if (typeof window === "undefined") return "welcome";
  const raw = window.location.hash.replace(/^#\/?/, "").trim() as RouteView;
  return VALID_ROUTES.has(raw) ? raw : "welcome";
}

export const systemState = reactive({
  route: readRouteFromHash() as RouteView,
  // 用于让离开页面前发出的异步操作失效，即使用户又回到同一页面。
  routeRevision: 0,
  drivingMode: "parked" as DrivingMode,
  alertVisible: false,
  alertTitle: "驾驶安全提醒",
  alertMessage: "前方路况变化，请注意驾驶安全，已暂停壁纸互动动作。",
  toast: null as ToastMessage | null,
  drawerOpen: false,
  showHotzoneGuides: false,
  mockPreset: "fast" as MockPreset,
  cutoutStrategy: "after_first_round" as CutoutStrategy,
  simulateNextSwitchFailure: false,
  isFullscreen: false,
  config: null as AppConfig | null,
  onboardingSpeciesMode: null as "cat" | "dog" | "both" | null,
  onboardingReturnRoute: "welcome" as "welcome" | "home" | "wallpaper",
  initialized: false,
  bootstrapError: null as string | null,
});

let toastTimer: number | null = null;
let toastSeq = 0;

/** 切换到 view，按 syncHash 同步浏览器地址，并更新实际导航的版本号。 */
export function setRoute(view: RouteView, options?: { syncHash?: boolean }) {
  if (systemState.route !== view) {
    systemState.routeRevision += 1;
    systemState.route = view;
  }
  if (options?.syncHash !== false && typeof window !== "undefined") {
    const targetHash = `#/${view}`;
    if (window.location.hash !== targetHash) {
      window.location.hash = targetHash;
    }
  }
}

export function showToast(
  text: string,
  type: ToastMessage["type"] = "info",
  durationMs = 3600,
) {
  toastSeq += 1;
  const id = toastSeq;
  systemState.toast = { id, type, text };
  if (typeof window !== "undefined") {
    if (toastTimer !== null) {
      window.clearTimeout(toastTimer);
    }
    toastTimer = window.setTimeout(() => {
      if (systemState.toast?.id === id) {
        systemState.toast = null;
      }
    }, durationMs);
  }
}

export function clearToast() {
  systemState.toast = null;
}

export function setDrivingMode(mode: DrivingMode) {
  systemState.drivingMode = mode;
  if (mode === "driving") {
    showToast("已切换至「车辆行驶中」，画布互动、上传与切换操作已受限", "warning", 3200);
  } else {
    showToast("已切换至「演示停车」，全部互动与宠物管理功能已开放", "success", 2600);
  }
}

export function guardParkedAction(actionLabel: string): boolean {
  if (systemState.drivingMode === "driving") {
    showToast(`车辆行驶中禁止${actionLabel}，请先切至「演示停车」状态`, "warning", 3600);
    return false;
  }
  return true;
}

export function triggerSafetyAlert(title = "行车安全优先提醒", message = "检测到系统优先驾驶提醒，已立即中断当前动作播放。") {
  systemState.alertTitle = title;
  systemState.alertMessage = message;
  systemState.alertVisible = true;
}

export function dismissSafetyAlert() {
  systemState.alertVisible = false;
}

export function resetSystemState() {
  setRoute("welcome", { syncHash: false });
  systemState.drivingMode = "parked";
  systemState.alertVisible = false;
  systemState.toast = null;
  systemState.drawerOpen = false;
  systemState.showHotzoneGuides = false;
  systemState.mockPreset = "fast";
  systemState.cutoutStrategy = "after_first_round";
  systemState.simulateNextSwitchFailure = false;
  systemState.isFullscreen = false;
  systemState.config = null;
  systemState.onboardingSpeciesMode = null;
  systemState.onboardingReturnRoute = "welcome";
  systemState.initialized = false;
  systemState.bootstrapError = null;
}
