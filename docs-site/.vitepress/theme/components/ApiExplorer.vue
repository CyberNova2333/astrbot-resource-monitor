<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type {
  ApiCatalogSpec,
  ApiItemSpec,
} from '../../data/api-types'

const props = defineProps<{
  spec: ApiCatalogSpec
}>()

const searchQuery = ref('')
const selectedGroup = ref('all')
const selectedId = ref(props.spec.items[0]?.id ?? '')
const envIndex = ref(0)
const exampleTab = ref(0)
const responseTab = ref(0)
const mobileListOpen = ref(false)
const plainIndexOpen = ref(false)
const shellRef = ref<HTMLElement | null>(null)
const copiedTarget = shallowRef<'code' | 'resp' | null>(null)
let copyTimer: ReturnType<typeof setTimeout> | undefined

const plainIndexTitle = computed(() => {
  if (props.spec.labels.plainIndexToggle) return props.spec.labels.plainIndexToggle
  return props.spec.labels.allGroups === 'All'
    ? 'Plaintext Search & Print Index (Ctrl+K Target)'
    : '纯文本检索与打印索引（Ctrl+K 站内搜索定位）'
})

const activeEnvironment = computed(() => {
  const envs = props.spec.environments
  if (!envs || envs.length === 0) return ''
  return envs[envIndex.value]?.value ?? envs[0].value
})

const filteredGroups = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  return props.spec.groups
    .filter((g) => selectedGroup.value === 'all' || g.id === selectedGroup.value)
    .map((group) => {
      const items = props.spec.items.filter((item) => {
        if (item.group !== group.id) return false
        if (!q) return true
        return (
          item.title.toLowerCase().includes(q) ||
          item.signature.toLowerCase().includes(q) ||
          item.kind.toLowerCase().includes(q) ||
          item.summary.toLowerCase().includes(q)
        )
      })
      return { group, items }
    })
    .filter((entry) => entry.items.length > 0)
})

const activeItem = computed<ApiItemSpec | undefined>(() => {
  const exact = props.spec.items.find((item) => item.id === selectedId.value)
  if (exact) return exact
  return filteredGroups.value[0]?.items[0] ?? props.spec.items[0]
})

const responseSamples = computed(() => {
  return (activeItem.value?.responses ?? []).filter(
    (r) => typeof r.example === 'string' && r.example.length > 0,
  )
})

const activeExample = computed(() => {
  const list = activeItem.value?.examples ?? []
  return list[exampleTab.value] ?? list[0]
})

const renderedExampleCode = computed(() => {
  const raw = activeExample.value?.code ?? ''
  if (!activeEnvironment.value) return raw
  return raw.replaceAll('{{BASE_URL}}', activeEnvironment.value)
})

const activeResponseSample = computed(() => {
  const list = responseSamples.value
  return list[responseTab.value] ?? list[0]
})

function selectItem(item: ApiItemSpec, updateHash = true) {
  selectedId.value = item.id
  exampleTab.value = 0
  responseTab.value = 0
  mobileListOpen.value = false
  if (updateHash && typeof window !== 'undefined') {
    const nextHash = '#' + encodeURIComponent(item.id)
    if (window.location.hash !== nextHash) {
      window.history.replaceState(null, '', nextHash)
    }
  }
}

function syncFromHash() {
  if (typeof window === 'undefined') return
  const raw = decodeURIComponent(window.location.hash.replace(/^#/, ''))
  if (!raw) return
  const match = props.spec.items.find((item) => item.id === raw)
  if (match) {
    selectedId.value = match.id
    exampleTab.value = 0
    responseTab.value = 0
    window.requestAnimationFrame(() => {
      if (window.scrollY > 0 && !plainIndexOpen.value) {
        window.scrollTo({ top: 0, behavior: 'auto' })
      }
    })
  }
}

async function copyText(text: string, target: 'code' | 'resp') {
  if (!text || typeof navigator === 'undefined' || !navigator.clipboard) return
  try {
    await navigator.clipboard.writeText(text)
    copiedTarget.value = target
    if (copyTimer) clearTimeout(copyTimer)
    copyTimer = setTimeout(() => {
      copiedTarget.value = null
    }, 1800)
  } catch {
    copiedTarget.value = null
  }
}

watch(
  () => props.spec,
  (next) => {
    exampleTab.value = 0
    responseTab.value = 0
    const exists = next.items.some((i) => i.id === selectedId.value)
    if (!exists) {
      selectedId.value = next.items[0]?.id ?? ''
    }
    syncFromHash()
  },
)

onMounted(() => {
  syncFromHash()
  window.addEventListener('hashchange', syncFromHash)
  window.addEventListener('popstate', syncFromHash)
})

onUnmounted(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('hashchange', syncFromHash)
    window.removeEventListener('popstate', syncFromHash)
  }
  if (copyTimer) clearTimeout(copyTimer)
})
</script>

