<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { mappingApi, reportApi } from '@/api'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'

const versions = ref([])
const purposes = ref([])
const selectedVersion = ref('')
const selectedPurpose = ref('')
const report = ref(null)
const loading = ref(false)

const scopeLabel = computed(() => report.value?.scope?.name || '')
const analysisRate = computed(() => {
  const analysis = report.value?.analysis
  return analysis?.subjects ? Math.round(analysis.completed / analysis.subjects * 100) : 0
})
const reviewRate = computed(() => {
  const review = report.value?.review
  return review?.eligible ? Math.round((review.confirmed + review.overridden) / review.eligible * 100) : 0
})
const tool = computed(() => report.value?.tool_effectiveness || {})
const ruleAuditAvailable = computed(() => report.value?.rule_audit_status?.available !== false)
function percent(value) {
  return value == null ? '-' : `${value}%`
}
const exceptionRows = computed(() => {
  if (!report.value) return []
  return [
    ...report.value.exceptions.missing_log.map((item) => ({ ...item, type: 'YAML 失败但缺日志' })),
    ...report.value.exceptions.no_conclusion.map((item) => ({ ...item, type: '失败无分析结论' })),
  ]
})

async function loadPurposes() {
  selectedPurpose.value = ''
  purposes.value = []
  if (!selectedVersion.value) return
  const { data } = await mappingApi.listPurposes(selectedVersion.value)
  purposes.value = data
}

async function loadReport() {
  if (!selectedVersion.value) {
    report.value = null
    return
  }
  loading.value = true
  try {
    const response = selectedPurpose.value
      ? await reportApi.purpose(selectedPurpose.value)
      : await reportApi.version(selectedVersion.value)
    report.value = response.data
  } finally {
    loading.value = false
  }
}

watch(selectedVersion, async () => {
  await loadPurposes()
  await loadReport()
})
watch(selectedPurpose, loadReport)

onMounted(async () => {
  const { data } = await mappingApi.listVersions()
  versions.value = data
  if (data.length) selectedVersion.value = data[0].id
})
</script>

