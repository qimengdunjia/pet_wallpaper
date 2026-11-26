<!-- 文件用途：初始化网页 Demo，恢复档案与任务后按当前路由渲染页面。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from "vue";
import {
  fetchConfig,
  fetchCurrentWallpaper,
  fetchGenerations,
  fetchPets,
} from "@/lib/api";
import { preloadAssetVideosBackground, preloadTransitionVideos } from "@/lib/preload";
import {
  needsDecoration,
  readDecorationBatch,
  setDecorationBatch,
  startWaitingBatch,
  stopAllPolling,
  trackJob,
} from "@/stores/generationStore";
import {
  getFirstReadyPet,
  setDefaultWallpaper,
  setPets,
  setSavedWallpaper,
} from "@/stores/petStore";
import { setDisplayedWallpaper } from "@/stores/playerStore";
import { isWallpaperImmersive, setRoute, systemState } from "@/stores/systemStore";
import type { RouteView } from "@/types";
import CarBottomDock from "@/components/CarBottomDock.vue";
import DemoControlDrawer from "@/components/DemoControlDrawer.vue";
import SystemAlertOverlay from "@/components/SystemAlertOverlay.vue";
import SystemTopBar from "@/components/SystemTopBar.vue";
import HomeReturnView from "@/views/HomeReturnView.vue";
import LoadingTransitionView from "@/views/LoadingTransitionView.vue";
import OnboardingDecorationView from "@/views/OnboardingDecorationView.vue";
import OnboardingSpeciesView from "@/views/OnboardingSpeciesView.vue";
import OnboardingUploadView from "@/views/OnboardingUploadView.vue";
import SettingsView from "@/views/SettingsView.vue";
import WallpaperStageView from "@/views/WallpaperStageView.vue";
import WelcomeView from "@/views/WelcomeView.vue";

