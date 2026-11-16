<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useData, withBase } from 'vitepress'

const props = withDefaults(
  defineProps<{
    src: string
    title?: string
    aspect?: string
    newTabLabel?: string
    expandLabel?: string
    collapseLabel?: string
  }>(),
  {
    title: '',
    aspect: '',
    newTabLabel: '',
    expandLabel: '',
    collapseLabel: '',
  },
)

const { isDark, lang } = useData()

const isEn = computed(() => String(lang.value || '').toLowerCase().startsWith('en'))

const resolvedTitle = computed(
  () =>
    props.title ||
    (isEn.value ? 'Interactive Architecture Diagram' : '交互式架构图（支持平移 / 缩放 / 节点探查）'),
)

const resolvedNewTabLabel = computed(
  () => props.newTabLabel || (isEn.value ? 'Open Full View ↗' : '在新窗口打开 ↗'),
)

const resolvedExpandLabel = computed(() =>
  isExpanded.value
    ? props.collapseLabel || (isEn.value ? 'Exit' : '退出全屏')
    : props.expandLabel || (isEn.value ? 'Fullscreen' : '全屏查看'),
)

const standaloneHref = computed(() => withBase(props.src))

const stageHref = computed(() => {
  const base = standaloneHref.value
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}stage=1&theme=${isDark.value ? 'dark' : 'light'}`
})

const anchorRef = ref<HTMLElement | null>(null)
const cardRef = ref<HTMLElement | null>(null)
const iframeRef = ref<HTMLIFrameElement | null>(null)
const stageRef = ref<HTMLElement | null>(null)
const isExpanded = ref(false)
const containerWidth = ref(720)
const viewportH = ref(860)
const detectedRatio = ref<number | null>(null)
let resizeObserver: ResizeObserver | null = null

function parseAspect(raw: string): number | null {
  if (!raw) return null
  const parts = raw.split(/[/:x]/).map((s) => Number(s.trim()))
  if (parts.length === 2 && parts[0] > 0 && parts[1] > 0) return parts[0] / parts[1]
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
}

const activeRatio = computed(() => detectedRatio.value || parseAspect(props.aspect) || 1.85)

const stageHeightPx = computed(() => {
  const w = Math.max(240, containerWidth.value)
  const r = activeRatio.value
  const isCompact = w < 540
  const dockReserve = isCompact ? 54 : 62
  const ideal = Math.round(w / r + dockReserve)
  const minH = isCompact ? 250 : 280
  const maxH = isCompact
    ? Math.min(440, Math.round(viewportH.value * 0.62))
    : Math.min(620, Math.round(viewportH.value * 0.74))
  return Math.max(minH, Math.min(Math.max(minH, maxH), ideal))
})

function syncTheme(): void {
  try {
    const doc = iframeRef.value?.contentDocument
    if (!doc?.documentElement) return
    doc.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  } catch {
    // Ignore cross-origin frame access if an external URL is supplied.
  }
}

function handleIframeLoad(): void {
  syncTheme()
  try {
    const doc = iframeRef.value?.contentDocument
    const svg = doc?.querySelector('svg')
    const vb = svg?.getAttribute('viewBox')
    if (vb) {
      const nums = vb.trim().split(/[\s,]+/).map(Number)
      if (nums.length === 4 && nums[2] > 0 && nums[3] > 0) {
        detectedRatio.value = nums[2] / nums[3]
      }
    }
  } catch {
    // Keep provided or fallback aspect ratio.
  }
}

function toggleExpand(): void {
  isExpanded.value = !isExpanded.value
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && isExpanded.value) {
    isExpanded.value = false
  }
}

function updateViewport(): void {
  if (typeof window === 'undefined') return
  viewportH.value = window.innerHeight || 860
  if (anchorRef.value) {
    containerWidth.value = anchorRef.value.clientWidth || containerWidth.value
  }
}

watch(isDark, () => {
  syncTheme()
})

watch(isExpanded, (expanded) => {
  if (typeof document === 'undefined') return
  document.documentElement.style.overflow = expanded ? 'hidden' : ''
})

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport, { passive: true })
  window.addEventListener('keydown', handleKeydown)
  if (typeof ResizeObserver === 'function' && anchorRef.value) {
    resizeObserver = new ResizeObserver(() => {
      if (!isExpanded.value && anchorRef.value) {
        containerWidth.value = anchorRef.value.clientWidth || containerWidth.value
      }
    })
    resizeObserver.observe(anchorRef.value)
  }
})

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('resize', updateViewport)
    window.removeEventListener('keydown', handleKeydown)
  }
  if (typeof document !== 'undefined') {
    document.documentElement.style.overflow = ''
  }
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div
    ref="anchorRef"
    class="diagram-frame-anchor"
    :style="isExpanded ? { height: `${stageHeightPx + 48}px` } : undefined"
  >
    <div v-if="isExpanded" class="diagram-frame-backdrop" @click="isExpanded = false" />
    <div
      ref="cardRef"
      class="archify-diagram-card diagram-frame"
      :class="{ 'is-expanded': isExpanded }"
      role="region"
      :aria-label="resolvedTitle"
    >
      <div class="diagram-frame__bar">
        <span class="diagram-frame__title">
          <span class="diagram-frame__icon" aria-hidden="true">📐</span>
          <span>{{ resolvedTitle }}</span>
        </span>
        <div class="diagram-frame__actions">
          <button
            type="button"
            class="diagram-frame__btn"
            :aria-pressed="isExpanded"
            @click="toggleExpand"
          >
            {{ isExpanded ? '✕' : '⛶' }} {{ resolvedExpandLabel }}
          </button>
          <a
            :href="standaloneHref"
            target="_blank"
            rel="noreferrer"
            class="diagram-frame__link"
          >
            {{ resolvedNewTabLabel }}
          </a>
        </div>
      </div>
      <div
        ref="stageRef"
        class="diagram-frame__stage"
        :style="isExpanded ? undefined : { height: `${stageHeightPx}px` }"
      >
        <iframe
          ref="iframeRef"
          :src="stageHref"
          :title="resolvedTitle"
          width="100%"
          height="100%"
          scrolling="no"
          allowfullscreen
          loading="lazy"
          class="diagram-frame__iframe"
          @load="handleIframeLoad"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.diagram-frame-anchor {
  position: relative;
  margin: 1.5rem 0;
  width: 100%;
}

.diagram-frame-backdrop {
  position: fixed;
  inset: 0;
  z-index: 199;
  background: rgba(9, 13, 22, 0.72);
  backdrop-filter: blur(4px);
}

.diagram-frame {
  border: 1px solid var(--vp-c-border);
  border-radius: 12px;
  overflow: hidden;
  background: var(--vp-c-bg-soft);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
}

.diagram-frame.is-expanded {
  position: fixed;
  inset: 16px;
  z-index: 200;
  margin: 0;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.42);
}

.diagram-frame__bar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px 16px;
  padding: 10px 16px;
  background: var(--vp-c-bg-elv);
  border-bottom: 1px solid var(--vp-c-border);
  font-size: 13px;
  flex: 0 0 auto;
}

.diagram-frame__title {
  font-weight: 600;
  color: var(--vp-c-text-1);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.diagram-frame__icon {
  font-size: 15px;
  flex: 0 0 auto;
}

.diagram-frame__actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  flex: 0 0 auto;
}

.diagram-frame__btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid var(--vp-c-border);
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.5;
  cursor: pointer;
  transition: border-color 0.15s, color 0.15s, background-color 0.15s;
}

.diagram-frame__btn:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
}

.diagram-frame__link {
  font-size: 12px;
  color: var(--vp-c-brand-1);
  text-decoration: none;
  font-weight: 500;
  white-space: nowrap;
}

.diagram-frame__link:hover {
  text-decoration: underline;
}

.diagram-frame__stage {
  position: relative;
  width: 100%;
  overflow: hidden;
  flex: 1 1 auto;
  min-height: 0;
}

.diagram-frame.is-expanded .diagram-frame__stage {
  height: auto;
  flex: 1 1 auto;
  min-height: 0;
}

.diagram-frame__iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  overflow: hidden;
}

@media (max-width: 640px) {
  .diagram-frame.is-expanded {
    inset: 8px;
  }

  .diagram-frame__bar {
    padding: 9px 12px;
    font-size: 12.5px;
  }
}
</style>
