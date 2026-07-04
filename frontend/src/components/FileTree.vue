<script setup>
import { ref, watch } from 'vue'
import TreeNode from './TreeNode.vue'
import { browseApi } from '@/api'

const props = defineProps({
  provider: { type: String, default: 'local' },
})
const emit = defineEmits(['select'])

const tree = ref([])
const loading = ref(false)
const expandedPaths = ref(new Set())
const selectedPath = ref('')
let _reqSeq = 0

watch(() => props.provider, () => {
  _reqSeq = 0
  tree.value = []
  expandedPaths.value = new Set()
  selectedPath.value = ''
  loadDir('')
}, { immediate: true })

async function loadDir(path) {
  loading.value = true
  const seq = ++_reqSeq
  try {
    const { data } = await browseApi.tree(props.provider, path)
    if (seq !== _reqSeq) return  // stale response, ignore
    const entries = (data.entries || []).map(e => ({ ...e, _children: null, _loaded: false }))
    if (!path) {
      tree.value = entries
    } else {
      _patchChildren(tree.value, path, entries)
    }
  } finally {
    if (seq === _reqSeq) loading.value = false
  }
}

function _patchChildren(nodes, forPath, entries) {
  for (const node of nodes) {
    if (node.path === forPath) {
      node._children = entries
      node._loaded = true
      return true
    }
    if (node._children) {
      if (_patchChildren(node._children, forPath, entries)) return true
    }
  }
  return false
}

function onNodeClick(node) {
  selectedPath.value = node.path
  if (node.type === 'directory') {
    toggle(node)
  } else {
    emit('select', { provider: props.provider, path: node.path, name: node.name, type: node.type })
  }
}

function onNodeDblClick(node) {
  if (node.type === 'directory') toggle(node)
}

function toggle(node) {
  const p = node.path
  if (expandedPaths.value.has(p)) {
    expandedPaths.value.delete(p)
  } else {
    expandedPaths.value.add(p)
    if (node.type === 'directory' && !node._loaded) {
      loadDir(p)
    }
  }
}
</script>

<template>
  <div class="file-tree">
    <div class="tree-header">
      <el-icon :size="14"><FolderOpened /></el-icon>
      <span>{{ provider === 'local' ? '本地' : provider }}</span>
      <span class="tree-header-badge">{{ tree.length }}</span>
    </div>

    <div class="tree-body" v-loading="loading">
      <TreeNode
        v-for="node in tree"
        :key="node.path"
        :node="node"
        :depth="0"
        :selected-path="selectedPath"
        :expanded-paths="expandedPaths"
        @click="onNodeClick"
        @dblclick="onNodeDblClick"
      />
      <div v-if="!tree.length" class="tree-empty">空目录</div>
    </div>
  </div>
</template>

<style scoped>
.file-tree {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border-right: 1px solid var(--border-light);
}
.tree-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: var(--space-sm) var(--space-md);
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}
.tree-header-badge {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-muted);
  font-weight: 400;
}
.tree-body {
  flex: 1;
  overflow-y: auto;
  padding: var(--space-xs) 0;
}
.tree-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