<template>
  <div ref="shellRef" class="apifox-shell">
    <header class="apifox-topbar">
      <div class="apifox-topbar__title-row">
        <div class="apifox-topbar__heading">
          <h1 class="apifox-title">{{ spec.project }}</h1>
          <span class="apifox-count-pill">
            {{ spec.items.length }} {{ spec.labels.totalItems }}
          </span>
        </div>
        <p class="apifox-subtitle">{{ spec.subtitle }}</p>
      </div>

      <div
        v-if="spec.environments && spec.environments.length > 0"
        class="apifox-env-box"
      >
        <label class="apifox-env-label" for="apifox-env-select">
          {{ spec.labels.envLabel }}
        </label>
        <select
          id="apifox-env-select"
          v-model.number="envIndex"
          class="apifox-env-select"
        >
          <option
            v-for="(env, idx) in spec.environments"
            :key="env.label"
            :value="idx"
          >
            {{ env.label }} · {{ env.value }}
          </option>
        </select>
      </div>
    </header>

    <div class="apifox-mobile-trigger-wrap">
      <button
        type="button"
        class="apifox-mobile-trigger"
        :aria-expanded="mobileListOpen"
        @click="mobileListOpen = !mobileListOpen"
      >
        <span>
          <span
            v-if="activeItem"
            class="apifox-kind-badge"
            :class="`badge-${activeItem.kind}`"
          >
            {{ activeItem.kind }}
          </span>
          {{ activeItem?.title ?? spec.labels.mobilePicker }}
        </span>
        <span class="apifox-mobile-chevron">{{ mobileListOpen ? '▲' : '▼' }}</span>
      </button>
    </div>

    <div class="apifox-workbench">
      <!-- Left Catalog Directory -->
      <aside
        class="apifox-sidebar"
        :class="{ 'is-mobile-open': mobileListOpen }"
      >
        <div class="apifox-search-box">
          <input
            v-model="searchQuery"
            type="search"
            class="apifox-search-input"
            :placeholder="spec.searchPlaceholder"
            :aria-label="spec.searchPlaceholder"
          />
          <div class="apifox-group-chips" role="tablist">
            <button
              type="button"
              class="apifox-chip"
              :class="{ 'is-active': selectedGroup === 'all' }"
              @click="selectedGroup = 'all'"
            >
              {{ spec.labels.allGroups }}
            </button>
            <button
              v-for="g in spec.groups"
              :key="g.id"
              type="button"
              class="apifox-chip"
              :class="{ 'is-active': selectedGroup === g.id }"
              @click="selectedGroup = g.id"
            >
              {{ g.title }}
            </button>
          </div>
        </div>

        <nav class="apifox-tree" aria-label="API & Component Navigation">
          <div
            v-for="entry in filteredGroups"
            :key="entry.group.id"
            class="apifox-tree-group"
          >
            <div class="apifox-tree-group-title">
              <span>{{ entry.group.title }}</span>
              <span class="apifox-tree-group-count">{{ entry.items.length }}</span>
            </div>
            <button
              v-for="item in entry.items"
              :key="item.id"
              type="button"
              class="apifox-tree-item"
              :class="{ 'is-selected': activeItem?.id === item.id }"
              :aria-pressed="activeItem?.id === item.id"
              @click="selectItem(item)"
            >
              <span class="apifox-kind-badge" :class="`badge-${item.kind}`">
                {{ item.kind }}
              </span>
              <span class="apifox-tree-item-text">
                <span class="apifox-tree-item-title">{{ item.title }}</span>
                <code class="apifox-tree-item-sig">{{ item.signature }}</code>
              </span>
            </button>
          </div>

          <p v-if="filteredGroups.length === 0" class="apifox-empty">
            {{ spec.emptyText }}
          </p>
        </nav>
      </aside>

      <!-- Center Specification Pane -->
      <main v-if="activeItem" class="apifox-detail">
        <section class="apifox-detail-header">
          <div class="apifox-detail-badges">
            <span
              class="apifox-kind-badge apifox-kind-badge--lg"
              :class="`badge-${activeItem.kind}`"
            >
              {{ activeItem.kind }}
            </span>
            <span v-if="activeItem.auth" class="apifox-meta-pill">
              {{ activeItem.auth }}
            </span>
            <span v-if="activeItem.stability" class="apifox-meta-pill">
              {{ activeItem.stability }}
            </span>
          </div>

          <h2 class="apifox-detail-title">{{ activeItem.title }}</h2>
          <div class="apifox-signature-bar">
            <code class="apifox-signature-code">{{ activeItem.signature }}</code>
          </div>
          <p class="apifox-detail-summary">{{ activeItem.summary }}</p>

          <a
            v-if="activeItem.relatedLink"
            :href="activeItem.relatedLink"
            class="apifox-related-link"
          >
            {{ activeItem.relatedLabel || spec.labels.deepDocs }} ↗
          </a>
        </section>

        <!-- Capability & Explicit Limit Split -->
        <section class="apifox-bounds-grid">
          <div class="apifox-bound-card apifox-bound-card--ok">
            <h3 class="apifox-section-title">{{ spec.labels.canDo }}</h3>
            <ul class="apifox-bound-list">
              <li v-for="(cap, idx) in activeItem.capabilities" :key="idx">
                {{ cap }}
              </li>
            </ul>
          </div>
          <div class="apifox-bound-card apifox-bound-card--limit">
            <h3 class="apifox-section-title">{{ spec.labels.cannotDo }}</h3>
            <ul class="apifox-bound-list">
              <li v-for="(lim, idx) in activeItem.limitations" :key="idx">
                {{ lim }}
              </li>
            </ul>
          </div>
        </section>

        <!-- Parameters / Input Schema -->
        <section class="apifox-card">
          <h3 class="apifox-section-title">{{ spec.labels.params }}</h3>
          <div
            v-if="activeItem.params && activeItem.params.length > 0"
            class="apifox-param-list"
          >
            <div
              v-for="param in activeItem.params"
              :key="param.name"
              class="apifox-param-row"
            >
              <div class="apifox-param-head">
                <code class="apifox-inline-code">{{ param.name }}</code>
                <span class="apifox-loc-pill">{{ param.location }}</span>
                <code class="apifox-type-code">{{ param.type }}</code>
                <span
                  class="apifox-req-pill"
                  :class="param.required ? 'is-req' : 'is-opt'"
                >
                  {{ param.required ? spec.labels.required : spec.labels.optional }}
                </span>
                <span v-if="param.defaultValue" class="apifox-default-val">
                  {{ spec.labels.defaultLabel }}: <code>{{ param.defaultValue }}</code>
                </span>
              </div>
              <p class="apifox-param-desc">{{ param.description }}</p>
            </div>
          </div>
          <p v-else class="apifox-muted-note">{{ spec.labels.noParams }}</p>
        </section>

        <!-- Status / Return Contracts -->
        <section class="apifox-card">
          <h3 class="apifox-section-title">{{ spec.labels.responses }}</h3>
          <div class="apifox-response-list">
            <div
              v-for="(resp, rIdx) in activeItem.responses"
              :key="resp.status + rIdx"
              class="apifox-response-row"
            >
              <span class="apifox-status-pill" :class="`tone-${resp.tone}`">
                {{ resp.status }}
              </span>
              <span class="apifox-response-desc">{{ resp.summary }}</span>
            </div>
          </div>
        </section>
      </main>

      <!-- Right Invocation & Payload Sample Pane -->
      <aside v-if="activeItem" class="apifox-samples">
        <div class="apifox-sample-card">
          <div class="apifox-sample-header">
            <span class="apifox-sample-heading">{{ spec.labels.examples }}</span>
            <button
              type="button"
              class="apifox-copy-btn"
              @click="copyText(renderedExampleCode, 'code')"
            >
              {{ copiedTarget === 'code' ? spec.labels.copied : spec.labels.copy }}
            </button>
          </div>

          <div
            v-if="activeItem.examples.length > 0"
            class="apifox-tabs"
            role="tablist"
          >
            <button
              v-for="(ex, idx) in activeItem.examples"
              :key="ex.label"
              type="button"
              class="apifox-tab"
              :class="{ 'is-active': exampleTab === idx }"
              @click="exampleTab = idx"
            >
              {{ ex.label }}
            </button>
          </div>

          <pre class="apifox-code-pre"><code>{{ renderedExampleCode }}</code></pre>
        </div>

        <div v-if="responseSamples.length > 0" class="apifox-sample-card">
          <div class="apifox-sample-header">
            <span class="apifox-sample-heading">{{ spec.labels.responseSample }}</span>
            <button
              type="button"
              class="apifox-copy-btn"
              @click="copyText(activeResponseSample?.example ?? '', 'resp')"
            >
              {{ copiedTarget === 'resp' ? spec.labels.copied : spec.labels.copy }}
            </button>
          </div>

          <div class="apifox-tabs" role="tablist">
            <button
              v-for="(resp, idx) in responseSamples"
              :key="resp.status"
              type="button"
              class="apifox-tab"
              :class="{ 'is-active': responseTab === idx }"
              @click="responseTab = idx"
            >
              {{ resp.status }}
            </button>
          </div>

          <pre class="apifox-code-pre"><code>{{ activeResponseSample?.example }}</code></pre>
        </div>
      </aside>
    </div>

    <div class="apifox-index-footer">
      <button
        type="button"
        class="apifox-index-toggle"
        :aria-expanded="plainIndexOpen"
        @click="plainIndexOpen = !plainIndexOpen"
      >
        <span>{{ plainIndexOpen ? '▾' : '▸' }}</span>
        <span>{{ plainIndexTitle }}</span>
      </button>
      <div v-show="plainIndexOpen" class="apifox-index-body vp-doc">
        <slot />
      </div>
    </div>
  </div>