async function bootstrap() {
  try {
    const [config, pets, currentWallpaper, jobs] = await Promise.all([
      fetchConfig(),
      fetchPets(),
      fetchCurrentWallpaper(),
      fetchGenerations(),
    ]);
    systemState.config = config;
    preloadTransitionVideos([config.transitions?.intro?.url, config.transitions?.loop?.url]);
    setDefaultWallpaper(config.default_wallpaper ?? null);
    setPets(pets);
    setSavedWallpaper(currentWallpaper);

    // 档案和任务接口并行返回，按更新时间合并同一个任务的快照。
    const jobsById = new Map(jobs.map((job) => [job.id, job]));
    for (const { latest_job: latest } of pets) {
      if (!latest) continue;
      const cached = jobsById.get(latest.id);
      if (!cached || latest.updated_at > cached.updated_at) jobsById.set(latest.id, latest);
    }
    const activeJobs = [...jobsById.values()].filter((job) =>
      !needsDecoration(job) && (job.status === "queued" || job.status === "generating"),
    );
    const unfinishedPortraits = [...jobsById.values()].filter((job) =>
      needsDecoration(job) && pets.some((pet) => pet.latest_job_id === job.id),
    );
    for (const job of jobsById.values()) {
      trackJob(job);
    }

    const hashRoute = window.location.hash.replace(/^#\/?/, "").trim();
    const navigate = (route: Exclude<RouteView, "settings">) => {
      if (hashRoute === "settings") {
        setRoute("settings");
        systemState.settingsReturnRoute = route;
      } else {
        setRoute(route);
      }
    };

    const baseline = currentWallpaper ?? config.default_wallpaper;
    if (baseline) {
      setDisplayedWallpaper(baseline.pet_id, baseline.version_id, baseline.assets);
      preloadAssetVideosBackground(baseline.assets);
    }

    if (hashRoute === "onboarding-decoration") {
      const storedIds = readDecorationBatch();
      const recoverable = storedIds.length
        ? unfinishedPortraits.filter((job) => storedIds.includes(job.id))
        : unfinishedPortraits.slice(0, 2);
      if (recoverable.length) {
        setDecorationBatch(recoverable.map((job) => job.id));
        systemState.onboardingReturnRoute = baseline ? "wallpaper" : "welcome";
        navigate("onboarding-decoration");
        return;
      }
      const confirmed = activeJobs.filter((job) => storedIds.includes(job.id));
      if (confirmed.length) {
        startWaitingBatch(confirmed.map((job) => job.id));
        navigate("generating");
        return;
      }
    }
    if (currentWallpaper) {
      if (hashRoute === "home") {
        navigate("home");
      } else if ((hashRoute === "generating" || hashRoute === "settings") && activeJobs.length > 0) {
        startWaitingBatch(activeJobs.map((j) => j.id));
        navigate("generating");
      } else {
        navigate("wallpaper");
      }
    } else if (activeJobs.length > 0) {
      startWaitingBatch(activeJobs.map((j) => j.id));
      navigate("generating");
    } else if (config.default_wallpaper) {
      if (hashRoute === "welcome") {
        navigate("welcome");
      } else if (hashRoute === "home") {
        navigate("home");
      } else {
        navigate("wallpaper");
      }
    } else {
      const readyPet = getFirstReadyPet();
      if (readyPet && readyPet.active_assets && readyPet.active_version_id) {
        setDisplayedWallpaper(readyPet.id, readyPet.active_version_id, readyPet.active_assets);
        preloadAssetVideosBackground(readyPet.active_assets);
        navigate(hashRoute === "wallpaper" ? "wallpaper" : "home");
      } else {
        navigate("welcome");
      }
    }
  } catch (err) {
    systemState.bootstrapError =
      err instanceof Error ? err.message : "连接后端服务失败，请刷新重试";
  } finally {
    systemState.initialized = true;
  }
}

function handleHashChange() {
  const hash = window.location.hash.replace(/^#\/?/, "").trim();
  if (
    hash === "welcome" ||
    hash === "home" ||
    hash === "onboarding-species" ||
    hash === "onboarding-upload" ||
    hash === "onboarding-decoration" ||
    hash === "generating" ||
    hash === "wallpaper" ||
    hash === "settings"
  ) {
    setRoute(hash, { syncHash: false });
  }
}

const isImmersive = computed(() => isWallpaperImmersive());

onMounted(() => {
  window.addEventListener("hashchange", handleHashChange);
  void bootstrap();
});

onBeforeUnmount(() => {
  window.removeEventListener("hashchange", handleHashChange);
  stopAllPolling();
});
</script>

<template>
  <main class="app-shell">
    <SystemTopBar />

    <div
      v-if="systemState.toast && !isImmersive"
      class="toast-banner"
      :class="systemState.toast.type"
      data-testid="toast-banner"
    >
      {{ systemState.toast.text }}
    </div>

    <div v-if="!systemState.initialized" class="view-stage">
      <div class="cockpit-card" style="max-width: 440px; text-align: center">
        正在加载宠物档案与壁纸资源...
      </div>
    </div>

    <div v-else-if="systemState.bootstrapError" class="view-stage">
      <div class="cockpit-card" style="max-width: 480px; text-align: center">
        <h2>无法初始化 Demo</h2>
        <p style="color: var(--text-secondary)">{{ systemState.bootstrapError }}</p>
      </div>
    </div>

    <template v-else>
      <WelcomeView v-if="systemState.route === 'welcome'" />
      <HomeReturnView v-else-if="systemState.route === 'home'" />
      <OnboardingSpeciesView v-else-if="systemState.route === 'onboarding-species'" />
      <OnboardingUploadView v-else-if="systemState.route === 'onboarding-upload'" />
      <OnboardingDecorationView v-else-if="systemState.route === 'onboarding-decoration'" />
      <LoadingTransitionView v-else-if="systemState.route === 'generating'" />
      <WallpaperStageView v-else-if="systemState.route === 'wallpaper'" />
      <SettingsView v-else-if="systemState.route === 'settings'" />
    </template>

    <CarBottomDock />
    <DemoControlDrawer />
    <SystemAlertOverlay />
  </main>
</template>
