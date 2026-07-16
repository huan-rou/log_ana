<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { taskApi, logApi, analysisApi } from '@/api'
import ReviewDrawer from '@/components/ReviewDrawer.vue'
import TreeNode from '@/components/TreeNode.vue'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'

const route = useRoute()
const taskId = route.params.id

// ── User role ──
const userRole = ref('')
try {
  const u = JSON.parse(localStorage.getItem('user') || '{}')
  userRole.value = u.role || ''
} catch {}
const canStartTask = computed(() => userRole.value === 'reviewer' || userRole.value === 'admin')
const canWriteReview = computed(() => ['analyst', 'reviewer', 'admin'].includes(userRole.value))

// ── Task ──
const task = ref(null)
const loading = ref(true)

// ── Tabs ──
const activeTab = ref('files')

// ── Analyzed files ──
const files = ref([])
const filesLoading = ref(false)
const statusFilter = ref('')
const typeFilter = ref('')
const fallbackFilter = ref(null)
const summaryFilter = ref('')

// ── Review drawer ──
const drawerVisible = ref(false)
const drawerFileId = ref(null)

// ── Raw log ──
const rawLog = ref({ content: '', total_lines: 0, start_line: 1, end_line: 0 })
const rawLoading = ref(false)
const rawPage = ref(1)
const pageSize = 200

const explorerFiles = ref([])
const explorerFilesLoading = ref(false)
const explorerFileId = ref('')
const explorerLog = ref({ lines: [], total_lines: 0, start_line: 1, end_line: 0 })
const explorerLoading = ref(false)
const explorerPage = ref(1)
const explorerExpandedPaths = ref(new Set())
const explorerSelectedPath = ref('')

// ── Failures ──
const failures = ref([])
const failuresLoading = ref(false)

// ── Refresh timer for running tasks ──
let refreshTimer = null

onMounted(async () => {
  await loadTask()
  if (task.value?.status === 'completed') loadFiles()
  startAutoRefresh()
})

onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
})

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer)
  refreshTimer = setInterval(async () => {
    if (task.value && (task.value.status === 'parsing' || task.value.status === 'analyzing')) {
      await loadTask()
      if (task.value?.status === 'completed') loadFiles()
    }
  }, 3000)
}

async function loadTask() {
  try {
    const { data } = await taskApi.get(taskId)
    task.value = data
    if (data.status === 'completed' || data.status === 'failed') {
      if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null }
    }
  } catch {
    task.value = null
  } finally {
    loading.value = false
  }
}

async function handleRun() {
  try {
    await analysisApi.run(taskId)
    task.value.status = 'parsing'
    startAutoRefresh()
  } catch {}
}

// ════════════════════════════════════════════════════════════════
// 完整重分析（清旧数据 + 重跑 parse/detect/classify）
// ════════════════════════════════════════════════════════════════

const rerunDialogVisible = ref(false)
const rerunSubmitting = ref(false)
const rerunPreserveReview = ref(false)
const rerunResult = ref(null)

function canRerun() {
  // 只有 completed/failed 才能 rerun
  return task.value && (task.value.status === 'completed' || task.value.status === 'failed')
}

function openRerunDialog() {
  rerunPreserveReview.value = false
  rerunResult.value = null
  rerunDialogVisible.value = true
}

async function confirmRerun() {
  rerunSubmitting.value = true
  try {
    const { data } = await analysisApi.rerun(taskId, {
      preserve_review: rerunPreserveReview.value,
    })
    rerunResult.value = data
    // 重置 task 状态让前端轮询接管
    if (task.value) {
      task.value.status = 'parsing'
      task.value.error_message = null
      task.value.total_entries = 0
      task.value.failure_count = 0
      task.value.classified_count = 0
      task.value.unrecognized_count = 0
    }
    startAutoRefresh()
  } finally {
    rerunSubmitting.value = false
  }
}

async function loadFiles() {
  filesLoading.value = true
  try {
    const params = {}
    if (statusFilter.value) params.review_status = statusFilter.value
    if (typeFilter.value) params.file_type = typeFilter.value
    if (fallbackFilter.value !== null) params.is_fallback = fallbackFilter.value
    if (summaryFilter.value) params.summary_result = summaryFilter.value
    const { data } = await analysisApi.files(taskId, params)
    files.value = Array.isArray(data) ? data : []
  } finally {
    filesLoading.value = false
  }
}

function openReview(row) {
  drawerFileId.value = row.id
  drawerVisible.value = true
}

async function loadRawLog() {
  rawLoading.value = true
  const start = (rawPage.value - 1) * pageSize + 1
  const end = rawPage.value * pageSize
  try {
    const { data } = await logApi.raw(taskId, { start_line: start, end_line: end })
    rawLog.value = data
  } finally {
    rawLoading.value = false
  }
}

async function loadExplorerFiles() {
  if (explorerFiles.value.length > 0) return
  explorerFilesLoading.value = true
  try {
    const { data } = await analysisApi.files(taskId, {})
    explorerFiles.value = Array.isArray(data) ? data : []
    const expanded = new Set()
    for (const file of explorerFiles.value) {
      const parts = compactFilePath(file).split('/').filter(Boolean)
      parts.pop()
      let acc = ''
      for (const part of parts) {
        acc = acc ? `${acc}/${part}` : part
        expanded.add(acc)
      }
    }
    explorerExpandedPaths.value = expanded
    if (!explorerFileId.value && explorerFiles.value.length > 0) {
      const failed = explorerFiles.value.find((f) => f.failure_count > 0)
      const selected = failed || explorerFiles.value[0]
      explorerFileId.value = selected.id
      explorerSelectedPath.value = compactFilePath(selected)
      await loadExplorerLog()
    }
  } finally {
    explorerFilesLoading.value = false
  }
}

async function loadExplorerLog() {
  if (!explorerFileId.value) {
    explorerLog.value = { lines: [], total_lines: 0, start_line: 1, end_line: 0 }
    return
  }
  explorerLoading.value = true
  const file = selectedExplorerFile.value
  const start = 1
  const end = file?.total_lines > 0 ? file.total_lines : 1000000
  try {
    const { data } = await logApi.fileRaw(explorerFileId.value, { start_line: start, end_line: end })
    explorerLog.value = {
      lines: data.lines || [],
      total_lines: data.total_lines || 0,
      start_line: data.start_line || start,
      end_line: data.end_line || end,
    }
  } finally {
    explorerLoading.value = false
  }
}

function handleExplorerNodeClick(node) {
  if (node.type === 'directory') {
    toggleExplorerDir(node)
    return
  }
  if (!node.fileId) return
  explorerFileId.value = node.fileId
  explorerSelectedPath.value = node.path
  loadExplorerLog()
}

function toggleExplorerDir(node) {
  const next = new Set(explorerExpandedPaths.value)
  if (next.has(node.path)) {
    next.delete(node.path)
  } else {
    next.add(node.path)
  }
  explorerExpandedPaths.value = next
}

