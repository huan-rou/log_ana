<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import FileTree from '@/components/FileTree.vue'
import FileViewer from '@/components/FileViewer.vue'
import { browseApi } from '@/api'

const route = useRoute()
const providers = ref([])
const currentProvider = ref('local')
const treeWidth = ref(280)
const isResizing = ref(false)

// Tab state
const tabs = ref([])
const activeTab = ref(0)

onMounted(async () => {
  try {
    const { data } = await browseApi.roots()
    providers.value = data.roots || []
    if (providers.value.length > 0) {
      currentProvider.value = providers.value[0].id
    }
  } catch {}

  // Deep link: /browse?provider=s3&path=...&name=... 直接打开文件
  const { provider, path, name } = route.query
  if (provider && path) {
    currentProvider.value = provider
    onFileSelect({
      provider,
      path,
      name: name || String(path).split('/').pop(),
    })
  }
})

async function onFileSelect({ provider, path, name }) {
  // Check if already open
  const existing = tabs.value.findIndex(t => t.path === path && t.provider === provider)
  if (existing >= 0) {
    activeTab.value = existing
    return
  }

  // Open new tab (loading)
  const idx = tabs.value.length
  tabs.value.push({
    provider, path, name,
    contentType: '',
    content: '',
    loading: true,
    error: null,
    size: 0,
  })
  activeTab.value = idx

  // Fetch content, then replace tab to trigger reactivity
  try {
    const { data } = await browseApi.file(provider, path)
    tabs.value[idx] = {
      ...tabs.value[idx],
      contentType: data.content_type,
      content: data.content,
      size: data.size,
      loading: false,
    }
  } catch (e) {
    tabs.value[idx] = {
      ...tabs.value[idx],
      error: e.response?.data?.detail || '加载失败',
      loading: false,
    }
  }
}

function closeTab(index) {
  tabs.value.splice(index, 1)
  if (activeTab.value >= tabs.value.length) {
    activeTab.value = Math.max(0, tabs.value.length - 1)
  }
}

function selectTab(index) {
  activeTab.value = index
}

// ── Resize ──
function onResizeStart() {
  isResizing.value = true
  document.addEventListener('mousemove', onResizeMove)
  document.addEventListener('mouseup', onResizeEnd)
}
function onResizeMove(e) {
  if (!isResizing.value) return
  const w = e.clientX - 40 // sidebar width
  treeWidth.value = Math.max(180, Math.min(500, w))
}
function onResizeEnd() {
  isResizing.value = false
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
}

onUnmounted(() => {
  // Cleanup lingering resize listeners in case component unmounts mid-resize
  document.removeEventListener('mousemove', onResizeMove)
  document.removeEventListener('mouseup', onResizeEnd)
})
</script>

<template>
  <div class="browser">
    <!-- Provider selector -->
    <div class="browser-toolbar">
      <select v-model="currentProvider" class="provider-select">
        <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.label }}</option>
      </select>
      <span class="toolbar-spacer"></span>
      <span class="toolbar-info" v-if="tabs.length">{{ tabs.length }} 个文件</span>
    </div>

    <!-- Body: tree + viewer -->
    <div class="browser-body">
      <!-- Tree panel -->
      <div class="tree-panel" :style="{ width: treeWidth + 'px' }">
        <FileTree
          :provider="currentProvider"
          @select="onFileSelect"
        />
      </div>

      <!-- Resize handle -->
      <div class="resize-handle" @mousedown.prevent="onResizeStart"></div>

      <!-- Viewer panel -->
      <div class="viewer-panel">
        <FileViewer
          :tabs="tabs"
          :activeTab="activeTab"
          @closeTab="closeTab"
          @selectTab="selectTab"
        />
      </div>
    </div>
  </div>
</template>

<style scoped>
.browser {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.browser-toolbar {
  display: flex;
  align-items: center;
  padding: 4px 8px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
  gap: 8px;
}

.provider-select {
  font-size: 12px;
  padding: 2px 6px;
  border: 1px solid var(--border-color);
  border-radius: var(--radius-sm);
  background: var(--bg-input);
  color: var(--text-primary);
  font-family: var(--font-family);
  cursor: pointer;
  outline: none;
}
.provider-select:focus {
  border-color: var(--color-primary);
}

.toolbar-spacer {
  flex: 1;
}

.toolbar-info {
  font-size: 11px;
  color: var(--text-muted);
}

.browser-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.tree-panel {
  flex-shrink: 0;
  overflow: hidden;
}

.resize-handle {
  width: 3px;
  cursor: col-resize;
  background: transparent;
  transition: background 0.15s;
  flex-shrink: 0;
}
.resize-handle:hover {
  background: var(--color-primary);
}

.viewer-panel {
  flex: 1;
  overflow: hidden;
}
</style>
