<script setup>
import DefaultTheme from "vitepress/theme";
import { ref, computed, onMounted, watch } from "vue";
import { useRoute, useData } from "vitepress";

const route = useRoute();
const { frontmatter } = useData();

const STORAGE_KEY_AUTO_DISABLED = "cbnv_serious_auto_disabled";
const STORAGE_KEY_MANUAL = "cbnv_serious_manual";

const isSeriousMode = ref(false);
const showToast = ref(false);
const toastMessage = ref("");
const hasUndoAction = ref(false);
let toastTimer = null;
let previousPathWasHome = true;

const isHome = computed(() => {
  return (
    route.path === "/" ||
    route.path === "/index.html" ||
    frontmatter.value?.layout === "home"
  );
});

function applyMode(serious) {
  isSeriousMode.value = serious;
  if (typeof document !== "undefined") {
    if (serious) {
      document.documentElement.classList.add("serious-mode");
    } else {
      document.documentElement.classList.remove("serious-mode");
    }
  }
}

function triggerToast(message, showUndo = false, duration = 6500) {
  toastMessage.value = message;
  hasUndoAction.value = showUndo;
  showToast.value = true;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    showToast.value = false;
  }, duration);
}

function evaluateRouteMode(isUserNavigation = false) {
  if (typeof window === "undefined") return;
  const manual = localStorage.getItem(STORAGE_KEY_MANUAL);
  const autoDisabled =
    localStorage.getItem(STORAGE_KEY_AUTO_DISABLED) === "true";

  if (manual === "on") {
    applyMode(true);
    previousPathWasHome = isHome.value;
    return;
  }
  if (manual === "off") {
    applyMode(false);
    previousPathWasHome = isHome.value;
    return;
  }

  // 自动路由联动模式：支持双向过渡
  if (isHome.value) {
    // 官网部分：默认启用质感主题与动效
    const wasSerious = isSeriousMode.value;
    applyMode(false);
    // 从文档部分返回官网首页时，触发向质感模式过渡的反馈
    if (isUserNavigation && !previousPathWasHome && wasSerious) {
      triggerToast("已回到官网首页，为您恢复全效质感呈现。", false, 4500);
    }
    previousPathWasHome = true;
  } else {
    // 文档部分：自动进入极简克制的简约模式（若未撤销）
    const previousWasHome = previousPathWasHome;
    previousPathWasHome = false;
    if (!autoDisabled) {
      applyMode(true);
      // 若当前从官网进入文档部分，或首次进入文档，弹出 Toast
      if (
        isUserNavigation ||
        !sessionStorage.getItem("cbnv_serious_toast_shown")
      ) {
        sessionStorage.setItem("cbnv_serious_toast_shown", "true");
        triggerToast("检测到您正在读文档，已为您减少界面干扰。", true, 7000);
      }
    } else {
      applyMode(false);
    }
  }
}

function undoSerious() {
  // 点击撤销：所有项目文档站都不会自动进入简约模式
  localStorage.setItem(STORAGE_KEY_AUTO_DISABLED, "true");
  localStorage.removeItem(STORAGE_KEY_MANUAL);
  applyMode(false);
  triggerToast("已撤销简约模式，后续阅读文档将默认保持质感呈现。", false, 4500);
}

function toggleManual() {
  const next = !isSeriousMode.value;
  applyMode(next);
  localStorage.setItem(STORAGE_KEY_MANUAL, next ? "on" : "off");
  if (next) {
    triggerToast("已切换为简约模式，界面已精简为克制阅读风格。", false, 4500);
  } else {
    triggerToast("已切换为质感模式，全站视觉特效已恢复。", false, 4500);
  }
}

onMounted(() => {
  previousPathWasHome = isHome.value;
  evaluateRouteMode(false);
});

watch(
  () => route.path,
  () => {
    evaluateRouteMode(true);
  },
);
</script>

