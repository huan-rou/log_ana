<script setup>
import { ref } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
  path: { type: String, default: '' },
})

const mode = ref('rendered')

const clean = (props.content || '')
  .replace(/<script[\s\S]*?<\/script>/gi, '')
  .replace(/<script[\s\S]*?\/?>/gi, '')
</script>

<template>
  <div class="html-viewer">
    <div class="html-toolbar">
      <span class="html-path">{{ path }}</span>
      <div class="html-modes">
        <button :class="{ active: mode === 'rendered' }" @click="mode = 'rendered'">渲染</button>
        <button :class="{ active: mode === 'source' }" @click="mode = 'source'">源码</button>
      </div>
    </div>
    <div class="html-body">
      <iframe
        v-show="mode === 'rendered'"
        :srcdoc="clean"
        sandbox="allow-same-origin"
        class="html-iframe"
      ></iframe>
      <pre v-show="mode === 'source'" class="html-source"><code>{{ clean }}</code></pre>
    </div>
  </div>
</template>

<style scoped>
.html-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.html-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-input);
  flex-shrink: 0;
}
.html-path {
  font-size: 11px;
  color: var(--text-muted);
}
.html-modes {
  display: flex;
  gap: 0;
}
.html-modes button {
  padding: 2px 10px;
  font-size: 11px;
  border: 1px solid var(--border-color);
  background: var(--bg-panel);
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font-family);
}
.html-modes button:first-child {
  border-radius: var(--radius-sm) 0 0 var(--radius-sm);
}
.html-modes button:last-child {
  border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
  border-left: none;
}
.html-modes button.active {
  background: var(--color-primary);
  color: var(--text-inverse);
  border-color: var(--color-primary);
}
.html-body {
  flex: 1;
  overflow: hidden;
}
.html-iframe {
  width: 100%;
  height: 100%;
  border: none;
}
.html-source {
  height: 100%;
  overflow: auto;
  padding: 12px;
  margin: 0;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-primary);
}
</style>
