<script setup>
import { ref, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analysisApi, logApi, reviewApi, categoryApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  fileId: { type: String, default: null },
})
const emit = defineEmits(['update:modelValue', 'updated'])

const router = useRouter()

const detail = ref(null)
const loading = ref(false)

// ── Log viewer ──
const logPage = ref(1)
const logPageSize = 200
const logLines = ref([])
const logTotal = ref(0)
const logLoading = ref(false)
const highlightRange = ref(null) // {start, end}

// ── Evidence block (root cause) ──
const evidenceLines = ref([])

// ── Related files ──
const relatedFiles = ref([])
const relatedLoading = ref(false)

// ── Review form ──
const categoryTree = ref([])
const overrideMode = ref(false)
const reviewForm = ref({ category_path: [], evidence: '', note: '' })
const submitting = ref(false)

// ── User role ──
const userRole = ref('')
try {
  const u = JSON.parse(localStorage.getItem('user') || '{}')
  userRole.value = u.role || ''
} catch {}
const canWriteReview = computed(() => ['analyst', 'reviewer', 'admin'].includes(userRole.value))

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

watch(() => [props.modelValue, props.fileId], async ([show, id]) => {
  if (show && id) await loadAll(id)
})

async function loadAll(fileId) {
  loading.value = true
  detail.value = null
  evidenceLines.value = []
  logLines.value = []
  relatedFiles.value = []
  overrideMode.value = false
  try {
    const { data } = await analysisApi.fileDetail(fileId)
    detail.value = data
    reviewForm.value = {
      category_path: [],
      evidence: data.primary?.evidence || '',
      note: data.reviewer_note || '',
    }
    loadCategories()
    loadEvidenceBlock()
    logPage.value = 1
    loadLogPage()
    loadRelated()
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  if (categoryTree.value.length) return
  try {
    const { data } = await categoryApi.list()
    categoryTree.value = (data || []).map((c) => ({
      value: c.id,
      label: c.name,
      children: (c.children || []).map((ch) => ({ value: ch.id, label: ch.name })),
    }))
  } catch {}
}

async function loadEvidenceBlock() {
  const p = detail.value?.primary
  if (!p || p.line_start == null) return
  const start = Math.max(1, p.line_start - 2)
  const end = (p.line_end || p.line_start) + 2
  try {
    const { data } = await logApi.fileRaw(props.fileId, { start_line: start, end_line: end })
    evidenceLines.value = (data.lines || []).map((l) => ({
      ...l,
      hit: l.no >= p.line_start && l.no <= (p.line_end || p.line_start),
    }))
  } catch {}
}

async function loadLogPage() {
  logLoading.value = true
  const start = (logPage.value - 1) * logPageSize + 1
  try {
    const { data } = await logApi.fileRaw(props.fileId, {
      start_line: start,
      end_line: start + logPageSize - 1,
    })
    logLines.value = data.lines || []
    logTotal.value = data.total_lines || 0
  } finally {
    logLoading.value = false
  }
}

function jumpToLine(lineNo, lineEnd) {
  if (lineNo == null) return
  logPage.value = Math.ceil(lineNo / logPageSize)
  highlightRange.value = { start: lineNo, end: lineEnd || lineNo }
  loadLogPage()
}

function isHighlighted(no) {
  const r = highlightRange.value
  return r && no >= r.start && no <= r.end
}

async function loadRelated() {
  relatedLoading.value = true
  try {
    const { data } = await analysisApi.relatedFiles(props.fileId)
    relatedFiles.value = Array.isArray(data) ? data : []
  } finally {
    relatedLoading.value = false
  }
}

const relatedGroups = computed(() => {
  const labels = { testcase: '本用例文件', testsuite: '测试套文件', task: '任务日志', raw: '其他文件' }
  const groups = {}
  for (const f of relatedFiles.value) {
    const key = f.group || 'raw'
    if (!groups[key]) groups[key] = { label: labels[key] || key, items: [] }
    groups[key].items.push(f)
  }
  return Object.values(groups)
})

function openInBrowser(f) {
  const route = router.resolve({
    name: 'Browser',
    query: { provider: f.provider || 's3', path: f.path, name: f.name },
  })
  window.open(route.href, '_blank')
}

function formatSize(size) {
  if (size == null) return ''
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

// ── Review actions ──
async function handleConfirm() {
  submitting.value = true
  try {
    await reviewApi.confirm(props.fileId, { note: reviewForm.value.note || null })
    ElMessage.success('已确认')
    detail.value.file.review_status = 'confirmed'
    emit('updated')
  } finally {
    submitting.value = false
  }
}

async function handleOverride() {
  const path = reviewForm.value.category_path
  const categoryId = path.length ? path[path.length - 1] : null
  if (!categoryId) {
    ElMessage.warning('请选择覆盖分类')
    return
  }
  submitting.value = true
  try {
    await reviewApi.override(props.fileId, {
      category_id: categoryId,
      evidence: reviewForm.value.evidence || null,
      note: reviewForm.value.note || null,
    })
    ElMessage.success('已覆盖最终结论')
    overrideMode.value = false
    await loadAll(props.fileId)
    emit('updated')
  } finally {
    submitting.value = false
  }
}

async function handleReset() {
  submitting.value = true
  try {
    await reviewApi.reset(props.fileId)
    ElMessage.success('已重置为待审核')
    await loadAll(props.fileId)
    emit('updated')
  } finally {
    submitting.value = false
  }
}

const statusTag = computed(() => {
  const map = {
    pending: { type: 'warning', label: '待审核' },
    confirmed: { type: 'success', label: '已确认' },
    overridden: { type: 'primary', label: '已覆盖' },
  }
  return map[detail.value?.file?.review_status] || map.pending
})

function categoryLabel(cat) {
  if (!cat) return '无法识别'
  return cat.parent_name ? `${cat.parent_name} / ${cat.name}` : cat.name
}
</script>

<template>
  <el-drawer v-model="visible" size="75%" :with-header="false" destroy-on-close>
    <div class="review-drawer" v-loading="loading">
      <template v-if="detail">
        <!-- Header -->
        <div class="drawer-header">
          <div>
            <span class="file-name mono">{{ detail.file.name }}</span>
            <el-tag size="small" style="margin-left: 8px">
              {{ detail.file.file_type === 'testsuite' ? '测试套' : detail.file.file_type === 'testcase' ? '测试用例' : '任务日志' }}
            </el-tag>
            <el-tag size="small" :type="statusTag.type" style="margin-left: 8px">{{ statusTag.label }}</el-tag>
          </div>
          <el-button text @click="visible = false"><el-icon><Close /></el-icon></el-button>
        </div>

        <!-- Override result (when overridden) -->
        <div v-if="detail.override" class="cause-card overridden-card">
          <div class="cause-card-head">
            <el-tag type="primary" size="small">最终结论 · 人工覆盖</el-tag>
            <span class="cause-category">{{ categoryLabel(detail.override.category) }}</span>
          </div>
          <pre v-if="detail.override.evidence" class="evidence-text">{{ detail.override.evidence }}</pre>
        </div>

        <!-- Root cause card -->
        <div v-if="detail.primary" class="cause-card" :class="{ muted: detail.override }">
          <div class="cause-card-head">
            <el-tag type="danger" size="small">{{ detail.override ? '自动结论（已被覆盖）' : '最终结论 · 根因 #1' }}</el-tag>
            <span class="cause-category">{{ categoryLabel(detail.primary.category) }}</span>
            <span class="cause-meta">
              <template v-if="detail.primary.rule">规则: {{ detail.primary.rule.name }} ({{ detail.primary.rule.rule_id }} v{{ detail.primary.rule.version }}) · </template>
              置信度
              <span :style="{ color: detail.primary.confidence >= 0.7 ? '#67c23a' : '#e6a23c' }">
                {{ (detail.primary.confidence * 100).toFixed(0) }}%
              </span>
            </span>
          </div>
          <div class="cause-evidence">{{ detail.primary.evidence }}</div>
          <div v-if="evidenceLines.length" class="log-block">
            <div v-for="l in evidenceLines" :key="l.no" class="log-line" :class="{ error: l.hit || l.is_error }">
              <span class="line-no">{{ l.no }}</span><span class="line-text">{{ l.text }}</span>
            </div>
          </div>
          <div v-if="detail.primary.line_start != null" class="cause-foot">
            证据来自第 {{ detail.primary.line_start }}<template v-if="detail.primary.line_end && detail.primary.line_end !== detail.primary.line_start">–{{ detail.primary.line_end }}</template> 行
            <el-button link type="primary" size="small" @click="jumpToLine(detail.primary.line_start, detail.primary.line_end)">在日志中定位</el-button>
          </div>
        </div>
        <el-empty v-if="!detail.primary && !detail.override" description="该文件没有检测到失败事件" :image-size="60" />

        <!-- Other potential reasons -->
        <div v-if="detail.secondary || detail.others.length" class="other-reasons">
          <div class="other-title">其他可能原因（不影响最终结论）</div>
          <div v-if="detail.secondary" class="other-item">
            <el-tag type="warning" size="small">#2</el-tag>
            <span class="other-cat">{{ categoryLabel(detail.secondary.category) }}</span>
            <span class="other-meta">
              <template v-if="detail.secondary.rule">规则 {{ detail.secondary.rule.rule_id }} · </template>
              置信度 {{ (detail.secondary.confidence * 100).toFixed(0) }}%
              <template v-if="detail.secondary.line_start != null"> · 第 {{ detail.secondary.line_start }} 行</template>
            </span>
            <el-button v-if="detail.secondary.line_start != null" link type="primary" size="small" @click="jumpToLine(detail.secondary.line_start, detail.secondary.line_end)">定位</el-button>
            <div class="other-evidence">{{ detail.secondary.evidence }}</div>
          </div>
          <div v-for="o in detail.others" :key="o.id" class="other-item">
            <el-tag type="info" size="small">参考</el-tag>
            <span class="other-cat">{{ categoryLabel(o.category) }}</span>
            <span class="other-meta">
              <template v-if="o.rule">规则 {{ o.rule.rule_id }} · </template>
              置信度 {{ (o.confidence * 100).toFixed(0) }}%
              <template v-if="o.line_start != null"> · 第 {{ o.line_start }} 行</template>
            </span>
            <el-button v-if="o.line_start != null" link type="primary" size="small" @click="jumpToLine(o.line_start, o.line_end)">定位</el-button>
          </div>
        </div>

        <!-- Log viewer -->
        <div class="log-section">
          <div class="log-toolbar">
            <span class="log-title">日志详情（本文件 · 共 {{ logTotal.toLocaleString() }} 行）</span>
            <el-pagination
              v-if="logTotal > logPageSize"
              v-model:current-page="logPage"
              :page-size="logPageSize"
              :total="logTotal"
              layout="prev, pager, next"
              small
              @current-change="loadLogPage"
            />
          </div>
          <div class="log-block log-viewer" v-loading="logLoading">
            <div v-for="l in logLines" :key="l.no" class="log-line" :class="{ error: l.is_error, located: isHighlighted(l.no) }">
              <span class="line-no">{{ l.no }}</span><span class="line-text">{{ l.text }}</span>
            </div>
            <div v-if="!logLines.length && !logLoading" class="log-empty">暂无日志内容</div>
          </div>
        </div>

        <!-- Related files -->
        <div class="related-section" v-loading="relatedLoading">
          <div class="other-title">相关文件（未参与分析）</div>
          <template v-if="relatedGroups.length">
            <div v-for="g in relatedGroups" :key="g.label" class="related-group">
              <div class="related-group-label">{{ g.label }}</div>
              <div v-for="f in g.items" :key="f.path" class="related-item">
                <el-icon><Document /></el-icon>
                <span class="related-name mono" :title="f.path">{{ f.name }}</span>
                <span class="related-size">{{ formatSize(f.size) }}</span>
                <el-button link type="primary" size="small" @click="openInBrowser(f)">在浏览器中打开</el-button>
              </div>
            </div>
          </template>
          <div v-else class="related-empty">无相关文件</div>
        </div>

        <!-- Review footer -->
        <div class="review-footer">
          <div v-if="overrideMode" class="override-form">
            <el-form label-width="100px" label-position="left">
              <el-form-item label="覆盖分类" required>
                <el-cascader
                  v-model="reviewForm.category_path"
                  :options="categoryTree"
                  :props="{ expandTrigger: 'hover', checkStrictly: true }"
                  placeholder="选择 大类 / 子类（可选大类）"
                  style="width: 320px"
                />
              </el-form-item>
              <el-form-item label="证据日志">
                <el-input v-model="reviewForm.evidence" type="textarea" :rows="3"
                          placeholder="支持该结论的日志行（可在上方日志中复制粘贴）" />
              </el-form-item>
            </el-form>
          </div>
          <el-input
            v-model="reviewForm.note"
            type="textarea"
            :rows="2"
            placeholder="审核备注：为什么确认 / 覆盖，规则可如何改进…"
            style="margin-bottom: 10px"
          />
          <div class="footer-actions" v-if="canWriteReview">
            <el-button :loading="submitting" @click="handleReset"
                       :disabled="detail.file.review_status === 'pending'">重置为待审核</el-button>
            <template v-if="overrideMode">
              <el-button @click="overrideMode = false">取消</el-button>
              <el-button type="primary" :loading="submitting" @click="handleOverride">提交覆盖</el-button>
            </template>
            <template v-else>
              <el-button type="warning" plain :loading="submitting" @click="overrideMode = true">覆盖结果</el-button>
              <el-button type="success" :loading="submitting" @click="handleConfirm">确认无误</el-button>
            </template>
          </div>
          <div class="footer-hint" v-else>
            <el-text type="info" size="small">游客模式：只能查看，不能修改审核结果</el-text>
          </div>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.review-drawer {
  padding: 4px 8px 24px;
}

.drawer-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.file-name {
  font-size: 16px;
  font-weight: 600;
}

.mono {
  font-family: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', monospace;
}

.cause-card {
  border: 2px solid #f56c6c;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}

.cause-card.muted {
  border-color: #dcdfe6;
  opacity: 0.85;
}

.overridden-card {
  border-color: #409eff;
}

.cause-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.cause-category {
  font-size: 15px;
  font-weight: 600;
}

.cause-meta {
  margin-left: auto;
  font-size: 12px;
  color: #909399;
}

.cause-evidence {
  margin-top: 8px;
  font-size: 13px;
  color: #606266;
}

.cause-foot {
  margin-top: 6px;
  font-size: 12px;
  color: #909399;
}

.evidence-text {
  margin: 8px 0 0;
  font-family: 'Cascadia Code', 'JetBrains Mono', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  background: #f5f7fa;
  border-radius: 4px;
  padding: 8px 10px;
}

.log-block {
  margin-top: 10px;
  background: #1e1e1e;
  border-radius: 6px;
  padding: 8px 0;
  overflow: auto;
  font-family: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12.5px;
  line-height: 1.6;
}

.log-viewer {
  max-height: 420px;
}

.log-line {
  display: flex;
  padding: 0 12px;
  color: #d4d4d4;
}

.log-line.error {
  background: rgba(245, 108, 108, 0.18);
  color: #f5a3a3;
}

.log-line.located {
  background: rgba(230, 162, 60, 0.25);
}

.line-no {
  flex: none;
  width: 52px;
  color: #6e6e6e;
  user-select: none;
}

.log-line.error .line-no {
  color: #f08080;
}

.line-text {
  white-space: pre-wrap;
  word-break: break-all;
}

.log-empty {
  color: #909399;
  text-align: center;
  padding: 24px;
}

.other-reasons {
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 14px;
}

.other-title {
  font-size: 12px;
  color: #909399;
  margin-bottom: 8px;
}

.other-item {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 13px;
  padding: 4px 0;
}

.other-cat {
  font-weight: 500;
}

.other-meta {
  font-size: 12px;
  color: #909399;
}

.other-evidence {
  flex-basis: 100%;
  font-size: 12px;
  color: #909399;
  padding-left: 2px;
}

.log-section {
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 14px;
}

.log-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.log-title {
  font-size: 13px;
  font-weight: 500;
}

.related-section {
  background: #fafafa;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  padding: 12px 16px;
  margin-bottom: 14px;
}

.related-group {
  margin-bottom: 6px;
}

.related-group-label {
  font-size: 12px;
  font-weight: 500;
  color: #606266;
  margin: 6px 0 2px;
}

.related-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  padding: 2px 0;
  color: #606266;
}

.related-name {
  font-size: 12px;
  max-width: 420px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.related-size {
  font-size: 12px;
  color: #c0c4cc;
}

.related-empty {
  font-size: 13px;
  color: #909399;
}

.review-footer {
  border-top: 1px solid #e4e7ed;
  padding-top: 14px;
}

.footer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