async function loadFailures() {
  failuresLoading.value = true
  try {
    const { data } = await logApi.failures(taskId, { limit: 500 })
    failures.value = Array.isArray(data) ? data : []
  } finally {
    failuresLoading.value = false
  }
}

// ════════════════════════════════════════════════════════════════
// v5：JSON 树视图（按轮次管理）—— 内嵌 [单轮次 / 整体] Tab
// ════════════════════════════════════════════════════════════════

const treeViewActive = ref('single')  // 'single' | 'aggregate'
const treeViewLoading = ref(false)
const treeViewLoaded = ref(false)

// 单轮次 Tab 状态
const trees = ref([])                 // 所有轮次列表
const selectedRound = ref(null)       // 当前选中的 round
const currentTree = ref(null)         // 当前 round 的完整树（含 nodes）
const singleRoundTestcases = ref([])  // 当前 task 的 testcases
const selectedSingleNodeId = ref(null)

// 整体 Tab 状态
const round1Tree = ref(null)          // round=1 的树（作为聚合基准）
const aggTree = ref(null)             // 整体视图用 round1Tree 或当前 round 的树
const selectedAggNodeId = ref(null)
const aggNodeMeta = ref(null)         // getAggregate 返回
const aggTestcases = ref([])          // getAggregateTestcases 返回

// 当前 task 是否关联了 JSON 树
const hasTree = computed(() => !!task.value?.tree_node_id)

const currentRoundInfo = computed(() =>
  trees.value.find((t) => t.round_number === selectedRound.value) || null
)

// ── 加载流程 ──

async function loadJsonTreeView() {
  if (!hasTree.value) return
  treeViewLoading.value = true
  try {
    // 1. 列所有轮次
    const { data } = await analysisApi.getTaskTrees(taskId)
    trees.value = Array.isArray(data) ? data : []

    // 2. 找当前 task 所在 round：让后端按 tree_node_id 推
    let defaultRound = trees.value[0]?.round_number
    try {
      const { data: currentTree } = await analysisApi.getTaskTree(taskId, null)
      if (currentTree?.round_number != null) {
        defaultRound = currentTree.round_number
      }
    } catch {}

    if (trees.value.length > 0) {
      selectedRound.value = defaultRound
    }

    await loadSingleRound()
    await loadAggregate()
  } finally {
    treeViewLoading.value = false
    treeViewLoaded.value = true
  }
}

async function loadSingleRound() {
  if (selectedRound.value == null) return
  try {
    // 1. 拉当前 round 的完整树
    const { data: tree } = await analysisApi.getTaskTree(taskId, selectedRound.value)
    currentTree.value = tree

    // 2. 拉当前 task 的 testcases
    const { data: tc } = await analysisApi.getTestcases(taskId, {
      treeNodeId: task.value?.tree_node_id,
    })
    singleRoundTestcases.value = Array.isArray(tc?.testcases) ? tc.testcases : []
  } catch {}
}

async function loadAggregate() {
  // round=1 作为聚合基准
  try {
    const { data: tree } = await analysisApi.getTaskTree(taskId, 1)
    round1Tree.value = tree
    aggTree.value = tree

    // 自动选第一个节点触发聚合
    const firstLeaf = findFirstNode(tree)
    if (firstLeaf) {
      selectAggregateNode(firstLeaf.id)
    } else {
      aggNodeMeta.value = null
      aggTestcases.value = []
    }
  } catch {}
}

function findFirstNode(tree) {
  if (!tree) return null
  // 优先选叶子节点
  const stack = [{ node: tree, depth: 0 }]
  while (stack.length) {
    const { node } = stack.shift()
    if (node.is_leaf) return node
    if (node.children) {
      for (const child of node.children) stack.push({ node: child, depth: node.depth + 1 })
    }
  }
  return null
}

async function handleRoundChange(newRound) {
  if (newRound == null || newRound === selectedRound.value) return
  selectedRound.value = newRound
  await loadSingleRound()
}

function selectSingleNode(node) {
  selectedSingleNodeId.value = node?.id ?? null
}

async function selectAggregateNode(nodeId) {
  selectedAggNodeId.value = nodeId
  if (!nodeId) {
    aggNodeMeta.value = null
    aggTestcases.value = []
    return
  }
  try {
    const { data: meta } = await analysisApi.getAggregate(taskId, nodeId)
    aggNodeMeta.value = meta
    const { data: tc } = await analysisApi.getAggregateTestcases(taskId, nodeId)
    aggTestcases.value = Array.isArray(tc?.testcases) ? tc.testcases : []
  } catch {
    aggNodeMeta.value = null
    aggTestcases.value = []
  }
}

// ── 汇总统计 ──

const totalMissingRoundsNodes = computed(() => {
  // 单轮次视图里没有 missing 概念，整体视图从 aggNodeMeta 拿
  if (aggNodeMeta.value?.aggregate) {
    return aggNodeMeta.value.aggregate.missing_rounds?.length || 0
  }
  return 0
})

const aggMissingWarning = computed(() => {
  if (!aggNodeMeta.value?.aggregate) return null
  const a = aggNodeMeta.value.aggregate
  if (!a.missing_rounds || a.missing_rounds.length === 0) return null
  return {
    rounds: a.missing_rounds,
    count: a.missing_rounds.length,
    executionCount: a.execution_count,
    latestRound: a.latest_round,
    allRounds: trees.value.map((t) => t.round_number),
  }
})

// ── 内嵌 TaskTreeNode 组件（与 MappingManager 一致） ──
const TaskTreeNodeView = {
  name: 'TaskTreeNodeView',
  props: {
    node: { type: Object, required: true },
    depth: { type: Number, default: 0 },
    selectedId: { type: String, default: null },
    aggMeta: { type: Object, default: null },
    showAggMeta: { type: Boolean, default: false },
  },
  emits: ['select'],
  computed: {
    isSelected() { return this.node.id === this.selectedId },
    effectiveAggMeta() {
      // 仅在 showAggMeta + 当前节点被选中 + 是叶子时返回 meta
      if (this.showAggMeta && this.isSelected && this.node.is_leaf) {
        return this.aggMeta
      }
      return null
    },
    executedCount() {
      if (!this.effectiveAggMeta?.aggregate?.all_rounds) return 0
      return this.effectiveAggMeta.aggregate.all_rounds.filter((r) => r.has_data).length
    },
    totalRounds() {
      return this.effectiveAggMeta?.aggregate?.all_rounds?.length || 0
    },
    missingRounds() {
      return this.effectiveAggMeta?.aggregate?.missing_rounds || []
    },
  },
  template: `
    <div class="tnode">
      <div
        class="tnode-line"
        :class="{ selected: isSelected, clickable: true }"
        :style="{ paddingLeft: depth * 16 + 8 + 'px' }"
        @click="$emit('select', node)"
      >
        <span class="tnode-name" :class="{ leaf: node.is_leaf }">{{ node.name || '(未命名)' }}</span>
        <span class="tnode-id mono">{{ node.node_id }}</span>
        <span v-if="effectiveAggMeta" class="tnode-meta">
          <el-tag size="small" effect="plain" :type="executedCount > 0 ? 'success' : 'info'">
            执行 {{ executedCount }} / {{ totalRounds }}
          </el-tag>
          <el-tag
            v-if="missingRounds.length > 0"
            size="small" effect="plain" type="warning"
          >
            缺 {{ missingRounds.join('/') }}
          </el-tag>
        </span>
      </div>
      <div v-if="node.children && node.children.length" class="tnode-children">
        <TaskTreeNodeView
          v-for="(child, i) in node.children"
          :key="child.id || child.node_id || i"
          :node="child"
          :depth="depth + 1"
          :selected-id="selectedId"
          :agg-meta="aggMeta"
          :show-agg-meta="showAggMeta"
          @select="$emit('select', $event)"
        />
      </div>
    </div>
  `,
}

