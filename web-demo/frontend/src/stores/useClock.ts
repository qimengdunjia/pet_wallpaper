import { onBeforeUnmount, onMounted, ref } from "vue";
import { systemState } from "./systemStore";

export function useClock() {
  const clockText = ref("");
  let timer: number | null = null;

  const refreshClock = () => {
    const now = new Date();
    clockText.value = now.toLocaleTimeString("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  };

  const syncFullscreen = () => {
    systemState.isFullscreen = Boolean(document.fullscreenElement);
  };

  onMounted(() => {
    refreshClock();
    timer = window.setInterval(refreshClock, 15000);
    document.addEventListener("fullscreenchange", syncFullscreen);
  });

  onBeforeUnmount(() => {
    if (timer !== null) window.clearInterval(timer);
    document.removeEventListener("fullscreenchange", syncFullscreen);
  });

  return clockText;
}
