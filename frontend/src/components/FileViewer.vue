<script setup>
import { ref, computed } from 'vue'
import JsonViewer from './JsonViewer.vue'
import HtmlViewer from './HtmlViewer.vue'
import LogViewer from './LogViewer.vue'

const props = defineProps({
  tabs: { type: Array, default: () => [] },
  activeTab: { type: Number, default: 0 },
})

const emit = defineEmits(['closeTab', 'selectTab'])

function viewerComponent(contentType) {
  if (contentType === 'json') return 'json'
  if (contentType === 'html') return 'html'
  if (contentType === 'log' || contentType === 'text') return 'log'
  return 'text'
}

function isImage(contentType) {
  return contentType === 'image'
}
</script>

<template>
  <div class="file-viewer">
    <!-- Tab bar -->
    <div class="viewer-tabs" v-if="tabs.length > 0">
      <div
        v-for="(tab, i) in tabs"
        :key="tab.path"
        class="viewer-tab"
        :class="{ active: i === activeTab }"
        @click="$emit('selectTab', i)"
      >
        <span class="viewer-tab-label">{{ tab.name }}</span>
        <el-icon :size="12" class="viewer-tab-close" @click.stop="$emit('closeTab', i)">
          <Close />
        </el-icon>
      </div>
    </div>

    <!-- Content -->
    <div class="viewer-content" v-if="tabs.length > 0">
      <template v-for="(tab, i) in tabs" :key="tab.path">
        <div v-show="i === activeTab" class="viewer-pane">
          <!-- Loading -->
          <div v-if="tab.loading" class="viewer-loading">
            <el-icon class="is-loading" :size="20"><Loading /></el-icon>
            <span>加载中...</span>
          </div>

          <!-- Error -->
          <div v-else-if="tab.error" class="viewer-error">
            {{ tab.error }}
          </div>

          <!-- Image -->
          <div v-else-if="isImage(tab.contentType)" class="viewer-image">
            <div class="viewer-image-placeholder">图片文件 ({{ tab.size }} bytes)</div>
          </div>

          <!-- JSON -->
          <JsonViewer
            v-else-if="viewerComponent(tab.contentType) === 'json'"
            :content="tab.content"
            :path="tab.path"
          />

          <!-- HTML -->
          <HtmlViewer
            v-else-if="viewerComponent(tab.contentType) === 'html'"
            :content="tab.content"
            :path="tab.path"
          />

          <!-- Log / Text -->
          <LogViewer
            v-else
            :content="tab.content"
            :path="tab.path"
            :content-type="tab.contentType"
          />
        </div>
      </template>
    </div>

    <!-- Empty state -->
    <div v-else class="viewer-empty">
      <el-icon :size="32"><Files /></el-icon>
      <span>选择文件以查看内容</span>
    </div>
  </div>
</template>

<style scoped>
.file-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
}

.viewer-tabs {
  display: flex;
  background: var(--bg-input);
  border-bottom: 1px solid var(--border-light);
  overflow-x: auto;
  flex-shrink: 0;
}
.viewer-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  font-size: 12px;
  color: var(--text-secondary);
  border-right: 1px solid var(--border-light);
  cursor: pointer;
  white-space: nowrap;
  max-width: 180px;
}
.viewer-tab:hover {
  background: var(--bg-hover);
}
.viewer-tab.active {
  background: var(--bg-panel);
  color: var(--text-primary);
  border-bottom: 2px solid var(--color-primary);
  margin-bottom: -1px;
}
.viewer-tab-label {
  overflow: hidden;
  text-overflow: ellipsis;
}
.viewer-tab-close {
  opacity: 0;
  transition: opacity 0.1s;
  flex-shrink: 0;
}
.viewer-tab:hover .viewer-tab-close {
  opacity: 0.6;
}
.viewer-tab-close:hover {
  opacity: 1 !important;
  color: var(--color-error);
}

.viewer-content {
  flex: 1;
  overflow: hidden;
}
.viewer-pane {
  height: 100%;
  overflow: auto;
}

.viewer-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
  font-size: 13px;
}

.viewer-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 200px;
  color: var(--text-muted);
  font-size: 13px;
}

.viewer-error {
  padding: 24px;
  color: var(--color-error);
  font-size: 13px;
}

.viewer-image {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}
.viewer-image-placeholder {
  color: var(--text-muted);
  font-size: 13px;
}
</style>
