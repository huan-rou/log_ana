<script>
export default {
  name: 'TreeNode',
  props: {
    node: Object,
    depth: { type: Number, default: 0 },
    selectedPath: String,
    expandedPaths: Object,
  },
  emits: ['click', 'dblclick'],
  computed: {
    isDir() { return this.node.type === 'directory' },
    expanded() { return this.expandedPaths.has(this.node.path) },
    selected() { return this.selectedPath === this.node.path },
    indent() { return this.depth * 16 + 12 },
  },
  methods: {
    fileIcon(node) {
      if (node.type === 'directory') return this.expandedPaths.has(node.path) ? 'FolderOpened' : 'Folder'
      const n = (node.name || '').toLowerCase()
      if (n.endsWith('.json')) return 'Code'
      if (n.endsWith('.html') || n.endsWith('.htm')) return 'Document'
      if (n.endsWith('.log')) return 'Tickets'
      if (n.endsWith('.yaml') || n.endsWith('.yml') || n.endsWith('.xml')) return 'Memo'
      if (n.endsWith('.py')) return 'VideoPlay'
      if (n.endsWith('.zip') || n.endsWith('.gz')) return 'FolderDelete'
      return 'Document'
    },
    formatSize(bytes) {
      if (bytes == null) return ''
      if (bytes < 1024) return `${bytes} B`
      if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
      return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    },
  },
}
</script>

<template>
  <div>
    <div
      class="tree-node"
      :class="{ selected }"
      :style="{ paddingLeft: indent + 'px' }"
      @click="$emit('click', node)"
      @dblclick="$emit('dblclick', node)"
    >
      <!-- expand arrow -->
      <span class="tree-node-icon">
        <el-icon v-if="isDir" :size="12" class="expand-arrow">
          <CaretRight v-if="!expanded" />
          <CaretBottom v-else />
        </el-icon>
        <span v-else style="width:12px;display:inline-block"></span>
      </span>

      <!-- file/folder icon -->
      <el-icon :size="14" class="tree-node-file-icon">
        <component :is="fileIcon(node)" />
      </el-icon>

      <!-- name -->
      <span class="tree-node-name">{{ node.name }}</span>

      <!-- size -->
      <span v-if="node.size != null" class="tree-node-size">{{ formatSize(node.size) }}</span>
    </div>

    <!-- recursive children -->
    <TreeNode
      v-if="isDir && expanded && node._children"
      v-for="child in node._children"
      :key="child.path"
      :node="child"
      :depth="depth + 1"
      :selected-path="selectedPath"
      :expanded-paths="expandedPaths"
      @click="$emit('click', $event)"
      @dblclick="$emit('dblclick', $event)"
    />
  </div>
</template>

<style scoped>
.tree-node {
  display: flex;
  align-items: center;
  padding: 2px var(--space-md);
  cursor: pointer;
  user-select: none;
  font-size: 12px;
  line-height: 22px;
  white-space: nowrap;
}
.tree-node:hover { background: var(--bg-hover); }
.tree-node.selected {
  background: var(--color-primary);
  color: var(--text-inverse);
}
.tree-node.selected .tree-node-size,
.tree-node.selected .expand-arrow {
  color: var(--text-inverse);
  opacity: 0.7;
}
.tree-node-icon {
  width: 16px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.expand-arrow { color: var(--text-muted); }
.tree-node-file-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
  margin: 0 4px;
}
.tree-node-name {
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
}
.tree-node-size {
  font-size: 10px;
  color: var(--text-muted);
  margin-left: auto;
  padding-left: 8px;
  flex-shrink: 0;
}
</style>
