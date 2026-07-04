<script setup>
import { computed } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
  path: { type: String, default: '' },
  contentType: { type: String, default: 'text' },
})

const lines = computed(() => (props.content || '').split('\n'))

function lineClass(line) {
  const upper = line.toUpperCase()
  if (/ERROR|CRITICAL|FATAL|FAIL/.test(upper)) return 'log-error'
  if (/WARNING|WARN/.test(upper)) return 'log-warn'
  if (/DEBUG|TRACE/.test(upper)) return 'log-debug'
  if (/INFO|SUCCESS|PASS/.test(upper)) return 'log-info'
  return ''
}

function highlightKeywords(text) {
  // Simple keyword highlighting
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(
      /(Error|Exception|Failed|FAILED|FATAL|CRITICAL|Traceback|AssertionError|TimeoutError|ConnectionError)/gi,
      '<span class="kw-error">$1</span>'
    )
    .replace(
      /(Warning|WARN|DeprecationWarning)/gi,
      '<span class="kw-warn">$1</span>'
    )
    .replace(
      /(File "[^"]+", line \d+)/gi,
      '<span class="kw-file">$1</span>'
    )
    .replace(
      /(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?)/g,
      '<span class="kw-ts">$1</span>'
    )
}
</script>

<template>
  <div class="log-viewer">
    <div class="log-toolbar">
      <span class="log-path">{{ path }}</span>
      <span class="log-info">{{ lines.length }} 行</span>
    </div>
    <div class="log-body">
      <table class="log-table">
        <tr
          v-for="(line, i) in lines"
          :key="i"
          :class="lineClass(line)"
        >
          <td class="log-ln">{{ i + 1 }}</td>
          <td class="log-text" v-html="highlightKeywords(line) || '&nbsp;'"></td>
        </tr>
      </table>
    </div>
  </div>
</template>

<style scoped>
.log-viewer {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.log-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 12px;
  background: var(--bg-input);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}
.log-path {
  font-size: 11px;
  color: var(--text-muted);
}
.log-info {
  font-size: 11px;
  color: var(--text-secondary);
}
.log-body {
  flex: 1;
  overflow: auto;
}
.log-table {
  width: 100%;
  border-collapse: collapse;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.5;
}
.log-table td {
  padding: 1px 0;
}
.log-ln {
  width: 48px;
  min-width: 48px;
  text-align: right;
  padding-right: 12px !important;
  color: var(--text-muted);
  user-select: none;
  vertical-align: top;
}
.log-text {
  white-space: pre-wrap;
  word-break: break-all;
  padding-right: 16px !important;
}

/* Line background */
.log-table tr.log-error { background: rgba(245,108,108,0.06); }
.log-table tr.log-warn  { background: rgba(230,162,60,0.05); }
.log-table tr.log-debug { opacity: 0.6; }

/* Keyword colors */
:deep(.kw-error) { color: var(--color-error); font-weight: 600; }
:deep(.kw-warn)  { color: var(--color-warning); }
:deep(.kw-file)  { color: var(--color-primary); }
:deep(.kw-ts)    { color: var(--text-muted); }
</style>
