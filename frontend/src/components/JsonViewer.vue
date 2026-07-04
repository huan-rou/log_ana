<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  content: { type: String, default: '' },
  path: { type: String, default: '' },
})

const parsed = computed(() => {
  try {
    return JSON.parse(props.content || '{}')
  } catch {
    return {}
  }
})

const parseError = computed(() => {
  try {
    JSON.parse(props.content || '{}')
    return null
  } catch (e) {
    return e.message
  }
})

const collapsed = ref(new Set())

function toggle(key) {
  if (collapsed.value.has(key)) {
    collapsed.value.delete(key)
  } else {
    collapsed.value.add(key)
  }
}

function isCollapsed(key) {
  return collapsed.value.has(key)
}

function isExpandable(val) {
  return val !== null && typeof val === 'object'
}

function renderValue(val, key, depth) {
  if (val === null) return '<null>'
  if (val === undefined) return '<undefined>'
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  if (typeof val === 'number') return String(val)
  if (typeof val === 'string') {
    if (val.length > 200) return JSON.stringify(val.slice(0, 200) + '…')
    return JSON.stringify(val)
  }
  return String(val)
}

function typeTag(val) {
  if (val === null) return 'nil'
  if (Array.isArray(val)) return 'arr'
  if (typeof val === 'object') return 'obj'
  return 'val'
}
</script>

<template>
  <div class="json-viewer">
    <div class="json-path">{{ path }}</div>
    <div v-if="parseError" class="json-error">{{ parseError }}</div>
    <div v-else class="json-tree">
      <template v-for="(val, key) in parsed" :key="key">
        <div class="json-row">
          <!-- top-level key -->
          <span
            v-if="isExpandable(val)"
            class="json-toggle"
            @click="toggle(key)"
          >{{ isCollapsed(key) ? '▸' : '▾' }}</span>
          <span v-else class="json-toggle-spacer"></span>

          <span class="json-key">"{{ key }}"</span>
          <span class="json-colon">: </span>

          <template v-if="isExpandable(val) && isCollapsed(key)">
            <span class="json-preview">{{ Array.isArray(val) ? `Array(${val.length})` : `{...}` }}</span>
          </template>
          <template v-else-if="!isExpandable(val)">
            <span :class="`json-value json-${typeTag(val)}`">{{ renderValue(val, key, 0) }}</span>
          </template>

          <!-- Expanded object/array children -->
          <template v-if="isExpandable(val) && !isCollapsed(key)">
            <div v-if="Array.isArray(val)" class="json-children">
              <div v-for="(item, idx) in val" :key="idx" class="json-row child">
                <span class="json-toggle-spacer"></span>
                <span class="json-index">{{ idx }}</span>
                <span class="json-colon">: </span>
                <span :class="`json-value json-${typeTag(item)}`">{{ renderValue(item, idx, 1) }}</span>
              </div>
            </div>
            <div v-else class="json-children">
              <div v-for="(v, k) in val" :key="k" class="json-row child">
                <span class="json-toggle-spacer"></span>
                <span class="json-key">"{{ k }}"</span>
                <span class="json-colon">: </span>
                <span :class="`json-value json-${typeTag(v)}`">{{ renderValue(v, k, 1) }}</span>
              </div>
            </div>
          </template>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.json-viewer {
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
}
.json-path {
  padding: 6px 12px;
  font-size: 11px;
  color: var(--text-muted);
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-input);
}
.json-error {
  padding: 16px;
  color: var(--color-error);
}
.json-tree {
  padding: 8px 12px;
}
.json-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
}
.json-row.child {
  margin-left: 20px;
}
.json-toggle {
  cursor: pointer;
  user-select: none;
  width: 14px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.json-toggle-spacer {
  width: 14px;
  flex-shrink: 0;
}
.json-key {
  color: #0451a5;
  flex-shrink: 0;
}
.json-index {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.json-colon {
  color: var(--text-primary);
  margin-right: 4px;
}
.json-value {
  word-break: break-all;
}
.json-value.json-val   { color: var(--text-primary); }
.json-value.json-nil   { color: var(--text-muted); font-style: italic; }
.json-value.json-str   { color: #0a8; }
.json-value.json-num   { color: #0550ae; }
.json-value.json-bool  { color: #cf222e; }
.json-preview {
  color: var(--text-muted);
  font-style: italic;
}
.json-children {
  width: 100%;
}
</style>
