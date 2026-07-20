<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { taskApi, browseApi, analysisApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  VideoPlay, CircleCheck, Warning, Refresh, ArrowDown,
} from '@element-plus/icons-vue'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'

const router = useRouter()

const tasks = ref([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const statusFilter = ref('')

// ── Create dialog ──
const showCreate = ref(false)
let s3ConfigCache = null

async function prefetchS3Config() {
  if (s3ConfigCache) return s3ConfigCache
  try {
    const { data } = await browseApi.s3Config()
    s3ConfigCache = data
    return data
  } catch { return null }
}

async function onSourceTypeChange(type) {
  if (type === 's3') {
    const cfg = await prefetchS3Config()
    if (cfg) {
      if (!createForm.value.bucket) createForm.value.bucket = cfg.bucket
      if (!createForm.value.prefix) createForm.value.prefix = cfg.prefix
    }
  }
}

const createForm = ref({
  name: '',
  source_type: 'upload',
  parser_type: 'text',
  log_format_pattern: '',
  bucket: '',
  prefix: '',
  package_version: '',
  automation_task_id: '',
  node_id: '',
  task_block_id: '',
})
const createLoading = ref(false)

// ── Filters ──
const statusOptions = [
  { label: '全部', value: '' },
  { label: '待处理', value: 'pending' },
  { label: '解析中', value: 'parsing' },
  { label: '分析中', value: 'analyzing' },
  { label: '已完成', value: 'completed' },
  { label: '完成但有告警', value: 'completed_with_warnings' },
  { label: '失败', value: 'failed' },
]

const statusTagType = {
  pending: 'info',
  parsing: 'warning',
  analyzing: '',
  completed: 'success',
  completed_with_warnings: 'warning',
  failed: 'danger',
}

const statusLabel = {
  pending: '待处理',
  parsing: '解析中',
  analyzing: '分析中',
  completed: '已完成',
  completed_with_warnings: '完成但有告警',
  failed: '失败',
}

async function loadTasks() {
  loading.value = true
  try {
    const params = { limit: 50, offset: (currentPage.value - 1) * 50 }
    if (statusFilter.value) params.status = statusFilter.value
    const { data } = await taskApi.list(params)
    tasks.value = Array.isArray(data) ? data : []
    total.value = tasks.value.length
  } finally {
    loading.value = false
  }
}

async function handleCreate() {
  createLoading.value = true
  try {
    const f = createForm.value
    const formData = new FormData()
    formData.append('name', f.name)
    formData.append('source_type', f.source_type)
    formData.append('parser_type', f.parser_type)
    if (f.log_format_pattern) formData.append('log_format_pattern', f.log_format_pattern)

    if (f.source_type === 's3') {
      if (f.bucket) formData.append('bucket', f.bucket)
      if (f.prefix) formData.append('prefix', f.prefix)
      if (f.package_version) formData.append('package_version', f.package_version)
      formData.append('automation_task_id', f.automation_task_id)
      formData.append('node_id', f.node_id || '')
      formData.append('task_block_id', f.task_block_id || '')
    }

    await taskApi.create(formData)
    showCreate.value = false
    createForm.value = { name: '', source_type: 'upload', parser_type: 'text', log_format_pattern: '',
      bucket: '', prefix: '', package_version: '', automation_task_id: '', node_id: '', task_block_id: '' }
    await loadTasks()
  } finally {
    createLoading.value = false
  }
}

async function handleDelete(task) {
  try {
    await ElMessageBox.confirm(
      `确定要删除任务 "${task.name}" 吗？此操作不可撤销。`,
      '确认删除',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
    )
    await taskApi.delete(task.id)
    await loadTasks()
  } catch {}
}

function openTask(task) {
  router.push(`/tasks/${task.id}`)
}

// ════════════════════════════════════════════════════════════════
// 批量启动 / 重分析（v6）
// ════════════════════════════════════════════════════════════════

const tableRef = ref(null)
const selectedTaskIds = ref([])  // 当前勾选的 task id 集合
const selectedRows = ref([])     // 完整行对象（用于细分按 status 启动/重分析）

const batchSubmitting = ref(false)
const batchResultVisible = ref(false)
const batchResult = ref(null)
const batchResultAction = ref('start')  // 'start' | 'rerun' — 决定结果 dialog 标题

// 表格里能勾的任务状态：pending / failed / completed 都是合法入口
//   pending + failed → 启动分析；completed + failed → 重新分析
// 其他状态（parsing / analyzing / fetched）正忙，不能批量触发。
function isActionable(task) {
  return task && ['pending', 'failed', 'completed', 'completed_with_warnings'].includes(task.status)
}

function isStartable(task) {
  return task && (task.status === 'pending' || task.status === 'failed')
}

function isRerunable(task) {
  return task && ['completed', 'completed_with_warnings', 'failed'].includes(task.status)
}

const startableCount = computed(() => tasks.value.filter(isStartable).length)
const rerunableCount = computed(() => tasks.value.filter(isRerunable).length)

function onSelectionChange(rows) {
  selectedRows.value = rows
  // 只保留可操作的（防 race：清空当前页面外的 selection 残留）
  selectedTaskIds.value = rows.filter(isActionable).map((r) => r.id)
}

function selectAllStartable() {
  if (!tableRef.value) return
  const rows = tasks.value.filter(isStartable)
  rows.forEach((row) => {
    tableRef.value.toggleRowSelection(row, true)
  })
  ElMessage.success(`已选中 ${rows.length} 个可启动任务`)
}

function selectAllRerunable() {
  if (!tableRef.value) return
  const rows = tasks.value.filter(isRerunable)
  rows.forEach((row) => {
    tableRef.value.toggleRowSelection(row, true)
  })
  ElMessage.success(`已选中 ${rows.length} 个可重分析任务`)
}

function clearSelection() {
  if (!tableRef.value) return
  tableRef.value.clearSelection()
  selectedTaskIds.value = []
}

async function handleBatchRun() {
  const targets = selectedRows.value.filter(isStartable)
  if (targets.length === 0) {
    ElMessage.warning('当前选择中没有可启动的任务（仅 pending/failed 可启动）')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将启动 ${targets.length} 个任务的日志解析与分析。\n` +
      `已完成的或正在运行的会被自动跳过。\n\n继续？`,
      '批量启动分析',
      { type: 'info', confirmButtonText: '启动', cancelButtonText: '取消' },
    )
  } catch { return }

  batchSubmitting.value = true
  try {
    const { data } = await analysisApi.runBatch(targets.map((t) => t.id))
    batchResult.value = data
    batchResultAction.value = 'start'
    batchResultVisible.value = true
    const started = data.started?.length || 0
    const skipped = data.skipped?.length || 0
    const errors = data.errors?.length || 0
    if (errors > 0) {
      ElMessage.warning(`启动 ${started} 个，${skipped} 跳过，${errors} 个任务不存在`)
    } else if (skipped > 0) {
      ElMessage.success(`启动 ${started} 个，${skipped} 个已跳过（状态不允许重复启动）`)
    } else {
      ElMessage.success(`已启动 ${started} 个任务`)
    }
    await loadTasks()
    clearSelection()
  } finally {
    batchSubmitting.value = false
  }
}

async function handleBatchRerun() {
  const targets = selectedRows.value.filter(isRerunable)
  if (targets.length === 0) {
    ElMessage.warning('当前选择中没有可重分析的任务（仅 completed/failed 可重新分析）')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将清空 ${targets.length} 个任务的现有日志条目 / 失败事件 / 分析结果 / 反馈，\n` +
      `然后重新跑完整分析流水线（应用最新解析 / 检测 / 规则代码）。\n\n` +
      `默认会重置所有任务的人工审核结论（如需保留，可在 TaskDetail 详情页单任务模式勾选）。\n\n` +
      `此操作不可逆，是否继续？`,
      '批量重新分析',
      {
        type: 'warning',
        confirmButtonText: '重分析',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--warning',
      },
    )
  } catch { return }

  batchSubmitting.value = true
  try {
    const { data } = await analysisApi.rerunBatch(targets.map((t) => t.id))
    batchResult.value = data
    batchResultAction.value = 'rerun'
    batchResultVisible.value = true
    const started = data.started?.length || 0
    const skipped = data.skipped?.length || 0
    const errors = data.errors?.length || 0
    if (errors > 0) {
      ElMessage.warning(`重分析 ${started} 个，${skipped} 跳过，${errors} 个任务不存在`)
    } else if (skipped > 0) {
      ElMessage.success(`重分析 ${started} 个，${skipped} 个已跳过（状态不允许重分析）`)
    } else {
      ElMessage.success(`已对 ${started} 个任务启动重新分析`)
    }
    await loadTasks()
    clearSelection()
  } finally {
    batchSubmitting.value = false
  }
}

onMounted(loadTasks)
</script>

<template>
  <div class="page task-list">
    <AppPageHeader
      title="任务列表"
      subtitle="创建分析任务、查看运行状态、跳转查看详细分析结果"
    >
      <template #actions>
        <el-select
          v-model="statusFilter"
          placeholder="按状态筛选"
          clearable
          style="width: 160px"
          @change="loadTasks"
        >
          <el-option v-for="opt in statusOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </el-select>
        <el-dropdown
          trigger="click"
          :disabled="selectedTaskIds.length === 0"
          @command="(cmd) => cmd === 'start' ? handleBatchRun() : handleBatchRerun()"
        >
          <el-button
            type="success"
            :loading="batchSubmitting"
            :disabled="selectedTaskIds.length === 0"
          >
            <el-icon><VideoPlay /></el-icon>
            批量操作
            <el-badge
              v-if="selectedTaskIds.length > 0"
              :value="selectedTaskIds.length"
              :max="99"
              type="warning"
              class="batch-badge"
            />
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="start" :disabled="selectedRows.filter(isStartable).length === 0">
                <el-icon><VideoPlay /></el-icon>
                启动分析（<strong>{{ selectedRows.filter(isStartable).length }}</strong>）
              </el-dropdown-item>
              <el-dropdown-item command="rerun" :disabled="selectedRows.filter(isRerunable).length === 0">
                <el-icon><Refresh /></el-icon>
                重新分析（<strong>{{ selectedRows.filter(isRerunable).length }}</strong>）
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button @click="showCreate = true">
          <el-icon><Plus /></el-icon>
          新建任务
        </el-button>
      </template>
    </AppPageHeader>

    <AppSection
      title="任务"
      :hint="`共 ${total} 条 / 可启动 ${startableCount} / 可重分析 ${rerunableCount}`"
    >
      <div class="batch-bar" v-if="startableCount + rerunableCount > 0 || selectedTaskIds.length > 0">
        <el-tooltip content="勾选所有 pending / failed（可启动分析）" placement="top">
          <el-button size="small" @click="selectAllStartable">
            <el-icon><CircleCheck /></el-icon>
            全选可启动（{{ startableCount }}）
          </el-button>
        </el-tooltip>
        <el-tooltip content="勾选所有 completed / failed（可重新分析）" placement="top">
          <el-button size="small" type="warning" plain @click="selectAllRerunable">
            <el-icon><Refresh /></el-icon>
            全选可重分析（{{ rerunableCount }}）
          </el-button>
        </el-tooltip>
        <el-button
          size="small"
          type="info"
          plain
          :disabled="selectedTaskIds.length === 0"
          @click="clearSelection"
        >
          清空选择
        </el-button>
        <span class="batch-hint">
          当前已选 <strong>{{ selectedTaskIds.length }}</strong> 个任务
          <template v-if="selectedTaskIds.length > 0">
            （可启动 <strong>{{ selectedRows.filter(isStartable).length }}</strong>
            / 可重分析 <strong>{{ selectedRows.filter(isRerunable).length }}</strong>）
          </template>
        </span>
      </div>
      <el-table
        ref="tableRef"
        :data="tasks"
        v-loading="loading"
        stripe
        class="data-table"
        row-key="id"
        @selection-change="onSelectionChange"
      >
        <el-table-column
          type="selection"
          width="44"
          :selectable="(row) => isActionable(row)"
          reserve-selection
        />
        <el-table-column label="任务名称" min-width="220">
          <template #header>
            <el-tooltip content="点击任务名进入详情页" placement="top">
              <span>任务名称</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <el-link type="primary" @click="openTask(row)">{{ row.name }}</el-link>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #header>
            <el-tooltip content="任务当前生命周期阶段" placement="top">
              <span>状态</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <el-tag :type="statusTagType[row.status]" size="small">
              {{ statusLabel[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="90">
          <template #header>
            <el-tooltip content="数据来源：本地上传 / S3 (RustFS)" placement="top">
              <span>来源</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <el-tag size="small" :type="row.source_type === 's3' ? '' : 'info'">
              {{ row.source_type === 's3' ? 'S3' : '上传' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="S3 路径" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <span v-if="row.source_type === 's3'" class="s3-path">
              {{ row.package_version }}/{{ row.automation_task_id }}/{{ row.node_id }}/{{ row.task_block_id }}
            </span>
            <span v-else class="text-muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="日志行数" width="100" align="right">
          <template #default="{ row }">
            <span class="num">{{ (row.total_entries || 0).toLocaleString() }}</span>
          </template>
        </el-table-column>
        <el-table-column label="失败/已分类/未识别" min-width="180" align="center">
          <template #header>
            <el-tooltip content="三类计数：失败事件 / 已分类 / 未识别" placement="top">
              <span>失败/已分类/未识别</span>
            </el-tooltip>
          </template>
          <template #default="{ row }">
            <div class="counts-cell">
              <span class="count-item err">{{ row.failure_count || 0 }}</span>
              <span class="sep">/</span>
              <span class="count-item ok">{{ row.classified_count || 0 }}</span>
              <span class="sep">/</span>
              <span class="count-item unk">{{ row.unrecognized_count || 0 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="text-muted">{{ row.created_at }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </AppSection>

    <!-- Batch run / rerun result dialog -->
    <el-dialog
      v-model="batchResultVisible"
      :title="
        batchResult
          ? (batchResultAction === 'rerun'
              ? `批量重新分析结果 — 共 ${batchResult.total} 个`
              : `批量启动结果 — 共 ${batchResult.total} 个`)
          : '批量操作结果'
      "
      width="640px"
    >
      <template v-if="batchResult">
        <el-row :gutter="12" style="margin-bottom: 16px">
          <el-col :span="8">
            <div class="s-stat">
              <span class="s-num success">{{ batchResult.started?.length || 0 }}</span>
              <span class="s-label">
                {{ batchResultAction === 'rerun' ? '已重新分析' : '已启动' }}
              </span>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="s-stat">
              <span class="s-num warning">{{ batchResult.skipped?.length || 0 }}</span>
              <span class="s-label">已跳过</span>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="s-stat">
              <span class="s-num danger">{{ batchResult.errors?.length || 0 }}</span>
              <span class="s-label">失败（task 不存在）</span>
            </div>
          </el-col>
        </el-row>

        <template v-if="batchResult.skipped?.length">
          <h4 class="result-section-title">
            <el-icon><Warning /></el-icon>
            跳过的任务（状态不允许{{ batchResultAction === 'rerun' ? '重分析' : '重复启动' }}）
          </h4>
          <div class="skipped-tags">
            <el-tag
              v-for="item in batchResult.skipped"
              :key="item.task_id"
              size="small"
              type="warning"
              style="margin: 2px"
            >
              {{ item.name }}（{{ item.status }}）
            </el-tag>
          </div>
        </template>

        <template v-if="batchResult.errors?.length">
          <h4 class="result-section-title">
            <el-icon><Warning /></el-icon> 出错的 task_id
          </h4>
          <el-table :data="batchResult.errors" size="small" max-height="180">
            <el-table-column prop="task_id" label="Task ID" min-width="180" />
            <el-table-column prop="reason" label="原因" min-width="160" />
          </el-table>
        </template>

        <template v-if="batchResultAction === 'rerun' && batchResult.deleted?.length">
          <h4 class="result-section-title">各任务清理数据明细</h4>
          <el-table :data="batchResult.deleted" size="small" max-height="240">
            <el-table-column prop="name" label="任务名" min-width="180" show-overflow-tooltip />
            <el-table-column label="日志条目" width="80" align="center">
              <template #default="{ row }">
                {{ row.deleted?.log_entries ?? 0 }}
              </template>
            </el-table-column>
            <el-table-column label="失败事件" width="80" align="center">
              <template #default="{ row }">
                {{ row.deleted?.failure_events ?? 0 }}
              </template>
            </el-table-column>
            <el-table-column label="分析结果" width="80" align="center">
              <template #default="{ row }">
                {{ row.deleted?.analysis_results ?? 0 }}
              </template>
            </el-table-column>
            <el-table-column label="反馈" width="60" align="center">
              <template #default="{ row }">
                {{ row.deleted?.feedback ?? 0 }}
              </template>
            </el-table-column>
          </el-table>
        </template>

        <template
          v-if="!batchResult.skipped?.length && !batchResult.errors?.length && batchResultAction === 'start'"
        >
          <el-alert
            :title="`全部 ${batchResult.total} 个任务已成功启动后台分析`"
            type="success"
            :closable="false"
          />
        </template>
        <template
          v-if="!batchResult.skipped?.length && !batchResult.errors?.length && batchResultAction === 'rerun'"
        >
          <el-alert
            :title="`全部 ${batchResult.total} 个任务已成功启动重新分析（清旧数据 + 重跑）`"
            type="success"
            :closable="false"
          />
        </template>
      </template>
      <template #footer>
        <el-button type="primary" @click="batchResultVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- Create Dialog -->
    <el-dialog v-model="showCreate" title="新建分析任务" width="520px" top="8vh">
      <el-form :model="createForm" label-width="110px" class="create-form">
        <el-form-item label="任务名称" required>
          <el-input v-model="createForm.name" placeholder="例如：2026-06-04 回归测试日志" />
        </el-form-item>
        <el-form-item label="数据来源">
          <el-radio-group v-model="createForm.source_type" @change="onSourceTypeChange">
            <el-radio value="upload">本地上传</el-radio>
            <el-radio value="s3">S3 / RustFS</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="createForm.source_type === 's3'">
          <div class="s3-grid">
            <el-form-item label="Bucket & Prefix">
              <div class="input-pair">
                <el-input v-model="createForm.bucket" placeholder="bucket" class="half" />
                <span class="sep-slash">/</span>
                <el-input v-model="createForm.prefix" placeholder="prefix" class="half" />
              </div>
            </el-form-item>
            <el-form-item label="Package Ver" class="compact">
              <el-input v-model="createForm.package_version" placeholder="1.2.3" />
            </el-form-item>
            <el-form-item label="Task ID" class="compact" required>
              <el-input v-model="createForm.automation_task_id" placeholder="nightly_regression" />
            </el-form-item>
            <el-form-item label="Node ID" class="compact opt">
              <el-input v-model="createForm.node_id" placeholder="默认：所有节点" />
            </el-form-item>
            <el-form-item label="Task Block" class="compact opt">
              <el-input v-model="createForm.task_block_id" placeholder="默认：所有 block" />
            </el-form-item>
          </div>
          <div class="s3-path-preview" v-if="createForm.bucket && createForm.automation_task_id">
            <el-icon :size="12"><Link /></el-icon>
            s3://{{ createForm.bucket }}/{{ createForm.prefix }}{{ createForm.prefix ? '/' : '' }}.../{{ createForm.automation_task_id }}/{{ createForm.node_id || '*' }}/{{ createForm.task_block_id || '*' }}/upload/
          </div>
        </template>

        <el-form-item label="解析类型">
          <el-radio-group v-model="createForm.parser_type">
            <el-radio value="text">文本格式</el-radio>
            <el-radio value="html">HTML 格式</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="自定义格式">
          <el-input v-model="createForm.log_format_pattern" placeholder="可选：自定义日志行正则表达式" type="textarea" :rows="2" />
          <div class="form-tip">默认：[timestamp] [LEVEL] [script] message</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="handleCreate" :loading="createLoading">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.task-list {
  max-width: 1400px;
}

.data-table :deep(.el-table__row) {
  height: var(--table-row-h);
}
.data-table :deep(.el-table__cell) {
  padding-block: var(--table-cell-py);
}

.counts-cell {
  font-family: var(--font-mono);
  font-size: var(--text-small);
  display: inline-flex;
  align-items: center;
  gap: 2px;
}
.count-item.err { color: var(--color-error); }
.count-item.ok  { color: var(--color-success); }
.count-item.unk { color: var(--color-warning); }
.sep { color: var(--border-color); margin: 0 2px; }

.s3-path {
  font-family: var(--font-mono);
  font-size: var(--text-small);
  color: var(--text-secondary);
}
.text-muted { color: var(--text-muted); }
.num {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
}

.form-tip {
  font-size: var(--text-small);
  color: var(--text-muted);
  margin-top: var(--space-xs);
}

/* ── S3 compact form ── */
.create-form :deep(.el-form-item) { margin-bottom: var(--space-card); }
.s3-grid :deep(.el-form-item.compact) { margin-bottom: var(--space-sm); }
.s3-grid :deep(.el-form-item.compact .el-form-item__label) { font-size: var(--text-small); }
.s3-grid :deep(.el-form-item.opt .el-form-item__label) { color: var(--text-muted); }

.input-pair {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  width: 100%;
}
.input-pair .half { flex: 1; }
.sep-slash { color: var(--text-muted); font-size: var(--text-body); flex-shrink: 0; }

.s3-path-preview {
  margin-top: var(--space-sm);
  padding: var(--space-sm) var(--space-lg);
  background: var(--bg-input);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 批量启动 ── */
.batch-bar {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
  flex-wrap: wrap;
}
.batch-hint {
  font-size: var(--text-small);
  color: var(--text-secondary);
}
.batch-badge {
  margin-left: 4px;
}
.batch-badge :deep(.el-badge__content) {
  transform: translateY(-2px);
}

.s-stat {
  text-align: center;
  padding: var(--space-md) var(--space-xs);
  background: var(--bg-input);
  border-radius: var(--radius-md);
}
.s-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.s-label {
  display: block;
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  margin-top: 2px;
}
.s-num.success { color: var(--color-success); }
.s-num.warning { color: var(--color-warning); }
.s-num.danger  { color: var(--color-error); }

.skipped-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  max-height: 120px;
  overflow-y: auto;
}
.result-section-title {
  font-size: var(--text-small);
  color: var(--text-secondary);
  margin: var(--space-md) 0 var(--space-xs);
  display: flex;
  align-items: center;
  gap: 4px;
}
</style>