</template>

<style scoped>
.apifox-shell {
  max-width: 1500px;
  margin: 0 auto;
  padding: 20px 24px 48px;
  font-family: var(--vp-font-family-base);
  color: var(--vp-c-text-1);
}

.apifox-topbar {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: flex-end;
  gap: 16px;
  padding: 18px 22px;
  margin-bottom: 16px;
  background: var(--vp-c-bg-elv);
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  box-shadow: var(--adv-docs-shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.04));
}

.apifox-topbar__title-row {
  flex: 1 1 420px;
  min-width: 0;
}

.apifox-topbar__heading {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.apifox-title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--vp-c-text-1);
}

.apifox-count-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
  border: 1px solid var(--vp-c-divider);
}

.apifox-subtitle {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--vp-c-text-2);
  line-height: 1.55;
}

.apifox-env-box {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 240px;
}

.apifox-env-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--vp-c-text-3);
}

.apifox-env-select {
  height: 36px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font-size: 13px;
  font-family: var(--vp-font-family-mono);
}

.apifox-mobile-trigger-wrap {
  display: none;
  margin-bottom: 12px;
}

.apifox-mobile-trigger {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-radius: 10px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-elv);
  color: var(--vp-c-text-1);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.apifox-workbench {
  display: grid;
  grid-template-columns: 272px minmax(0, 1.15fr) minmax(360px, 440px);
  gap: 16px;
  align-items: start;
}

