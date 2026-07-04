<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

import { taskApi, analysisApi } from '@/api'

const router = useRouter()

const tasks = ref([])
const loading = ref(true)
const selectedTaskId = ref(null)
const dashboard = ref(null)
const report = ref(null)

onMounted(async () => {
  try {
    const { data } = await taskApi.list({ limit: 50 })
    tasks.value = data
    if (data.length > 0) {
      selectedTaskId.value = data[0].id
      await loadDashboard(data[0].id)
    }
  } finally {
    loading.value = false
  }
})

async function loadDashboard(taskId) {
  try {
    const { data } = await taskApi.summary(taskId)
    // Prefer dedicated dashboard endpoint for richer data
    try {
      const dashResp = await analysisApi.dashboard(taskId)
      dashboard.value = dashResp.data
    } catch {
      dashboard.value = { ...data, category_distribution: data.category_breakdown || {} }
    }
    // Load report
    try {
      const reportResp = await analysisApi.report(taskId)
      report.value = reportResp.data
    } catch {
      report.value = null
    }
  } catch {
    dashboard.value = null
    report.value = null
  }
}

async function handleTaskChange(taskId) {
  selectedTaskId.value = taskId
  await loadDashboard(taskId)
}

const pieOption = computed(() => {
  if (!dashboard.value) return {}
  const dist = dashboard.value.category_distribution || {}
  const data = Object.entries(dist).map(([name, value]) => ({
    name: name || '未分类',
    value,
  }))
  return {
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', left: 'left' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {c}' },
      data: data.length > 0 ? data : [{ name: '暂无数据', value: 0 }],
    }],
  }
})

const barOption = computed(() => {
  if (!dashboard.value) return {}
  const d = dashboard.value
  return {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['总数', '已分类', '未识别'] },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      data: [
        { value: d.total_failures || 0, itemStyle: { color: '#409eff' } },
        { value: d.classified || 0, itemStyle: { color: '#67c23a' } },
        { value: d.unrecognized || 0, itemStyle: { color: '#e6a23c' } },
      ],
      itemStyle: { borderRadius: [4, 4, 0, 0] },
    }],
  }
})

const statusTag = (status) => {
  const map = {
    pending: 'info',
    parsing: 'warning',
    analyzing: 'warning',
    completed: 'success',
    failed: 'danger',
  }
  return map[status] || 'info'
}

function navigateToTask(taskId) {
  router.push(`/tasks/${taskId}`)
}
</script>