function handleTabChange(tab) {
  if (tab === 'files' && files.value.length === 0) loadFiles()
  if (tab === 'raw' && rawLog.value.total_lines === 0) loadRawLog()
  if (tab === 'explorer') loadExplorerFiles()
  if (tab === 'failures' && failures.value.length === 0) loadFailures()
  if (tab === 'tree' && !treeViewLoaded.value) loadJsonTreeView()
}

// 任务刷新后重新加载 JSON 树视图（task.tree_node_id 可能变化）
watch(() => task.value?.tree_node_id, (newId, oldId) => {
  if (newId !== oldId && activeTab.value === 'tree') {
    treeViewLoaded.value = false
    selectedSingleNodeId.value = null
    selectedAggNodeId.value = null
    aggNodeMeta.value = null
    aggTestcases.value = []
    loadJsonTreeView()
  }
})

// ── Stats ──
const fileStats = computed(() => {
  const all = files.value
  return {
    total: all.length,
    failed: all.filter((f) => f.failure_count > 0).length,
    reviewed: all.filter((f) => f.review_status !== 'pending').length,
    unrecognized: all.filter((f) => f.primary?.is_fallback).length,
  }
})

function filterUnrecognized() {
  fallbackFilter.value = fallbackFilter.value === true ? null : true
  loadFiles()
}

async function jumpToExplorer(fileId) {
  activeTab.value = 'explorer'
  explorerFileId.value = fileId
  await loadExplorerFiles()
  explorerSelectedPath.value = compactFilePath(selectedExplorerFile.value || '')
  await loadExplorerLog()
}

const statusTag = (s) => {
  const map = { pending: 'info', parsing: 'warning', analyzing: '', completed: 'success', failed: 'danger' }
  return map[s] || 'info'
}

const statusLabel = (s) => {
  const map = { pending: '待处理', parsing: '解析中', analyzing: '分析中', completed: '已完成', failed: '失败' }
  return map[s] || s
}

const reviewBadge = (s) => {
  const map = {
    pending: { type: 'warning', label: '待审核' },
    confirmed: { type: 'success', label: '已确认' },
    overridden: { type: 'primary', label: '已覆盖' },
  }
  return map[s] || { type: 'info', label: s }
}

const fileTypeLabel = (t) => {
  const map = { testsuite: '测试套', testcase: '测试用例', task_log: '任务日志' }
  return map[t] || t
}

// ── 上传方原始结果（summary_report.yaml）──
function summaryResult(row) {
  return row.summary_report?.display_result || '—'
}

function summaryStatusTag(row) {
  const map = { success: 'success', failed: 'danger', blocked: 'warning' }
  return map[row.summary_report?.normalized_status] || 'info'
}

function summaryIdentity(row) {
  const s = row.summary_report
  if (!s) return null
  if (row.file_type === 'testcase' && s.case_id) {
    return { id: s.case_id, desc: s.case_desc }
  }
  if (s.suite_id) {
    return { id: s.suite_id, desc: s.suite_desc }
  }
  return null
}

function summaryFailReason(row) {
  return row.summary_report?.fail_reason_short || '—'
}

function finalCategoryText(row) {
  const c = row.final_category
  if (!c) return row.failure_count > 0 ? '无法识别' : '—'
  return c.parent_name ? `${c.parent_name} / ${c.name}` : c.name
}

function compactFilePath(file) {
  const raw = (file.file_path || file.name || '').replace(/\\/g, '/')
  const marker = '/artifacts/'
  if (raw.includes(marker)) return raw.slice(raw.indexOf(marker) + 1)
  const parts = raw.split('/').filter(Boolean)
  return parts.slice(-4).join('/') || file.name
}

function fileDisplayName(file) {
  const identity = summaryIdentity(file)?.id
  return identity || file.name
}

function buildExplorerTree(filesToMap) {
  const root = []
  const dirMap = new Map()

  function ensureDir(pathParts, parentChildren) {
    let children = parentChildren
    let acc = ''
    for (const part of pathParts) {
      acc = acc ? `${acc}/${part}` : part
      if (!dirMap.has(acc)) {
        const node = {
          id: `dir:${acc}`,
          path: acc,
          name: part,
          type: 'directory',
          _children: [],
        }
        dirMap.set(acc, node)
        children.push(node)
      }
      children = dirMap.get(acc)._children
    }
    return children
  }

  for (const file of filesToMap) {
    const compact = compactFilePath(file)
    const parts = compact.split('/').filter(Boolean)
    const fileName = parts.pop() || file.name
    const children = ensureDir(parts, root)
    children.push({
      id: file.id,
      fileId: file.id,
      path: compact,
      name: fileDisplayName(file),
      rawName: fileName,
      type: 'file',
      file,
    })
  }

  return root
}

const totalRawPages = computed(() => Math.ceil((rawLog.value.total_lines || 0) / pageSize))
const selectedExplorerFile = computed(() => explorerFiles.value.find((f) => f.id === explorerFileId.value) || null)
const explorerFileTitle = computed(() => {
  const file = selectedExplorerFile.value
  if (!file) return ''
  const identity = summaryIdentity(file)?.id
  return identity ? `${identity} · ${file.name}` : file.name
})
const explorerTree = computed(() => buildExplorerTree(explorerFiles.value))

const s3PathText = computed(() => {
  if (!task.value) return ''
  return task.value.s3_path || `${task.value.package_version}/${task.value.automation_task_id}/${task.value.node_id}/${task.value.task_block_id}`
})
</script>

