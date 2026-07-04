<script setup>
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { reviewApi, analysisApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  fileId: { type: String, default: null },
  recordId: { type: String, default: null },
  initialNotes: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const notes = ref('')
const submitting = ref(false)
const fileInfo = ref(null)

watch(() => [props.modelValue, props.fileId], async ([show, id]) => {
  if (show && id) {
    notes.value = props.initialNotes || ''
    fileInfo.value = null
    try {
      const { data } = await analysisApi.fileDetail(id)
      fileInfo.value = data
    } catch { /* ignore */ }
  }
})

async function handleSave() {
  if (!notes.value.trim()) {
    ElMessage.warning('请填写补充说明')
    return
  }
  submitting.value = true
  try {
    if (props.recordId) {
      await reviewApi.updateHighValueNotes(props.recordId, { notes: notes.value.trim() })
      ElMessage.success('备注已更新')
    } else {
      await reviewApi.markHighValue(props.fileId, { notes: notes.value.trim() })
      ElMessage.success('已标记为高价值信息')
    }
    emit('saved')
  } finally {
    submitting.value = false
  }
}

function catLabel(cat) {
  if (!cat) return '无法识别'
  return cat.parent_name ? `${cat.parent_name} / ${cat.name}` : cat.name
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="recordId ? '修改高价值备注' : '⭐ 标记为高价值信息'"
    width="520px"
    destroy-on-close
  >
    <div v-if="fileInfo" class="hv-dialog-body">
      <div class="hv-meta">
        <div class="hv-meta-row">
          <span class="hv-label">文件</span>
          <span class="mono">{{ fileInfo.file.name }}</span>
        </div>
        <div class="hv-meta-row">
          <span class="hv-label">自动结论</span>
          <span>{{ catLabel(fileInfo.primary?.category) }}</span>
        </div>
        <div class="hv-meta-row">
          <span class="hv-label">人工覆盖</span>
          <span class="overridden-cat">{{ catLabel(fileInfo.override?.category) }}</span>
        </div>
      </div>

      <div class="hv-notes-section">
        <label class="hv-notes-label">补充说明 <span class="required">*</span></label>
        <el-input
          v-model="notes"
          type="textarea"
          :rows="5"
          placeholder="可用于后续 LLM 分析的上下文信息。例如：该错误的原因、判定依据、建议的新规则模式等…"
        />
      </div>
    </div>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="handleSave">
        {{ recordId ? '保存修改' : '确认保存' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.hv-dialog-body {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hv-meta {
  background: #f5f7fa;
  border-radius: 6px;
  padding: 12px 14px;
  font-size: 13px;
}

.hv-meta-row {
  display: flex;
  gap: 10px;
  line-height: 1.8;
}

.hv-label {
  color: #909399;
  flex: none;
  width: 60px;
}

.mono {
  font-family: 'Cascadia Code', 'JetBrains Mono', 'Fira Code', monospace;
}

.overridden-cat {
  color: #409eff;
  font-weight: 500;
}

.hv-notes-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.hv-notes-label {
  font-size: 13px;
  font-weight: 500;
}

.required {
  color: #f56c6c;
}
</style>
