<!--
  任务树节点（用于 preview / view 两种场景）
  与 backend/app/services/task_tree.py parse_task_tree 的返回结构对齐：
    {
      id, name, name_key, node_id, depth, path, is_leaf, sort_order,
      s3_matched?: bool | null,
      extra?: json-string,
      children?: [ TaskTreeNode, ... ]
    }

  props:
    node    {Object}  当前节点
    depth   {Number}  嵌套深度（缩进用）
    showS3  {Boolean} 是否渲染 S3 匹配标签（叶子节点）

  设计：自递归组件。children 缺失/空数组自然终止。
-->
<script setup>
defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  showS3: { type: Boolean, default: false },
})
</script>

<template>
  <div class="tnode">
    <div class="tnode-line" :style="{ paddingLeft: depth * 18 + 8 + 'px' }">
      <span class="tnode-name" :class="{ leaf: node.is_leaf }">{{ node.name || '(未命名)' }}</span>
      <span class="tnode-id num">{{ node.node_id }}</span>
      <span v-if="node.is_leaf && showS3 && node.s3_matched !== null && node.s3_matched !== undefined" class="tnode-s3">
        <el-tag :type="node.s3_matched ? 'success' : 'warning'" size="small" effect="plain">
          {{ node.s3_matched ? 'S3 ✓' : 'S3 ✗' }}
        </el-tag>
      </span>
    </div>
    <div v-if="node.children && node.children.length" class="tnode-children">
      <TaskTreeNode
        v-for="(child, i) in node.children"
        :key="child.id || child.node_id || i"
        :node="child"
        :depth="depth + 1"
        :show-s3="showS3"
      />
    </div>
  </div>
</template>

<style scoped>
.tnode { font-size: var(--text-small); }
.tnode-line {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding-block: 2px;
  border-radius: var(--radius-sm);
}
.tnode-line:hover { background: var(--bg-hover); }
.tnode-name {
  color: var(--text-primary);
  font-weight: 400;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
.tnode-name.leaf {
  color: var(--color-primary);
  font-weight: 500;
}
.tnode-id {
  color: var(--text-muted);
  font-size: var(--text-tiny);
  flex-shrink: 0;
}
.tnode-s3 {
  flex-shrink: 0;
  margin-left: auto;
}
.tnode-children {
  /* nested indentation handled by paddingLeft on each line */
}
</style>