<template>
  <div class="page task-detail" v-loading="loading">
    <AppPageHeader
      :title="task?.name || '加载中...'"
      :subtitle="task ? `${fileStats.total} 个文件 · ${fileStats.failed} 个失败 · ${fileStats.reviewed} 已审核` : ''"
    >
      <template #meta>
        <el-tag v-if="task" :type="statusTag(task.status)">{{ statusLabel(task.status) }}</el-tag>
        <el-tag v-if="task" size="small" :type="task.source_type === 's3' ? '' : 'info'">
          {{ task.source_type === 's3' ? 'S3' : '本地上传' }}
        </el-tag>
        <span v-if="task?.source_type === 's3'" class="meta-item mono" :title="s3PathText">
          {{ s3PathText }}
        </span>
        <span v-if="task" class="meta-item">创建: {{ task.created_at }}</span>
        <span v-if="task?.completed_at" class="meta-item">完成: {{ task.completed_at }}</span>
      </template>
      <template #actions>
        <el-button
          v-if="canStartTask"
          type="primary"
          @click="handleRun"
          :disabled="!task || (task.status !== 'pending' && task.status !== 'failed')"
        >
          <el-icon><VideoPlay /></el-icon>
          运行分析
        </el-button>
        <el-tooltip
          v-if="canStartTask && canRerun()"
          content="清空已有 LogEntry / FailureEvent / AnalysisResult / Feedback 后重跑完整流水线（应用最新解析 / 检测 / 规则代码）"
          placement="bottom"
        >
          <el-button
            type="warning"
            plain
            @click="openRerunDialog"
          >
            <el-icon><Refresh /></el-icon>
            重新分析
          </el-button>
        </el-tooltip>
      </template>
    </AppPageHeader>

    <el-alert
      v-if="task?.error_message"
      :title="task.error_message"
      type="error"
      :closable="false"
      class="error-msg"
    />

    <!-- ════════════════════════════════════════════════════════════════ -->
    <!-- 重新分析对话框（v6）                                            -->
    <!-- ════════════════════════════════════════════════════════════════ -->
    <el-dialog
      v-model="rerunDialogVisible"
      :title="rerunResult ? '重新分析已启动' : '完整重新分析'"
      width="560px"
      :close-on-click-modal="false"
    >
      <template v-if="rerunResult">
        <el-alert
          type="success"
          :closable="false"
          :title="`任务已进入重新分析流水线（${rerunResult.preserve_review ? '保留人工结论' : '已重置人工结论'}）`"
        />
        <h4 class="rerun-sub-title">已清理的旧数据</h4>
        <el-row :gutter="8">
          <el-col :span="8"><div class="rerun-stat"><span class="num">{{ rerunResult.deleted?.log_entries ?? 0 }}</span><span class="lbl">日志条目</span></div></el-col>
          <el-col :span="8"><div class="rerun-stat"><span class="num">{{ rerunResult.deleted?.failure_events ?? 0 }}</span><span class="lbl">失败事件</span></div></el-col>
          <el-col :span="8"><div class="rerun-stat"><span class="num">{{ rerunResult.deleted?.analysis_results ?? 0 }}</span><span class="lbl">分析结果</span></div></el-col>
        </el-row>
        <el-row :gutter="8" style="margin-top: 8px">
          <el-col :span="8"><div class="rerun-stat"><span class="num">{{ rerunResult.deleted?.feedback ?? 0 }}</span><span class="lbl">反馈记录</span></div></el-col>
          <el-col :span="8"><div class="rerun-stat"><span class="num">{{ rerunResult.deleted?.testcases ?? 0 }}</span><span class="lbl">用例记录</span></div></el-col>
          <el-col v-if="!rerunResult.preserve_review" :span="8"><div class="rerun-stat"><span class="num">{{ rerunResult.deleted?.log_files_reset ?? 0 }}</span><span class="lbl">文件审核心</span></div></el-col>
        </el-row>
        <p class="rerun-foot">
          任务状态已切到 <code>parsing</code>，后台流水线已经在跑。页面会自动刷新状态。
        </p>
      </template>

      <template v-else>
        <el-alert
          type="warning"
          :closable="false"
          style="margin-bottom: 12px"
          show-icon
        >
          <template #title>
            <strong>此操作不可逆。</strong>将删除现有日志条目、失败事件、分析结果、反馈，
            然后从 <code>parsing</code> 重新开始一整条分析流水线。
          </template>
        </el-alert>

        <el-form label-width="120px">
          <el-form-item label="保留人工审核">
            <el-switch v-model="rerunPreserveReview" />
            <div class="form-hint">
              <strong v-if="rerunPreserveReview">已开启：</strong>
              <strong v-else>默认关闭（推荐）：</strong>
              <span v-if="rerunPreserveReview">
                LogFile 上的人工覆盖/确认结论保留，但因底下的 AnalysisResult 变了，可能出现不一致。
              </span>
              <span v-else>
                会把 LogFile 的 review_status 全部重置为 <code>pending</code>，清空所有 override 字段，
                并清理 ArchivedReview / HighValueRecord 标记。
              </span>
            </div>
          </el-form-item>
        </el-form>
      </template>

      <template #footer>
        <el-button @click="rerunDialogVisible = false">关闭</el-button>
        <el-button
          v-if="!rerunResult"
          type="warning"
          :loading="rerunSubmitting"
          @click="confirmRerun"
        >
          {{ rerunPreserveReview ? '确认重新分析（保留审核）' : '确认重新分析（重置审核）' }}
        </el-button>
      </template>
    </el-dialog>

    <AppSection title="任务概览" v-if="task">
      <el-row :gutter="16" class="stat-row">
        <el-col :span="6">
          <div class="mini-stat">
            <span class="mini-stat-num">{{ fileStats.total }}</span>
            <span class="mini-stat-label">日志文件</span>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="mini-stat error">
            <span class="mini-stat-num">{{ fileStats.failed }}</span>
            <span class="mini-stat-label">失败文件</span>
          </div>
        </el-col>
        <el-col :span="6">
          <div class="mini-stat success">
            <span class="mini-stat-num">{{ fileStats.reviewed }} / {{ fileStats.total }}</span>
            <span class="mini-stat-label">已审核</span>
          </div>
        </el-col>
        <el-col :span="6">
          <div
            class="mini-stat warning clickable"
            :class="{ active: fallbackFilter === true }"
            @click="filterUnrecognized"
            title="点击只看未识别文件"
          >
            <span class="mini-stat-num">{{ fileStats.unrecognized }}</span>
            <span class="mini-stat-label">未识别</span>
          </div>
        </el-col>
      </el-row>
    </AppSection>

    <AppSection title="分析详情" hint="切换 Tab 查看不同维度的数据">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <!-- ═══ v5：JSON 树视图（按轮次）═══ -->
        <el-tab-pane label="JSON 树视图" name="tree">
          <div v-if="!hasTree" class="tree-view-empty">
            <el-empty
              description="该任务未关联 JSON 树（Task.tree_node_id 为空）"
              :image-size="80"
            >
              <template #default>
                <p class="tree-view-hint">
                  该任务没有关联的 JSON 树节点。在「任务映射管理」里给当前版本追加执行轮次，
                  然后用「按此次批量建任务」即可自动关联。
                </p>
                <el-button
                  type="primary"
                  tag="router-link"
                  :to="'/mapping'"
                >
                  前往任务映射管理
                </el-button>
              </template>
            </el-empty>
          </div>
          <div v-else v-loading="treeViewLoading">
            <el-tabs v-model="treeViewActive" class="tree-inner-tabs">
              <!-- 单轮次 Tab -->
              <el-tab-pane label="单轮次" name="single">
                <div class="tree-view-toolbar">
                  <span class="toolbar-label">轮次：</span>
                  <el-select
                    :model-value="selectedRound"
                    @update:model-value="handleRoundChange"
                    placeholder="选择轮次"
                    style="width: 140px"
                  >
                    <el-option
                      v-for="t in trees"
                      :key="t.round_number"
                      :label="`#${t.round_number}（${t.root_name}）`"
                      :value="t.round_number"
                    />
                  </el-select>
                  <el-tag v-if="currentTree" size="small" effect="plain">
                    {{ currentTree.total_nodes }} 节点
                  </el-tag>
                  <el-tag v-if="currentTree" size="small" effect="plain" type="success">
                    {{ currentTree.leaf_count }} 叶子
                  </el-tag>
                  <el-tag v-if="currentRoundInfo" size="small" type="info" effect="plain">
                    {{ currentRoundInfo.note }}
                  </el-tag>
                </div>

                <div class="tree-view-split">
                  <!-- 左：树 -->
                  <div class="tree-view-tree-panel">
                    <div class="panel-header">
                      <el-icon><FolderOpened /></el-icon>
                      <span>任务树（轮次 #{{ selectedRound }}）</span>
                    </div>
                    <div class="panel-body tree-scroll">
                      <TaskTreeNodeView
                        v-if="currentTree"
                        :node="currentTree"
                        :depth="0"
                        :selected-id="selectedSingleNodeId"
                        @select="selectSingleNode"
                      />
                      <div v-else class="empty-text">加载中...</div>
                    </div>
                  </div>

                  <!-- 右：TestCase 行 -->
                  <div class="tree-view-table-panel">
                    <div class="panel-header">
                      <span>当前任务的 TestCase 行（{{ singleRoundTestcases.length }}）</span>
                    </div>
                    <div class="panel-body">
                      <el-table
                        :data="singleRoundTestcases"
                        stripe
                        size="small"
                        max-height="500"
                        empty-text="当前任务暂无 testcase 文件"
                        class="data-table"
                      >
                        <el-table-column label="测试用例" min-width="180" show-overflow-tooltip>
                          <template #default="{ row }">
                            <span class="mono">{{ row.testcase_name }}</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="失败数" width="80" align="center">
                          <template #default="{ row }">
                            <el-tag
                              size="small"
                              :type="row.logfile.failure_count > 0 ? 'danger' : 'info'"
                              effect="plain"
                            >
                              {{ row.logfile.failure_count }}
                            </el-tag>
                          </template>
                        </el-table-column>
                        <el-table-column label="日志文件" min-width="200" show-overflow-tooltip>
                          <template #default="{ row }">
                            <span class="mono file-cell" :title="row.logfile.file_path">
                              {{ row.logfile.name }}
                            </span>
                          </template>
                        </el-table-column>
                        <el-table-column label="审核状态" width="100" align="center">
                          <template #default="{ row }">
                            <el-tag size="small" :type="reviewBadge(row.logfile.review_status).type">
                              {{ reviewBadge(row.logfile.review_status).label }}
                            </el-tag>
                          </template>
                        </el-table-column>
                        <el-table-column label="操作" width="160" align="center" fixed="right">
                          <template #default="{ row }">
                            <el-button
                              link
                              type="primary"
                              size="small"
                              @click="jumpToExplorer(row.logfile.id)"
                            >
                              日志
                            </el-button>
                            <el-button
                              link
                              type="primary"
                              size="small"
                              @click="openReview({ id: row.logfile.id })"
                            >
                              审核
                            </el-button>
                          </template>
                        </el-table-column>
                      </el-table>
                    </div>
                  </div>
                </div>
              </el-tab-pane>

              <!-- 整体 Tab -->
              <el-tab-pane label="整体" name="aggregate">
                <!-- 缺失告警条 -->
                <el-alert
                  v-if="aggMissingWarning"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="missing-alert"
                >
                  <template #title>
                    <strong>{{ aggMissingWarning.count }} 个轮次存在日志缺失</strong>
                    <span class="muted-text">
                      （执行 {{ aggMissingWarning.executionCount }} 次 / 最新轮次 #{{ aggMissingWarning.latestRound ?? '—' }} /
                      缺失 {{ aggMissingWarning.rounds.join(', ') }}）
                    </span>
                  </template>
                </el-alert>

                <div class="tree-view-toolbar">
                  <span class="toolbar-label">聚合基准：</span>
                  <el-tag size="small" effect="plain">Round #1（基准）</el-tag>
                  <el-tag size="small" effect="plain" type="info">
                    共 {{ aggTree?.total_nodes || 0 }} 节点 / {{ aggTree?.leaf_count || 0 }} 叶子
                  </el-tag>
                  <span class="toolbar-hint">点击左树节点查看跨 round 聚合</span>
                </div>

                <div class="tree-view-split">
                  <!-- 左：round=1 树（带聚合元信息） -->
                  <div class="tree-view-tree-panel">
                    <div class="panel-header">
                      <el-icon><FolderOpened /></el-icon>
                      <span>Round #1 树（点击节点查聚合）</span>
                    </div>
                    <div class="panel-body tree-scroll">
                      <TaskTreeNodeView
                        v-if="aggTree"
                        :node="aggTree"
                        :depth="0"
                        :selected-id="selectedAggNodeId"
                        :agg-meta="aggNodeMeta"
                        :show-agg-meta="true"
                        @select="(node) => node.is_leaf && selectAggregateNode(node.id)"
                      />
                      <div v-else class="empty-text">加载中...</div>
                    </div>
                  </div>

                  <!-- 右：跨 round 聚合 TestCase 行 -->
                  <div class="tree-view-table-panel">
                    <div class="panel-header">
                      <span v-if="aggNodeMeta?.node">
                        节点：
                        <span class="mono">{{ aggNodeMeta.node.name }}</span>
                        <span class="muted-text">
                          （{{ aggNodeMeta.node.path }}）
                        </span>
                      </span>
                      <span v-else>请选择左树节点</span>
                    </div>
                    <div class="panel-body">
                      <el-row v-if="aggNodeMeta?.aggregate" :gutter="8" class="agg-stats-row">
                        <el-col :span="6">
                          <div class="agg-mini-stat">
                            <span class="agg-num primary">{{ aggNodeMeta.aggregate.execution_count }}</span>
                            <span class="agg-label">已执行次数</span>
                          </div>
                        </el-col>
                        <el-col :span="6">
                          <div class="agg-mini-stat">
                            <span class="agg-num">{{ aggNodeMeta.aggregate.latest_round ?? '—' }}</span>
                            <span class="agg-label">最新轮次</span>
                          </div>
                        </el-col>
                        <el-col :span="6">
                          <div class="agg-mini-stat">
                            <span class="agg-num">{{ aggNodeMeta.aggregate.latest_round_logfile_count ?? 0 }}</span>
                            <span class="agg-label">最新轮日志数</span>
                          </div>
                        </el-col>
                        <el-col :span="6">
                          <div class="agg-mini-stat" :class="{ warning: aggNodeMeta.aggregate.missing_rounds.length > 0 }">
                            <span class="agg-num warning">{{ aggNodeMeta.aggregate.missing_rounds.length }}</span>
                            <span class="agg-label">缺失轮次数</span>
                          </div>
                        </el-col>
                      </el-row>

                      <el-table
                        :data="aggTestcases"
                        stripe
                        size="small"
                        max-height="450"
                        empty-text="该节点暂无 testcase 数据"
                        class="data-table"
                      >
                        <el-table-column label="测试用例" min-width="180" show-overflow-tooltip>
                          <template #default="{ row }">
                            <span class="mono">{{ row.name }}</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="执行次数" width="90" align="center">
                          <template #default="{ row }">
                            <el-tag size="small" :type="row.execution_count > 0 ? 'success' : 'info'" effect="plain">
                              {{ row.execution_count }}
                            </el-tag>
                          </template>
                        </el-table-column>
                        <el-table-column label="已执行轮次" min-width="160">
                          <template #default="{ row }">
                            <span class="mono">
                              <el-tag
                                v-for="r in row.rounds"
                                :key="r"
                                size="small"
                                effect="plain"
                                style="margin-right: 2px"
                              >
                                #{{ r }}
                              </el-tag>
                            </span>
                          </template>
                        </el-table-column>
                        <el-table-column label="缺失轮次" min-width="140">
                          <template #default="{ row }">
                            <template v-if="row.missing_rounds.length > 0">
                              <el-tag
                                v-for="r in row.missing_rounds"
                                :key="r"
                                size="small"
                                type="warning"
                                effect="plain"
                                style="margin-right: 2px"
                              >
                                #{{ r }}
                              </el-tag>
                            </template>
                            <span v-else class="muted-text">—</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="最新轮次" width="90" align="center">
                          <template #default="{ row }">
                            <span class="mono">{{ row.latest_round ?? '—' }}</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="最新日志审核" width="120" align="center">
                          <template #default="{ row }">
                            <el-tag
                              v-if="row.latest_logfile_status"
                              size="small"
                              :type="reviewBadge(row.latest_logfile_status).type"
                            >
                              {{ reviewBadge(row.latest_logfile_status).label }}
                            </el-tag>
                            <span v-else class="muted-text">—</span>
                          </template>
                        </el-table-column>
                        <el-table-column label="操作" width="160" align="center" fixed="right">
                          <template #default="{ row }">
                            <el-button
                              v-if="row.latest_logfile_id"
                              link
                              type="primary"
                              size="small"
                              @click="jumpToExplorer(row.latest_logfile_id)"
                            >
                              最新日志
                            </el-button>
                          </template>
                        </el-table-column>
                      </el-table>
                    </div>
                  </div>
                </div>
              </el-tab-pane>
            </el-tabs>
          </div>
        </el-tab-pane>

        <!-- Analyzed Files Tab -->
        <el-tab-pane label="分析结果" name="files">
          <div class="results-toolbar">
            <el-tooltip content="按审核状态过滤" placement="top">
              <el-select v-model="statusFilter" placeholder="审核状态" clearable style="width: 140px" @change="loadFiles">
                <el-option label="待审核" value="pending" />
                <el-option label="已确认" value="confirmed" />
                <el-option label="已覆盖" value="overridden" />
              </el-select>
            </el-tooltip>
            <el-tooltip content="按文件类型过滤：测试套/用例/任务日志" placement="top">
              <el-select v-model="typeFilter" placeholder="文件类型" clearable style="width: 140px; margin-left: 8px" @change="loadFiles">
                <el-option label="测试套" value="testsuite" />
                <el-option label="测试用例" value="testcase" />
                <el-option label="任务日志" value="task_log" />
              </el-select>
            </el-tooltip>
            <el-tooltip content="按识别状态过滤" placement="top">
              <el-select v-model="fallbackFilter" placeholder="识别状态" clearable style="width: 140px; margin-left: 8px" @change="loadFiles">
                <el-option label="仅未识别" :value="true" />
                <el-option label="仅已识别" :value="false" />
              </el-select>
            </el-tooltip>
            <el-tooltip content="按上传方原始结果过滤" placement="top">
              <el-select v-model="summaryFilter" placeholder="原始结果" clearable style="width: 140px; margin-left: 8px" @change="loadFiles">
                <el-option label="Success" value="success" />
                <el-option label="Failed" value="failed" />
                <el-option label="Blocked" value="blocked" />
              </el-select>
            </el-tooltip>
            <el-tooltip content="刷新当前筛选结果" placement="top">
              <el-button style="margin-left: 8px" @click="loadFiles">
                <el-icon><Refresh /></el-icon>
              </el-button>
            </el-tooltip>
          </div>
          <el-table :data="files" v-loading="filesLoading" max-height="600" stripe class="data-table">
            <el-table-column label="日志文件" min-width="220">
              <template #default="{ row }">
                <span class="mono file-cell" :title="row.file_path">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="100" align="center">
              <template #header>
                <el-tooltip content="测试套 / 测试用例 / 任务日志" placement="top">
                  <span>类型</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                <el-tag size="small" :type="row.file_type === 'testsuite' ? 'success' : row.file_type === 'testcase' ? '' : 'info'">
                  {{ fileTypeLabel(row.file_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="原始结果" width="100" align="center">
              <template #header>
                <el-tooltip content="上传方 summary_report.yaml 里的 success/failed/blocked" placement="top">
                  <span>原始结果</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                <el-tag v-if="row.summary_report" size="small" :type="summaryStatusTag(row)">
                  {{ summaryResult(row) }}
                </el-tag>
                <span v-else class="muted-dash">—</span>
              </template>
            </el-table-column>
            <el-table-column label="用例/套件" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <template v-if="summaryIdentity(row)">
                  <div class="mono summary-id">{{ summaryIdentity(row).id }}</div>
                </template>
                <span v-else class="muted-dash">—</span>
              </template>
            </el-table-column>
            <el-table-column label="失败原因" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tooltip
                  v-if="row.summary_report?.fail_reason_line"
                  :content="row.summary_report.fail_reason_line"
                  placement="top"
                  :show-after="300"
                >
                  <span class="summary-fail">{{ summaryFailReason(row) }}</span>
                </el-tooltip>
                <span v-else class="muted-dash">—</span>
              </template>
            </el-table-column>
            <el-table-column label="最终结论（根因）" min-width="220" show-overflow-tooltip>
              <template #default="{ row }">
                <span :class="{ 'unrec-text': !row.final_category && row.failure_count > 0 }">
                  {{ finalCategoryText(row) }}
                </span>
                <el-tag v-if="row.is_overridden" size="small" type="primary" style="margin-left: 6px">人工覆盖</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="90" align="right">
              <template #header>
                <el-tooltip content="自动分析置信度（人工覆盖后不显示）" placement="top">
                  <span>置信度</span>
                </el-tooltip>
              </template>
              <template #default="{ row }">
                <span v-if="row.is_overridden || !row.primary" class="text-muted">—</span>
                <span v-else :class="row.primary.confidence >= 0.7 ? 'num-ok' : 'num-warn'">
                  {{ (row.primary.confidence * 100).toFixed(0) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="匹配规则" min-width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="text-muted">{{ row.is_overridden ? '—' : (row.primary?.rule_name || '—') }}</span>
              </template>
            </el-table-column>
            <el-table-column label="审核状态" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small" :type="reviewBadge(row.review_status).type">
                  {{ reviewBadge(row.review_status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="jumpToExplorer(row.id)">日志</el-button>
                <el-button link type="primary" size="small" @click="openReview(row)">审核</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- Raw Log Tab -->
        <el-tab-pane label="原始日志" name="raw">
          <div class="raw-toolbar">
            <span class="raw-info">
              共 {{ (rawLog.total_lines || 0).toLocaleString() }} 行，
              当前 {{ rawLog.start_line }}–{{ rawLog.end_line }}
            </span>
            <el-pagination
              v-if="rawLog.total_lines > pageSize"
              v-model:current-page="rawPage"
              :page-size="pageSize"
              :total="rawLog.total_lines"
              layout="prev, pager, next"
              small
              @current-change="loadRawLog"
            />
          </div>
          <div class="raw-log-container" v-loading="rawLoading">
            <pre>{{ rawLog.content || '暂无日志内容' }}</pre>
          </div>
        </el-tab-pane>

        <el-tab-pane label="日志浏览" name="explorer">
          <div class="explorer-layout" v-loading="explorerFilesLoading">
            <aside class="explorer-tree-panel">
              <div class="explorer-tree-header">
                <el-icon :size="14"><FolderOpened /></el-icon>
                <span>分析文件</span>
                <span class="explorer-tree-count">{{ explorerFiles.length }}</span>
              </div>
              <div class="explorer-tree-body">
                <TreeNode
                  v-for="node in explorerTree"
                  :key="node.path"
                  :node="node"
                  :depth="0"
                  :selected-path="explorerSelectedPath"
                  :expanded-paths="explorerExpandedPaths"
                  @click="handleExplorerNodeClick"
                  @dblclick="handleExplorerNodeClick"
                />
                <div v-if="!explorerTree.length" class="explorer-empty">暂无文件</div>
              </div>
            </aside>
            <section class="explorer-viewer">
              <div class="explorer-viewer-head">
                <div class="explorer-title" :title="selectedExplorerFile?.file_path">
                  <span class="mono">{{ explorerFileTitle || '请选择日志文件' }}</span>
                  <span v-if="selectedExplorerFile" class="explorer-path">{{ compactFilePath(selectedExplorerFile) }}</span>
                </div>
                <div class="explorer-actions">
                  <span class="raw-info">{{ (explorerLog.total_lines || 0).toLocaleString() }} 行</span>
                  <el-button size="small" @click="loadExplorerLog" :disabled="!explorerFileId">
                    <el-icon><Refresh /></el-icon>
                  </el-button>
                </div>
              </div>
              <div class="explorer-log-container" v-loading="explorerLoading">
                <div v-if="explorerLog.lines.length" class="explorer-lines">
                  <div
                    v-for="line in explorerLog.lines"
                    :key="line.no"
                    class="explorer-line"
                    :class="{ error: line.is_error }"
                  >
                    <span class="explorer-line-no">{{ line.no }}</span>
                    <span class="explorer-line-text">{{ line.text }}</span>
                  </div>
                </div>
                <div v-else class="explorer-empty">暂无日志内容</div>
              </div>
            </section>
          </div>
        </el-tab-pane>

        <!-- Failures Tab -->
        <el-tab-pane label="失败事件" name="failures">
          <el-table :data="failures" v-loading="failuresLoading" max-height="600" stripe class="data-table">
            <el-table-column prop="exception_type" label="异常类型" min-width="180" show-overflow-tooltip />
            <el-table-column prop="script_name" label="脚本" min-width="200" show-overflow-tooltip />
            <el-table-column prop="exception_message" label="异常信息" min-width="300" show-overflow-tooltip />
            <el-table-column label="详情" width="80" fixed="right" align="center">
              <template #default="{ row }">
                <el-popover placement="left" :width="600" trigger="click">
                  <template #reference>
                    <el-button link type="primary" size="small">查看</el-button>
                  </template>
                  <pre class="traceback-pre">{{ row.traceback }}</pre>
                </el-popover>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </AppSection>

    <!-- Review Drawer -->
    <ReviewDrawer
      v-model="drawerVisible"
      :file-id="drawerFileId"
      @updated="loadFiles"
    />
  </div>
</template>

<style scoped>
.task-detail {
  max-width: 1600px;
}

.error-msg {
  margin-bottom: var(--space-section);
}

/* ── 重新分析对话框 ── */
.rerun-sub-title {
  font-size: var(--text-small);
  color: var(--text-secondary);
  margin: 16px 0 8px;
}
.rerun-stat {
  text-align: center;
  padding: 10px 4px;
  background: var(--bg-input);
  border-radius: var(--radius-sm);
}
.rerun-stat .num {
  display: block;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.rerun-stat .lbl {
  display: block;
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  margin-top: 2px;
}
.rerun-foot {
  margin-top: 12px;
  font-size: var(--text-small);
  color: var(--text-secondary);
}
.rerun-foot code {
  padding: 1px 4px;
  background: var(--bg-input);
  border-radius: 2px;
  font-family: var(--font-mono);
  font-size: 12px;
}
.form-hint {
  font-size: var(--text-small);
  color: var(--text-secondary);
  margin-top: 4px;
  line-height: 1.5;
}
.form-hint code {
  padding: 0 3px;
  background: var(--bg-input);
  border-radius: 2px;
  font-family: var(--font-mono);
  font-size: 12px;
}

.meta-item {
  font-size: var(--text-small);
  color: var(--text-secondary);
}
.meta-item.mono {
  font-family: var(--font-mono);
  font-size: var(--text-tiny);
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: var(--font-mono);
}

.data-table :deep(.el-table__row) {
  height: var(--table-row-h);
}
.data-table :deep(.el-table__cell) {
  padding-block: var(--table-cell-py);
}

.file-cell {
  font-size: var(--text-small);
  max-width: 360px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}

.unrec-text {
  color: var(--color-warning);
}

.summary-id {
  font-size: var(--text-small);
}

.summary-fail {
  font-size: var(--text-small);
  color: var(--text-primary);
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.muted-dash {
  color: var(--text-muted);
}
.text-muted { color: var(--text-muted); }
.num-ok    { color: var(--color-success); font-variant-numeric: tabular-nums; }
.num-warn  { color: var(--color-warning); font-variant-numeric: tabular-nums; }

/* ── Stat cards ── */
.stat-row {
  margin: 0;
}
.mini-stat {
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-lg);
  text-align: center;
  height: 100%;
}
.mini-stat .mini-stat-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text-primary);
}
.mini-stat .mini-stat-label {
  font-size: var(--text-small);
  color: var(--text-secondary);
  margin-top: var(--space-xs);
}
.mini-stat.error .mini-stat-num   { color: var(--color-error); }
.mini-stat.success .mini-stat-num { color: var(--color-success); }
.mini-stat.warning .mini-stat-num { color: var(--color-warning); }

.mini-stat.clickable {
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.mini-stat.clickable:hover {
  box-shadow: 0 0 0 2px rgba(230, 162, 60, 0.2);
}
.mini-stat.clickable.active {
  box-shadow: 0 0 0 2px var(--color-warning);
}

.results-toolbar {
  margin-bottom: var(--space-md);
  display: flex;
  align-items: center;
}

.raw-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-md);
}

.raw-info {
  font-size: var(--text-small);
  color: var(--text-secondary);
}

.raw-log-container {
  background: #1e1e1e;
  border-radius: var(--radius-md);
  padding: var(--space-lg);
  max-height: 500px;
  overflow: auto;
}

.raw-log-container pre {
  color: #d4d4d4;
  font-family: var(--font-mono);
  font-size: var(--text-body);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.explorer-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  margin-bottom: var(--space-md);
}

.explorer-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.explorer-subbar {
  margin-bottom: var(--space-md);
}

.explorer-option {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}

.explorer-option-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-secondary);
  font-size: var(--text-small);
}

.explorer-log-container {
  background: var(--bg-panel);
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-md) 0;
}

.explorer-line {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  column-gap: var(--space-lg);
  min-height: 22px;
  padding: 1px var(--space-lg);
  font-family: var(--font-mono);
  font-size: var(--text-small);
  line-height: 1.55;
  border-bottom: 1px solid #f3f4f6;
}

.explorer-line:hover {
  background: #f7f8fa;
}

.explorer-line.error {
  background: #fff5f5;
}

.explorer-line-no {
  color: var(--text-secondary);
  text-align: right;
  user-select: none;
}

.explorer-line-text {
  color: var(--text-primary);
  white-space: pre-wrap;
  word-break: break-all;
}

.explorer-empty {
  color: var(--text-secondary);
  padding: var(--space-2xl);
  text-align: center;
}

.explorer-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  min-height: 620px;
  height: min(680px, calc(100vh - 260px));
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.explorer-tree-panel {
  background: var(--bg-panel);
  border-right: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.explorer-tree-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md) var(--space-lg);
  font-size: var(--text-small);
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}

.explorer-tree-count {
  margin-left: auto;
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  font-weight: 400;
}

.explorer-tree-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: var(--space-md) 0;
}

.explorer-viewer {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
}

.explorer-viewer-head {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border-light);
}