<template>
  <div class="page overall-report">
    <AppPageHeader title="整体报表" subtitle="按版本或测试目的汇总当前最新分析结果">
      <template #actions>
        <el-select v-model="selectedVersion" placeholder="选择版本" style="width: 220px">
          <el-option v-for="version in versions" :key="version.id" :label="version.version_name" :value="version.id" />
        </el-select>
        <el-select v-model="selectedPurpose" clearable placeholder="全部测试目的" style="width: 240px">
          <el-option v-for="purpose in purposes" :key="purpose.id" :label="purpose.name" :value="purpose.id" />
        </el-select>
      </template>
    </AppPageHeader>

    <div v-loading="loading">
      <el-empty v-if="!selectedVersion && !loading" description="暂无测试版本" />
      <template v-else-if="report">
        <AppSection :title="scopeLabel" hint="重分析完成后自动使用最新结果">
          <div class="stat-grid">
            <div class="stat"><span>分析任务</span><strong>{{ report.tasks.total }}</strong></div>
            <div class="stat"><span>测试用例</span><strong>{{ report.results.total }}</strong></div>
            <div class="stat danger"><span>失败</span><strong>{{ report.results.failed }}</strong></div>
            <div class="stat warning"><span>阻塞</span><strong>{{ report.results.blocked }}</strong></div>
            <div class="stat success"><span>自动分析完成</span><strong>{{ analysisRate }}%</strong></div>
            <div class="stat"><span>审核完成</span><strong>{{ reviewRate }}%</strong></div>
          </div>
        </AppSection>

        <AppSection title="测试结果">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="成功">{{ report.results.success }}</el-descriptions-item>
            <el-descriptions-item label="失败">{{ report.results.failed }}</el-descriptions-item>
            <el-descriptions-item label="阻塞">{{ report.results.blocked }}</el-descriptions-item>
            <el-descriptions-item label="未知/缺失">{{ report.results.unknown }}</el-descriptions-item>
          </el-descriptions>
        </AppSection>

        <AppSection title="自动分析">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="分析对象">{{ report.analysis.subjects }}</el-descriptions-item>
            <el-descriptions-item label="规则结论">{{ report.analysis.rule_result }}</el-descriptions-item>
            <el-descriptions-item label="测试套失败归因">{{ report.analysis.suite_failed }}</el-descriptions-item>
            <el-descriptions-item label="兜底/未识别">{{ report.analysis.fallback }}</el-descriptions-item>
            <el-descriptions-item label="无分析结论">{{ report.analysis.no_conclusion }}</el-descriptions-item>
            <el-descriptions-item label="YAML 已匹配">{{ report.data_quality.summary_matched }}</el-descriptions-item>
          </el-descriptions>
        </AppSection>

        <AppSection title="工具效果">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="文件总数">{{ tool.total_files }}</el-descriptions-item>
            <el-descriptions-item label="工具已分析">{{ tool.analyzed_files }}</el-descriptions-item>
            <el-descriptions-item label="分析占比">{{ percent(tool.analysis_rate) }}</el-descriptions-item>
            <el-descriptions-item label="人工已审核">{{ tool.reviewed_files }}</el-descriptions-item>
            <el-descriptions-item label="人工已采纳">{{ tool.adopted_files }}</el-descriptions-item>
            <el-descriptions-item label="分析采纳率">{{ tool.adoption_rate == null ? '暂无审核样本' : percent(tool.adoption_rate) }}</el-descriptions-item>
          </el-descriptions>
        </AppSection>

        <AppSection title="人工审核">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="可审核">{{ report.review.eligible }}</el-descriptions-item>
            <el-descriptions-item label="待审核">{{ report.review.pending }}</el-descriptions-item>
            <el-descriptions-item label="确认">{{ report.review.confirmed }}</el-descriptions-item>
            <el-descriptions-item label="覆盖">{{ report.review.overridden }}</el-descriptions-item>
          </el-descriptions>
        </AppSection>

        <AppSection title="最终根因">
          <el-table :data="report.categories" size="small" max-height="250" empty-text="暂无分类结果">
            <el-table-column prop="name" label="最终结论" min-width="260" />
            <el-table-column prop="count" label="数量" width="100" />
          </el-table>
        </AppSection>

        <AppSection title="规则数据统计">
          <el-alert
            v-if="!ruleAuditAvailable"
            title="部分任务尚未以当前审计格式重分析，原始规则执行统计暂不可用"
            type="warning"
            :closable="false"
            show-icon
            class="rule-audit-alert"
          />
          <el-table :data="report.rule_statistics" size="small" max-height="320" empty-text="暂无启用规则">
            <el-table-column prop="name" label="规则" min-width="180" />
            <el-table-column prop="category" label="类别" min-width="160" />
            <el-table-column prop="selected_count" label="最终选中" width="100" />
            <el-table-column label="选中占比" width="100"><template #default="{ row }">{{ percent(row.selected_rate) }}</template></el-table-column>
            <el-table-column label="执行次数" width="100"><template #default="{ row }">{{ row.evaluation_count ?? '-' }}</template></el-table-column>
            <el-table-column label="命中次数" width="100"><template #default="{ row }">{{ row.matched_count ?? '-' }}</template></el-table-column>
            <el-table-column label="命中率" width="90"><template #default="{ row }">{{ percent(row.match_rate) }}</template></el-table-column>
            <el-table-column label="异常" width="80"><template #default="{ row }">{{ row.error_count ?? '-' }}</template></el-table-column>
          </el-table>
        </AppSection>

        <AppSection v-if="!selectedPurpose" title="测试目的明细">
          <el-table :data="report.purposes" size="small" max-height="320" empty-text="暂无测试目的">
            <el-table-column prop="name" label="测试目的" min-width="220" />
            <el-table-column prop="task_count" label="任务" width="80" />
            <el-table-column prop="failed" label="失败" width="80" />
            <el-table-column prop="blocked" label="阻塞" width="80" />
            <el-table-column label="自动分析" width="110"><template #default="{ row }">{{ row.analysis_completed }} / {{ row.analysis_subjects }}</template></el-table-column>
            <el-table-column prop="review_pending" label="待审核" width="90" />
          </el-table>
        </AppSection>

        <AppSection title="异常项">
          <el-table :data="exceptionRows" size="small" max-height="250" empty-text="暂无异常项">
            <el-table-column prop="type" label="异常" width="180" />
            <el-table-column prop="task_id" label="任务 ID" width="140" />
            <el-table-column prop="testcase" label="测试用例" min-width="260" />
            <el-table-column prop="status" label="原始结果" width="100" />
          </el-table>
        </AppSection>
      </template>
    </div>
  </div>
</template>

<style scoped>
.overall-report { max-width: 1400px; }
.stat-grid { display: grid; grid-template-columns: repeat(6, minmax(120px, 1fr)); gap: var(--space-md); }
.stat { border: 1px solid var(--border-light); border-radius: var(--radius-md); padding: var(--space-lg); background: var(--bg-panel); display: grid; gap: var(--space-sm); }
.stat span { color: var(--text-secondary); font-size: var(--text-small); }
.stat strong { font-size: 26px; color: var(--text-primary); }
.stat.danger strong { color: var(--color-error); }
.stat.warning strong { color: var(--color-warning); }
.stat.success strong { color: var(--color-success); }
.rule-audit-alert { margin-bottom: var(--space-md); }
@media (max-width: 1100px) { .stat-grid { grid-template-columns: repeat(3, minmax(120px, 1fr)); } }
@media (max-width: 640px) { .stat-grid { grid-template-columns: repeat(2, minmax(120px, 1fr)); } }
</style>
