<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reviewApi } from '@/api'
import ReviewDrawer from '@/components/ReviewDrawer.vue'
import HighValueDialog from '@/components/HighValueDialog.vue'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'

// ── Tabs ──
const activeTab = ref('pending')

// ── Data ──
const items = ref([])
const loading = ref(false)

// ── Review drawer ──
const drawerVisible = ref(false)
const drawerFileId = ref(null)

// ── High-value dialog ──
const hvVisible = ref(false)
const hvFileId = ref(null)
const hvRecordId = ref(null)
const hvCurrentNotes = ref('')

// ── Pagination ──
const page = ref(1)
const pageSize = 20

// ── Load ──
async function load() {
  loading.value = true
  try {
    const params = { limit: pageSize, offset: (page.value - 1) * pageSize }
    let res
    if (activeTab.value === 'pending') {
      res = await reviewApi.overridden(params)
    } else if (activeTab.value === 'archived') {
      res = await reviewApi.archived(params)
    } else {
      res = await reviewApi.highValueList(params)
    }
    items.value = res.data || []
  } finally {
    loading.value = false
  }
}

onMounted(load)

function onTabChange() {
  page.value = 1
  load()
}

// ── Actions ──
function showDetail(fileId) {
  drawerFileId.value = fileId
  drawerVisible.value = true
}

function onDrawerClosed() {
  drawerFileId.value = null
}

function onDrawerUpdated() {
  load()
}

async function handleReset(item) {
  try {
    await ElMessageBox.confirm('确定要驳回此审核结论，将其重置为未审核状态吗？', '驳回确认', { type: 'warning' })
    await reviewApi.reset(item.id)
    ElMessage.success('已重置为待审核')
    load()
  } catch { /* cancelled */ }
}

async function handleArchive(item) {
  try {
    await reviewApi.archive(item.id)
    ElMessage.success('已归档')
    load()
  } catch { /* noop */ }
}

async function handleUnarchive(item) {
  try {
    await reviewApi.unarchive(item.id)
    ElMessage.success('已取消归档')
    load()
  } catch { /* noop */ }
}

function openHighValue(item) {
  hvFileId.value = item.id
  hvRecordId.value = null
  hvCurrentNotes.value = ''
  hvVisible.value = true
}

function editHighValueNotes(item) {
  hvFileId.value = item.id
  hvRecordId.value = item.high_value?.id || null
  hvCurrentNotes.value = item.high_value?.notes || ''
  hvVisible.value = true
}

async function onHighValueSaved() {
  hvVisible.value = false
  load()
}

// ── Formatting ──
function catLabel(cat) {
  if (!cat) return '无法识别'
  return cat.parent_name ? `${cat.parent_name} / ${cat.name}` : cat.name
}

function typeLabel(ft) {
  return ft === 'testsuite' ? '测试套' : ft === 'testcase' ? '测试用例' : '任务日志'
}