.apifox-sidebar {
  position: sticky;
  top: 76px;
  max-height: calc(100vh - 96px);
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--vp-c-bg-elv);
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  overflow: hidden;
}

.apifox-search-box {
  padding: 12px;
  border-bottom: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-alt);
}

.apifox-search-input {
  width: 100%;
  height: 34px;
  padding: 0 10px;
  border-radius: 8px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg);
  color: var(--vp-c-text-1);
  font-size: 13px;
  box-sizing: border-box;
}

.apifox-search-input:focus-visible,
.apifox-env-select:focus-visible,
.apifox-tree-item:focus-visible,
.apifox-tab:focus-visible,
.apifox-copy-btn:focus-visible,
.apifox-chip:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 1px;
}

.apifox-group-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.apifox-chip {
  padding: 3px 8px;
  border-radius: 999px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg);
  color: var(--vp-c-text-2);
  font-size: 11px;
  font-weight: 500;
  cursor: pointer;
}

.apifox-chip.is-active {
  background: var(--vp-c-brand-1);
  color: #ffffff;
  border-color: var(--vp-c-brand-1);
}

.apifox-tree {
  overflow-y: auto;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.apifox-tree-group-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--vp-c-text-3);
}

.apifox-tree-group-count {
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
}

.apifox-tree-item {
  width: 100%;
  min-width: 0;
  overflow: hidden;
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  margin-top: 2px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--vp-c-text-1);
  text-align: left;
  cursor: pointer;
}