.explorer-path {
  display: block;
  margin-top: 2px;
  color: var(--text-secondary);
  font-size: var(--text-tiny);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.explorer-actions {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  flex-shrink: 0;
}

.traceback-pre {
  font-family: var(--font-mono);
  font-size: var(--text-small);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: var(--space-lg);
  border-radius: var(--radius-sm);
  margin: 0;
}

/* ═══ v5：JSON 树视图（按轮次）═══ */
.tree-view-empty {
  padding: var(--space-3xl) 0;
}
.tree-view-hint {
  color: var(--text-secondary);
  font-size: var(--text-small);
  max-width: 480px;
  margin: 0 auto var(--space-lg);
  line-height: 1.6;
}

.tree-inner-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: var(--border-light);
}

.tree-view-toolbar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
  flex-wrap: wrap;
}
.toolbar-label {
  font-size: var(--text-small);
  color: var(--text-secondary);
  font-weight: 500;
}
.toolbar-hint {
  font-size: var(--text-tiny);
  color: var(--text-muted);
  margin-left: auto;
}

.tree-view-split {
  display: grid;
  grid-template-columns: minmax(320px, 32%) 1fr;
  gap: var(--space-md);
  min-height: 540px;
}

.tree-view-tree-panel,
.tree-view-table-panel {
  display: flex;
  flex-direction: column;
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  overflow: hidden;
  min-height: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-md);
  border-bottom: 1px solid var(--border-light);
  background: var(--bg-input);
  font-size: var(--text-small);
  font-weight: 500;
  color: var(--text-primary);
  flex-shrink: 0;
}