function fmtDate(d) {
  if (!d) return ''
  const dt = new Date(d)
  return dt.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <div class="page review-dashboard">
    <AppPageHeader
      title="审核复盘"
      subtitle="查看人工覆盖的审核结论，提取反馈信息"
    />

    <AppSection flush>
      <el-tabs v-model="activeTab" @tab-change="onTabChange">
        <el-tab-pane label="待处理" name="pending" />
        <el-tab-pane label="已归档" name="archived" />
        <el-tab-pane label="高价值" name="high-value" />
      </el-tabs>

      <div v-loading="loading" class="card-list">
        <el-empty v-if="!items.length && !loading" description="暂无数据" />

        <div v-for="item in items" :key="item.id" class="review-card">
          <div class="card-top">
            <div class="card-file">
              <el-icon :size="16"><Document /></el-icon>
              <span class="mono file-name">{{ item.name }}</span>
              <el-tag size="small" type="info">{{ typeLabel(item.file_type) }}</el-tag>
              <el-tag v-if="item.testcase_name" size="small" type="info" effect="plain">{{ item.testcase_name }}</el-tag>
            </div>
            <span class="card-time">{{ fmtDate(item.reviewed_at) }}</span>
          </div>

          <div class="card-body">
            <div class="card-row">
              <span class="card-label">任务</span>
              <span class="card-value mono">{{ item.task_name || item.task_id }}</span>
            </div>
            <div class="card-row">
              <span class="card-label">自动结论</span>
              <span class="card-value">{{ catLabel(item.primary?.category) }}</span>
              <span v-if="item.primary?.rule_name" class="card-meta">
                · 规则 {{ item.primary.rule_name }} · 置信度 {{ (item.primary.confidence * 100).toFixed(0) }}%
              </span>
            </div>
            <div class="card-row">
              <span class="card-label">人工覆盖</span>
              <span class="card-value overridden-cat">{{ catLabel(item.override_category) }}</span>
            </div>
            <div v-if="item.high_value?.notes" class="card-row hv-notes">
              <span class="card-label">⭐ 备注</span>
              <span class="card-value">{{ item.high_value.notes }}</span>
            </div>
            <div v-if="item.reviewer_note" class="card-row">
              <span class="card-label">审核备注</span>
              <span class="card-value note-text">{{ item.reviewer_note }}</span>
            </div>
          </div>

          <div class="card-actions">
            <el-button size="small" text type="primary" @click="showDetail(item.id)">查看详情</el-button>

            <template v-if="activeTab === 'pending'">
              <el-button size="small" text type="warning" @click="handleReset(item)">↩ 驳回</el-button>
              <el-button size="small" text @click="handleArchive(item)">📦 归档</el-button>
              <el-button size="small" text type="danger" @click="openHighValue(item)">⭐ 归档为高价值</el-button>
            </template>

            <template v-if="activeTab === 'archived'">
              <el-button size="small" text type="primary" @click="handleUnarchive(item)">↩ 取消归档</el-button>
            </template>

            <template v-if="activeTab === 'high-value'">
              <el-button size="small" text type="primary" @click="editHighValueNotes(item)">✏ 修改备注</el-button>
            </template>
          </div>
        </div>

        <el-pagination
          v-if="items.length"
          v-model:current-page="page"
          :page-size="pageSize"
          :total="items.length >= pageSize ? (page * pageSize + 1) : items.length"
          layout="prev, pager, next"
          small
          class="card-pager"
          @current-change="load"
        />
      </div>
    </AppSection>

    <!-- Review drawer (reused) -->
    <ReviewDrawer
      v-model="drawerVisible"
      :file-id="drawerFileId"
      @update:model-value="onDrawerClosed"
      @updated="onDrawerUpdated"
    />

    <!-- High-value dialog -->
    <HighValueDialog
      v-model="hvVisible"
      :file-id="hvFileId"
      :record-id="hvRecordId"
      :initial-notes="hvCurrentNotes"
      @saved="onHighValueSaved"
    />
  </div>
</template>

<style scoped>
.review-dashboard {
  max-width: 1080px;
}

.card-list {
  margin-top: var(--space-md);
}

.review-card {
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-lg);
  margin-bottom: var(--space-md);
  background: var(--bg-panel);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-md);
}

.card-file {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.file-name {
  font-size: var(--text-body);
  font-weight: 500;
}

.mono {
  font-family: var(--font-mono);
}

.card-time {
  font-size: var(--text-small);
  color: var(--text-muted);
}

.card-body {
  margin-bottom: var(--space-md);
}

.card-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-md);
  font-size: var(--text-body);
  line-height: 1.8;
}

.card-label {
  color: var(--text-secondary);
  flex: none;
  width: 72px;
}

.card-value {
  color: var(--text-primary);
}

.card-meta {
  font-size: var(--text-small);
  color: var(--text-muted);
}

.overridden-cat {
  color: var(--color-primary);
  font-weight: 500;
}

.note-text {
  color: var(--text-secondary);
  font-style: italic;
}

.hv-notes .card-value {
  color: var(--color-warning);
}

.card-actions {
  display: flex;
  gap: var(--space-xs);
  padding-top: var(--space-md);
  border-top: 1px solid var(--border-light);
}

.card-pager {
  margin-top: var(--space-lg);
  justify-content: center;
}
</style>