.apifox-tree-item:hover {
  background: var(--vp-c-bg-alt);
}

.apifox-tree-item.is-selected {
  background: var(--vp-c-brand-soft);
  border-color: var(--vp-c-brand-1);
}

.apifox-tree-item-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 2px;
}

.apifox-tree-item-title {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.35;
}

.apifox-tree-item-sig {
  font-family: var(--vp-font-family-mono);
  font-size: 11px;
  color: var(--vp-c-text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.apifox-kind-badge {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  padding: 2px 6px;
  border-radius: 6px;
  font-family: var(--vp-font-family-mono);
  font-size: 10px;
  font-weight: 700;
  line-height: 1.35;
  color: #ffffff;
  background: #475569;
}

.apifox-kind-badge--lg {
  font-size: 12px;
  padding: 3px 10px;
}

.badge-GET,
.badge-HEAD {
  background: #059669;
}
.badge-POST,
.badge-WRITE {
  background: #0c5cab;
}
.badge-PUT {
  background: #d97706;
}
.badge-DELETE {
  background: #dc2626;
}
.badge-WSS,
.badge-FRAME {
  background: #0284c7;
}
.badge-MCP {
  background: #7c3aed;
}
.badge-CLI,
.badge-HOOK {
  background: #0d9488;
}
.badge-SDK,
.badge-CLASS {
  background: #4f46e5;
}
.badge-PLUGIN,
.badge-SLOT,
.badge-SCHEMA,
.badge-CONFIG {
  background: #334155;
}

.apifox-detail {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.apifox-detail-header,
.apifox-card {
  background: var(--vp-c-bg-elv);
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  padding: 18px 20px;
}

.apifox-detail-badges {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.apifox-meta-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  background: var(--vp-c-bg-alt);
  color: var(--vp-c-text-2);
  border: 1px solid var(--vp-c-divider);
}

.apifox-detail-title {
  margin: 10px 0 8px;
  font-size: 21px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--vp-c-text-1);
}

.apifox-signature-bar {
  padding: 9px 12px;
  border-radius: 8px;
  background: var(--vp-c-bg-alt);
  border: 1px solid var(--vp-c-divider);
  overflow-x: auto;
}

.apifox-signature-code {
  font-family: var(--vp-font-family-mono);
  font-size: 13px;
  color: var(--vp-c-text-1);
  white-space: nowrap;
}

.apifox-detail-summary {
  margin: 12px 0 0;
  font-size: 14px;
  line-height: 1.65;
  color: var(--vp-c-text-2);
}

.apifox-related-link {
  display: inline-flex;
  align-items: center;
  margin-top: 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--vp-c-brand-1);
  text-decoration: none;
}

.apifox-related-link:hover {
  text-decoration: underline;
}

.apifox-bounds-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.apifox-bound-card {
  border-radius: 12px;
  padding: 14px 16px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-elv);
}

.apifox-bound-card--ok {
  border-left: 4px solid #10b981;
}

.apifox-bound-card--limit {
  border-left: 4px solid #f59e0b;
}

.apifox-section-title {
  margin: 0 0 10px;
  font-size: 14px;
  font-weight: 700;
  color: var(--vp-c-text-1);
}

.apifox-bound-list {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  line-height: 1.55;
  color: var(--vp-c-text-2);
}

.apifox-param-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.apifox-param-row {
  padding: 11px 12px;
  border-radius: 9px;
  background: var(--vp-c-bg-alt);
  border: 1px solid var(--vp-c-divider);
}

.apifox-param-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
}

.apifox-param-desc {
  margin: 7px 0 0;
  font-size: 13px;
  line-height: 1.55;
  color: var(--vp-c-text-2);
}

.apifox-inline-code,
.apifox-type-code {
  font-family: var(--vp-font-family-mono);
  font-size: 12px;
}

.apifox-inline-code {
  font-weight: 700;
  color: var(--vp-c-text-1);
}

.apifox-type-code {
  color: var(--vp-c-brand-1);
}

.apifox-default-val {
  font-size: 11.5px;
  color: var(--vp-c-text-3);
  white-space: nowrap;
}

