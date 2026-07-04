<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { taskApi, browseApi } from '@/api'
import { ElMessageBox } from 'element-plus'
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
  { label: '失败', value: 'failed' },
]

const statusTagType = {
  pending: 'info',
  parsing: 'warning',
  analyzing: '',
  completed: 'success',
  failed: 'danger',
}

const statusLabel = {
  pending: '待处理',
  parsing: '解析中',
  analyzing: '分析中',
  completed: '已完成',
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
        <el-button type="primary" @click="showCreate = true">
          <el-icon><Plus /></el-icon>
          新建任务
        </el-button>
      </template>
    </AppPageHeader>

    <AppSection title="任务" :hint="`共 ${total} 条`">
      <el-table :data="tasks" v-loading="loading" stripe class="data-table">
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
</style>