.panel-body {
  flex: 1;
  min-height: 0;
  padding: var(--space-md);
  overflow: auto;
}
.tree-scroll {
  padding: var(--space-sm);
}

.empty-text {
  color: var(--text-muted);
  font-size: var(--text-small);
  text-align: center;
  padding: var(--space-2xl) 0;
}

.missing-alert {
  margin-bottom: var(--space-md);
}
.missing-alert .muted-text {
  margin-left: var(--space-sm);
  color: var(--text-secondary);
  font-weight: 400;
}

/* TaskTreeNodeView 内联组件 */
.tnode { font-size: var(--text-small); }
.tnode-line {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding-block: 3px;
  padding-right: var(--space-sm);
  border-radius: var(--radius-sm);
  cursor: pointer;
  user-select: none;
}
.tnode-line.clickable:hover { background: var(--bg-hover); }
.tnode-line.selected {
  background: var(--color-primary);
  color: var(--text-inverse);
}
.tnode-line.selected .tnode-id,
.tnode-line.selected .tnode-meta :deep(.el-tag) {
  color: var(--text-inverse);
  border-color: var(--text-inverse);
}
.tnode-name {
  color: var(--text-primary);
  font-weight: 400;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
  flex: 0 1 auto;
}
.tnode-name.leaf {
  color: var(--color-primary);
  font-weight: 500;
}
.tnode-line.selected .tnode-name.leaf {
  color: var(--text-inverse);
}
.tnode-id {
  color: var(--text-muted);
  font-size: var(--text-tiny);
  flex-shrink: 0;
}
.tnode-meta {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

/* 整体 Tab 聚合统计 */
.agg-stats-row {
  margin-bottom: var(--space-md);
}
.agg-mini-stat {
  text-align: center;
  padding: var(--space-md) var(--space-xs);
  background: var(--bg-input);
  border-radius: var(--radius-md);
  height: 100%;
}
.agg-mini-stat.warning {
  background: #fdf6ec;
  border: 1px solid #faecd8;
}
.agg-num {
  display: block;
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.agg-num.primary { color: var(--color-primary); }
.agg-num.warning { color: var(--color-warning); }
.agg-label {
  display: block;
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  margin-top: 4px;
}
</style>