<template>
  <div class="dashboard">
    <div class="page-header">
      <h2>分析看板</h2>
      <el-select
        v-model="selectedTaskId"
        placeholder="选择任务"
        @change="handleTaskChange"
        style="width: 280px"
        :loading="loading"
      >
        <el-option
          v-for="task in tasks"
          :key="task.id"
          :label="task.name"
          :value="task.id"
        >
          <span>{{ task.name }}</span>
          <el-tag :type="statusTag(task.status)" size="small" style="margin-left: 12px">
            {{ task.status }}
          </el-tag>
        </el-option>
      </el-select>
    </div>

    <div v-if="!selectedTaskId" class="empty-state">
      <el-empty description="暂无任务，请先创建任务" />
    </div>

    <template v-else-if="dashboard">
      <el-row :gutter="16" class="stat-cards">
        <el-col :span="6">
          <el-card>
            <div class="stat-card">
              <div class="stat-label">总日志行数</div>
              <div class="stat-value">{{ (dashboard.total_entries || 0).toLocaleString() }}</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card>
            <div class="stat-card">
              <div class="stat-label">失败事件</div>
              <div class="stat-value danger">{{ (dashboard.total_failures || 0).toLocaleString() }}</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card>
            <div class="stat-card">
              <div class="stat-label">已分类</div>
              <div class="stat-value success">{{ (dashboard.classified || 0).toLocaleString() }}</div>
            </div>
          </el-card>
        </el-col>
        <el-col :span="6">
          <el-card>
            <div class="stat-card">
              <div class="stat-label">未识别</div>
              <div class="stat-value warning">{{ (dashboard.unrecognized || 0).toLocaleString() }}</div>
            </div>
          </el-card>
        </el-col>
      </el-row>

      <!-- Analysis Report -->
      <el-row v-if="report" style="margin-top: 16px">
        <el-col :span="24">
          <el-card>
            <template #header>分析报告</template>
            <el-row :gutter="8">
              <el-col :span="4">
                <div class="report-stat">
                  <span class="report-num">{{ report.total_testsuite_files }}</span>
                  <span class="report-label">测试套文件</span>
                </div>
              </el-col>
              <el-col :span="4">
                <div class="report-stat">
                  <span class="report-num">{{ report.total_testcase_files }}</span>
                  <span class="report-label">测试用例文件</span>
                </div>
              </el-col>
              <el-col :span="4">
                <div class="report-stat">
                  <span class="report-num success">{{ report.auto_analyzed }}</span>
                  <span class="report-label">自动分析</span>
                  <span class="report-pct">{{ report.auto_analyzed_pct }}%</span>
                </div>
              </el-col>
              <el-col :span="4">
                <div class="report-stat">
                  <span class="report-num primary">{{ report.human_reviewed }}</span>
                  <span class="report-label">人工已审核</span>
                </div>
              </el-col>
              <el-col :span="4">
                <div class="report-stat">
                  <span class="report-num warning">{{ report.human_overridden }}</span>
                  <span class="report-label">人工已覆盖</span>
                </div>
              </el-col>
              <el-col :span="4">
                <div class="report-stat">
                  <span class="report-num danger">{{ report.remaining_unreviewed }}</span>
                  <span class="report-label">尚未审核</span>
                </div>
              </el-col>
            </el-row>
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px">
        <el-col :span="12">
          <el-card>
            <template #header>失败分类分布</template>
            <VChart :option="pieOption" style="height: 320px" autoresize />
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card>
            <template #header>分类统计</template>
            <VChart :option="barOption" style="height: 320px" autoresize />
          </el-card>
        </el-col>
      </el-row>

      <el-row :gutter="16" style="margin-top: 16px" v-if="dashboard.feedback_total > 0">
        <el-col :span="12">
          <el-card>
            <template #header>反馈准确率</template>
            <div class="accuracy-display">
              <el-progress
                type="dashboard"
                :percentage="Math.round(dashboard.feedback_accuracy || 0)"
                :color="(dashboard.feedback_accuracy || 0) >= 80 ? '#67c23a' : '#e6a23c'"
              />
              <div class="accuracy-detail">
                共 {{ dashboard.feedback_total }} 条反馈，{{ dashboard.feedback_correct }} 条正确
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </template>

    <div v-else class="empty-state">
      <el-empty description="加载看板数据失败" />
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 1200px;
  padding: var(--space-xl);
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-header h2 {
  font-size: 20px;
  font-weight: 600;
}

.stat-cards {
  margin-bottom: 16px;
}

.stat-card {
  text-align: center;
  padding: 8px 0;
}

.stat-label {
  font-size: 13px;
  color: #909399;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
}

.stat-value.danger { color: #f56c6c; }
.stat-value.success { color: #67c23a; }
.stat-value.warning { color: #e6a23c; }

.empty-state {
  margin-top: 80px;
}

.accuracy-display {
  text-align: center;
}

.accuracy-detail {
  margin-top: 12px;
  font-size: 13px;
  color: #909399;
}

/* ── Report ── */
.report-stat {
  text-align: center;
  padding: 12px 4px;
}
.report-num {
  display: block;
  font-size: 26px;
  font-weight: 700;
  color: #303133;
}
.report-num.success { color: #67c23a; }
.report-num.primary { color: #409eff; }
.report-num.warning { color: #e6a23c; }
.report-num.danger { color: #f56c6c; }
.report-label {
  display: block;
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.report-pct {
  display: block;
  font-size: 11px;
  color: #67c23a;
  margin-top: 2px;
}
</style>
