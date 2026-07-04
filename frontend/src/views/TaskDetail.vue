<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { taskApi, logApi, analysisApi } from '@/api'
import ReviewDrawer from '@/components/ReviewDrawer.vue'
import TreeNode from '@/components/TreeNode.vue'

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
const fallbackFilter = ref(null)  // null=全部 true=仅未识别 false=仅已识别
const summaryFilter = ref('')     // ''=全部 'success'|'failed'|'blocked'

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

function handleTabChange(tab) {
  if (tab === 'files' && files.value.length === 0) loadFiles()
  if (tab === 'raw' && rawLog.value.total_lines === 0) loadRawLog()
  if (tab === 'explorer') loadExplorerFiles()
  if (tab === 'failures' && failures.value.length === 0) loadFailures()
}

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
</script>

<template>
  <div class="task-detail" v-loading="loading">
    <!-- Header -->
    <div class="page-header">
      <div>
        <h2>{{ task?.name || '加载中...' }}</h2>
        <div class="task-meta">
          <el-tag :type="statusTag(task?.status)">{{ statusLabel(task?.status) }}</el-tag>
          <el-tag size="small" :type="task?.source_type === 's3' ? '' : 'info'" style="margin-left:8px">
            {{ task?.source_type === 's3' ? 'S3' : '本地上传' }}
          </el-tag>
          <span v-if="task?.source_type === 's3'" class="meta-item mono">
            {{ task?.s3_path || task?.package_version + '/' + task?.automation_task_id + '/' + task?.node_id + '/' + task?.task_block_id }}
          </span>
          <span class="meta-item">创建: {{ task?.created_at }}</span>
          <span v-if="task?.completed_at" class="meta-item">完成: {{ task?.completed_at }}</span>
        </div>
        <div v-if="task?.error_message" class="error-msg">
          <el-alert :title="task.error_message" type="error" :closable="false" />
        </div>
      </div>
      <div class="header-actions">
        <el-button
          v-if="canStartTask"
          type="primary"
          @click="handleRun"
          :disabled="!task || (task.status !== 'pending' && task.status !== 'failed')"
        >
          <el-icon><VideoPlay /></el-icon>
          运行分析
        </el-button>
      </div>
    </div>

    <!-- Stats -->
    <el-row :gutter="16" class="stats-row" v-if="task">
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
        <div class="mini-stat warning" :class="{ active: fallbackFilter === true }" @click="filterUnrecognized">
          <span class="mini-stat-num">{{ fileStats.unrecognized }}</span>
          <span class="mini-stat-label">未识别</span>
        </div>
      </el-col>
    </el-row>

    <!-- Content Tabs -->
    <el-card style="margin-top: 16px">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <!-- Analyzed Files Tab -->
        <el-tab-pane label="分析结果" name="files">
          <div class="results-toolbar">
            <el-select v-model="statusFilter" placeholder="审核状态" clearable style="width: 140px" @change="loadFiles">
              <el-option label="待审核" value="pending" />
              <el-option label="已确认" value="confirmed" />
              <el-option label="已覆盖" value="overridden" />
            </el-select>
            <el-select v-model="typeFilter" placeholder="文件类型" clearable style="width: 140px; margin-left: 8px" @change="loadFiles">
              <el-option label="测试套" value="testsuite" />
              <el-option label="测试用例" value="testcase" />
              <el-option label="任务日志" value="task_log" />
            </el-select>
            <el-select v-model="fallbackFilter" placeholder="识别状态" clearable style="width: 140px; margin-left: 8px" @change="loadFiles">
              <el-option label="仅未识别" :value="true" />
              <el-option label="仅已识别" :value="false" />
            </el-select>
            <el-select v-model="summaryFilter" placeholder="原始结果" clearable style="width: 140px; margin-left: 8px" @change="loadFiles">
              <el-option label="Success" value="success" />
              <el-option label="Failed" value="failed" />
              <el-option label="Blocked" value="blocked" />
            </el-select>
            <el-button style="margin-left: 8px" @click="loadFiles">
              <el-icon><Refresh /></el-icon>
            </el-button>
          </div>
          <el-table :data="files" v-loading="filesLoading" max-height="600" stripe>
            <el-table-column label="日志文件" min-width="240">
              <template #default="{ row }">
                <span class="mono file-cell" :title="row.file_path">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="类型" width="110">
              <template #default="{ row }">
                <el-tag size="small" :type="row.file_type === 'testsuite' ? 'success' : row.file_type === 'testcase' ? '' : 'info'">
                  {{ fileTypeLabel(row.file_type) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="原始结果" width="100">
              <template #default="{ row }">
                <el-tag v-if="row.summary_report" size="small" :type="summaryStatusTag(row)">
                  {{ summaryResult(row) }}
                </el-tag>
                <span v-else class="muted-dash">—</span>
              </template>
            </el-table-column>
            <el-table-column label="用例/套件" min-width="180">
              <template #default="{ row }">
                <template v-if="summaryIdentity(row)">
                  <div class="mono summary-id">{{ summaryIdentity(row).id }}</div>
                </template>
                <span v-else class="muted-dash">—</span>
              </template>
            </el-table-column>
            <el-table-column label="失败原因" min-width="220">
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
            <el-table-column label="最终结论（根因）" min-width="200">
              <template #default="{ row }">
                <span :class="{ 'unrec-text': !row.final_category && row.failure_count > 0 }">
                  {{ finalCategoryText(row) }}
                </span>
                <el-tag v-if="row.is_overridden" size="small" type="primary" style="margin-left: 6px">人工覆盖</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="90">
              <template #default="{ row }">
                <span v-if="row.is_overridden || !row.primary" style="color: #909399">—</span>
                <span v-else :style="{ color: row.primary.confidence >= 0.7 ? '#67c23a' : '#e6a23c' }">
                  {{ (row.primary.confidence * 100).toFixed(0) }}%
                </span>
              </template>
            </el-table-column>
            <el-table-column label="匹配规则" width="160" show-overflow-tooltip>
              <template #default="{ row }">
                <span style="font-size: 12px">{{ row.is_overridden ? '—' : (row.primary?.rule_name || '—') }}</span>
              </template>
            </el-table-column>
            <el-table-column label="审核状态" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="reviewBadge(row.review_status).type">
                  {{ reviewBadge(row.review_status).label }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="" width="130" fixed="right">
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
          <div v-if="false" class="explorer-toolbar">
            <el-select
              v-model="explorerFileId"
              filterable
              placeholder="选择日志文件"
              style="width: 420px"
              :loading="explorerFilesLoading"
              @change="handleExplorerFileChange"
            >
              <el-option
                v-for="file in explorerFiles"
                :key="file.id"
                :label="summaryIdentity(file)?.id || file.name"
                :value="file.id"
              >
                <div class="explorer-option">
                  <span class="mono">{{ summaryIdentity(file)?.id || file.name }}</span>
                  <el-tag size="small" :type="file.file_type === 'testsuite' ? 'success' : file.file_type === 'testcase' ? '' : 'info'">
                    {{ fileTypeLabel(file.file_type) }}
                  </el-tag>
                  <span class="explorer-option-name">{{ file.name }}</span>
                </div>
              </el-option>
            </el-select>
            <span class="raw-info explorer-title" :title="selectedExplorerFile?.file_path">
              {{ explorerFileTitle }}
            </span>
            <el-pagination
              v-if="explorerLog.total_lines > pageSize"
              v-model:current-page="explorerPage"
              :page-size="pageSize"
              :total="explorerLog.total_lines"
              layout="prev, pager, next"
              small
              @current-change="loadExplorerLog"
            />
          </div>
          <div v-if="false" class="raw-toolbar explorer-subbar">
            <span class="raw-info">
              共 {{ (explorerLog.total_lines || 0).toLocaleString() }} 行，
              当前 {{ explorerLog.start_line }}–{{ explorerLog.end_line }}
            </span>
            <el-button size="small" @click="loadExplorerLog" :disabled="!explorerFileId">
              <el-icon><Refresh /></el-icon>
            </el-button>
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
          <el-table :data="failures" v-loading="failuresLoading" max-height="600" stripe>
            <el-table-column prop="exception_type" label="异常类型" width="180" />
            <el-table-column prop="script_name" label="脚本" width="200" />
            <el-table-column prop="exception_message" label="异常信息" min-width="300" show-overflow-tooltip />
            <el-table-column label="详情" width="80" fixed="right">
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
    </el-card>

    <!-- Review Drawer -->
    <ReviewDrawer
      v-model="drawerVisible"
      :file-id="drawerFileId"
      @updated="loadFiles"
    />
  </div>
</template>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 8px;
}

.meta-item {
  font-size: 13px;
  color: #909399;
}
.meta-item.mono {
  font-family: var(--font-mono);
  font-size: 12px;
}

.mono {
  font-family: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', monospace;
}

.file-cell {
  font-size: 12.5px;
}

.unrec-text {
  color: #e6a23c;
}

.summary-id {
  font-size: 12px;
}

.summary-desc {
  font-size: 11.5px;
  color: #909399;
  line-height: 1.3;
}

.summary-fail {
  font-size: 12px;
  color: #606266;
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.muted-dash {
  color: #c0c4cc;
}

.error-msg {
  margin-top: 12px;
  max-width: 600px;
}

.stats-row {
  margin-top: 16px;
}

.mini-stat {
  background: #fff;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 16px;
  text-align: center;
}

.mini-stat .mini-stat-num {
  display: block;
  font-size: 24px;
  font-weight: 700;
}

.mini-stat .mini-stat-label {
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}

.mini-stat.error .mini-stat-num { color: #f56c6c; }
.mini-stat.success .mini-stat-num { color: #67c23a; }
.mini-stat.warning .mini-stat-num { color: #e6a23c; }

.mini-stat.warning {
  cursor: pointer;
  border-radius: 6px;
  transition: box-shadow 0.15s;
}
.mini-stat.warning:hover {
  box-shadow: 0 0 0 2px #e6a23c33;
}
.mini-stat.warning.active {
  box-shadow: 0 0 0 2px #e6a23c;
}

.raw-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.raw-info {
  font-size: 13px;
  color: #909399;
}

.raw-log-container {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 16px;
  max-height: 500px;
  overflow: auto;
}

.raw-log-container pre {
  color: #d4d4d4;
  font-family: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.explorer-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.explorer-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.explorer-subbar {
  margin-bottom: 8px;
}

.explorer-option {
  display: flex;
  align-items: center;
  gap: 8px;
}

.explorer-option-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: #909399;
  font-size: 12px;
}

.explorer-log-container {
  background: #fff;
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 0;
}

.explorer-line {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  column-gap: 12px;
  min-height: 22px;
  padding: 1px 14px;
  font-family: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12.5px;
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
  color: #909399;
  text-align: right;
  user-select: none;
}

.explorer-line-text {
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
}

.explorer-empty {
  color: #909399;
  padding: 24px;
  text-align: center;
}

.explorer-toolbar,
.explorer-subbar {
  display: none;
}

.explorer-layout {
  display: grid;
  grid-template-columns: 300px minmax(0, 1fr);
  min-height: 620px;
  height: min(680px, calc(100vh - 260px));
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  overflow: hidden;
}

.explorer-tree-panel {
  background: var(--bg-panel, #fff);
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}

.explorer-tree-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  border-bottom: 1px solid #e4e7ed;
  flex-shrink: 0;
}

.explorer-tree-count {
  margin-left: auto;
  font-size: 11px;
  color: #909399;
  font-weight: 400;
}

.explorer-tree-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 0;
}

.explorer-viewer {
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.explorer-viewer-head {
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 10px;
  border-bottom: 1px solid #e4e7ed;
}

.explorer-path {
  display: block;
  margin-top: 2px;
  color: #909399;
  font-size: 11px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.explorer-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.traceback-pre {
  font-family: 'Cascadia Code', 'JetBrains Mono', monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 400px;
  overflow: auto;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px;
  border-radius: 4px;
  margin: 0;
}

.results-toolbar {
  margin-bottom: 12px;
  display: flex;
  align-items: center;
}
</style>