<template>
  <DefaultTheme.Layout>
    <template #layout-top>
      <!-- 动效光晕装饰带有平滑淡入淡出过渡，在质感模式下启用 -->
      <Transition name="cbnv-deco-fade">
        <div
          v-if="!isSeriousMode && isHome"
          class="adv-docs-deco"
          aria-hidden="true"
        >
          <i class="adv-docs-deco__band"></i>
          <i class="adv-docs-deco__orb adv-docs-deco__orb--a"></i>
          <i class="adv-docs-deco__orb adv-docs-deco__orb--b"></i>
          <i class="adv-docs-deco__orb adv-docs-deco__orb--c"></i>
        </div>
        <div
          v-else-if="!isSeriousMode"
          class="adv-docs-deco adv-docs-deco--subtle"
          aria-hidden="true"
        >
          <i class="adv-docs-deco__band"></i>
          <i class="adv-docs-deco__orb adv-docs-deco__orb--a"></i>
        </div>
      </Transition>
    </template>

    <template #nav-bar-content-after>
      <button
        type="button"
        class="cbnv-serious-toggle"
        :class="{ 'is-active': isSeriousMode }"
        :title="
          isSeriousMode
            ? '简约模式：已开启（极简阅读风格，点击切换质感模式）'
            : '简约模式：已关闭（点击开启）'
        "
        :aria-label="isSeriousMode ? '切换到质感模式' : '切换到简约模式'"
        @click="toggleManual"
      >
        <span class="cbnv-serious-toggle__icon" aria-hidden="true">
          <svg
            v-if="isSeriousMode"
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <rect x="2.5" y="2" width="11" height="12" rx="1.5" />
            <path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" />
          </svg>
          <svg
            v-else
            viewBox="0 0 16 16"
            width="13"
            height="13"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path
              d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3M3.4 3.4l2.1 2.1M10.5 10.5l2.1 2.1M3.4 12.6l2.1-2.1M10.5 5.5l2.1-2.1"
            />
          </svg>
        </span>
        <span class="cbnv-serious-toggle__label">{{
          isSeriousMode ? "简约模式" : "质感模式"
        }}</span>
      </button>
    </template>

    <template #nav-screen-content-after>
      <div class="cbnv-serious-toggle-mobile-wrap">
        <button
          type="button"
          class="cbnv-serious-toggle cbnv-serious-toggle--mobile"
          :class="{ 'is-active': isSeriousMode }"
          :aria-label="isSeriousMode ? '切换到质感模式' : '切换到简约模式'"
          @click="toggleManual"
        >
          <span class="cbnv-serious-toggle__icon" aria-hidden="true">
            <svg
              v-if="isSeriousMode"
              viewBox="0 0 16 16"
              width="13"
              height="13"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <rect x="2.5" y="2" width="11" height="12" rx="1.5" />
              <path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" />
            </svg>
            <svg
              v-else
              viewBox="0 0 16 16"
              width="13"
              height="13"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path
                d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3M3.4 3.4l2.1 2.1M10.5 10.5l2.1 2.1M3.4 12.6l2.1-2.1M10.5 5.5l2.1-2.1"
              />
            </svg>
          </span>
          <span class="cbnv-serious-toggle__label">{{
            isSeriousMode ? "简约模式（已开启）" : "质感模式（已开启）"
          }}</span>
        </button>
      </div>
    </template>

    <template #layout-bottom>
      <Transition name="cbnv-toast-slide">
        <div
          v-if="showToast"
          class="cbnv-serious-toast"
          role="status"
          aria-live="polite"
        >
          <div class="cbnv-serious-toast__body">
            <span class="cbnv-serious-toast__icon" aria-hidden="true">
              <!-- 质感模式图标：星芒 -->
              <svg
                v-if="!isSeriousMode"
                viewBox="0 0 16 16"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <path
                  d="M8 1.5v3M8 11.5v3M1.5 8h3M11.5 8h3M3.4 3.4l2.1 2.1M10.5 10.5l2.1 2.1M3.4 12.6l2.1-2.1M10.5 5.5l2.1-2.1"
                />
              </svg>
              <!-- 简约模式图标：文档 -->
              <svg
                v-else
                viewBox="0 0 16 16"
                width="15"
                height="15"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
              >
                <rect x="2.5" y="2" width="11" height="12" rx="1.5" />
                <path d="M5.5 5.5h5M5.5 8h5M5.5 10.5h3" />
              </svg>
            </span>
            <span class="cbnv-serious-toast__message">
              {{ toastMessage }}
              <a
                v-if="hasUndoAction"
                href="javascript:void(0)"
                class="cbnv-serious-toast__undo"
                @click.prevent="undoSerious"
                >点击撤销</a
              >
            </span>
          </div>
          <button
            type="button"
            class="cbnv-serious-toast__close"
            aria-label="关闭提示"
            @click="showToast = false"
          >
            <svg
              viewBox="0 0 12 12"
              width="10"
              height="10"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              aria-hidden="true"
            >
              <path d="M2 2l8 8M10 2l-8 8" />
            </svg>
          </button>
        </div>
      </Transition>
    </template>
  </DefaultTheme.Layout>
</template>