.apifox-loc-pill,
.apifox-req-pill {
  display: inline-flex;
  align-items: center;
  padding: 1px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.apifox-loc-pill {
  background: var(--vp-c-bg);
  color: var(--vp-c-text-2);
  border: 1px solid var(--vp-c-divider);
  font-family: var(--vp-font-family-mono);
}

.apifox-req-pill.is-req {
  background: rgba(239, 68, 68, 0.12);
  color: #dc2626;
}

.apifox-req-pill.is-opt {
  background: var(--vp-c-bg);
  color: var(--vp-c-text-3);
  border: 1px solid var(--vp-c-divider);
}

.apifox-response-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apifox-response-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--vp-c-bg-alt);
  font-size: 13px;
}

.apifox-status-pill {
  flex: 0 0 auto;
  padding: 2px 8px;
  border-radius: 6px;
  font-family: var(--vp-font-family-mono);
  font-size: 12px;
  font-weight: 700;
}

.tone-ok {
  background: rgba(16, 185, 129, 0.15);
  color: #059669;
}
.tone-warn {
  background: rgba(245, 158, 11, 0.16);
  color: #b45309;
}
.tone-err {
  background: rgba(239, 68, 68, 0.14);
  color: #dc2626;
}
.tone-info {
  background: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
}

.apifox-samples {
  position: sticky;
  top: 76px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.apifox-sample-card {
  border-radius: 12px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-elv);
  overflow: hidden;
}

.apifox-sample-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  border-bottom: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-alt);
}

.apifox-sample-heading {
  font-size: 13px;
  font-weight: 700;
  color: var(--vp-c-text-1);
}

.apifox-copy-btn {
  padding: 3px 10px;
  border-radius: 6px;
  border: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg);
  color: var(--vp-c-text-2);
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.apifox-copy-btn:hover {
  border-color: var(--vp-c-brand-1);
  color: var(--vp-c-brand-1);
}

.apifox-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--vp-c-divider);
}

.apifox-tab {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid transparent;
  background: transparent;
  color: var(--vp-c-text-2);
  font-size: 12px;
  font-weight: 600;
  font-family: var(--vp-font-family-mono);
  cursor: pointer;
}

.apifox-tab.is-active {
  background: var(--vp-c-brand-soft);
  color: var(--vp-c-brand-1);
  border-color: var(--vp-c-brand-1);
}

.apifox-code-pre {
  margin: 0;
  padding: 14px;
  background: var(--vp-code-block-bg);
  color: var(--vp-code-block-color);
  font-family: var(--vp-font-family-mono);
  font-size: 12.5px;
  line-height: 1.55;
  overflow-x: auto;
  max-height: 420px;
}

.apifox-muted-note,
.apifox-empty {
  margin: 0;
  font-size: 13px;
  color: var(--vp-c-text-3);
  padding: 8px 4px;
}

.apifox-index-footer {
  margin-top: 22px;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background: var(--vp-c-bg-elv);
  overflow: hidden;
}

.apifox-index-toggle {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  border: 0;
  background: var(--vp-c-bg-alt);
  color: var(--vp-c-text-2);
  font-size: 13px;
  font-weight: 600;
  text-align: left;
  cursor: pointer;
}

.apifox-index-toggle:hover {
  color: var(--vp-c-text-1);
}

.apifox-index-body {
  padding: 16px 20px;
  border-top: 1px solid var(--vp-c-divider);
}

:global(html.dark) .tone-ok {
  color: #34d399;
}
:global(html.dark) .tone-warn {
  color: #fbbf24;
}
:global(html.dark) .tone-err {
  color: #f87171;
}
:global(html.dark) .apifox-req-pill.is-req {
  color: #f87171;
}

@media (max-width: 1180px) {
  .apifox-workbench {
    grid-template-columns: 248px minmax(0, 1fr);
  }
  .apifox-samples {
    position: static;
    grid-column: 2 / -1;
  }
}

@media (max-width: 820px) {
  .apifox-shell {
    padding: 12px 12px 36px;
  }
  .apifox-mobile-trigger-wrap {
    display: block;
  }
  .apifox-workbench {
    grid-template-columns: minmax(0, 1fr);
  }
  .apifox-sidebar {
    display: none;
    position: static;
    max-height: 360px;
  }
  .apifox-sidebar.is-mobile-open {
    display: flex;
  }
  .apifox-samples {
    grid-column: 1 / -1;
  }
  .apifox-bounds-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
