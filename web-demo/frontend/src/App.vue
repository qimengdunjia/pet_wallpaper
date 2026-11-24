<!-- 文件用途：初始化网页 Demo，恢复档案与任务后按当前路由渲染页面。 -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted } from "vue";
import {
  fetchConfig,
  fetchCurrentWallpaper,
  fetchGenerations,
  fetchPets,
} from "@/lib/api";
import { preloadAssetVideosBackground, preloadTransitionVideos } from "@/lib/preload";
import {
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
import { setRoute, systemState } from "@/stores/systemStore";
import CarBottomDock from "@/components/CarBottomDock.vue";
import DemoControlDrawer from "@/components/DemoControlDrawer.vue";
import SystemAlertOverlay from "@/components/SystemAlertOverlay.vue";
import SystemTopBar from "@/components/SystemTopBar.vue";
import HomeReturnView from "@/views/HomeReturnView.vue";
import LoadingTransitionView from "@/views/LoadingTransitionView.vue";
import OnboardingSpeciesView from "@/views/OnboardingSpeciesView.vue";
import OnboardingUploadView from "@/views/OnboardingUploadView.vue";
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
    const activeJobs = [...jobsById.values()].filter((j) => j.status === "queued" || j.status === "generating");
    for (const job of jobsById.values()) {
      trackJob(job);
    }

    const hashRoute = window.location.hash.replace(/^#\/?/, "").trim();

    if (currentWallpaper) {
      setDisplayedWallpaper(
        currentWallpaper.pet_id,
        currentWallpaper.version_id,
        currentWallpaper.assets,
      );
      preloadAssetVideosBackground(currentWallpaper.assets);
      if (hashRoute === "home") {
        setRoute("home");
      } else if (hashRoute === "generating" && activeJobs.length > 0) {
        startWaitingBatch(activeJobs.map((j) => j.id));
        setRoute("generating");
      } else {
        setRoute("wallpaper");
      }
    } else if (activeJobs.length > 0) {
      startWaitingBatch(activeJobs.map((j) => j.id));
      setRoute("generating");
    } else if (config.default_wallpaper) {
      const defWp = config.default_wallpaper;
      setDisplayedWallpaper(defWp.pet_id, defWp.version_id, defWp.assets);
      preloadAssetVideosBackground(defWp.assets);
      if (hashRoute === "welcome") {
        setRoute("welcome");
      } else if (hashRoute === "home") {
        setRoute("home");
      } else {
        setRoute("wallpaper");
      }
    } else {
      const readyPet = getFirstReadyPet();
      if (readyPet && readyPet.active_assets && readyPet.active_version_id) {
        setDisplayedWallpaper(readyPet.id, readyPet.active_version_id, readyPet.active_assets);
        preloadAssetVideosBackground(readyPet.active_assets);
        setRoute(hashRoute === "wallpaper" ? "wallpaper" : "home");
      } else {
        setRoute("welcome");
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
    hash === "generating" ||
    hash === "wallpaper"
  ) {
    setRoute(hash, { syncHash: false });
  }
}

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

    <div v-if="systemState.toast" class="toast-banner" :class="systemState.toast.type" data-testid="toast-banner">
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
      <LoadingTransitionView v-else-if="systemState.route === 'generating'" />
      <WallpaperStageView v-else-if="systemState.route === 'wallpaper'" />
    </template>

    <CarBottomDock />
    <DemoControlDrawer />
    <SystemAlertOverlay />
  </main>
</template>
