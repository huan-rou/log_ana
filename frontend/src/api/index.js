import axios from 'axios'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// Request interceptor: attach token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败'
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      if (window.location.pathname !== '/login') {
        window.location.href = '/login'
      }
      return Promise.reject(error)
    }
    if (error.response?.status === 403) {
      ElMessage.error('权限不足: ' + msg)
      return Promise.reject(error)
    }
    ElMessage.error(msg)
    return Promise.reject(error)
  }
)

export default api

// ── Tasks ──
export const taskApi = {
  list: (params) => api.get('/tasks/', { params }),
  get: (id) => api.get(`/tasks/${id}`),
  create: (formData) => api.post('/tasks/', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
  delete: (id) => api.delete(`/tasks/${id}`),
  summary: (id) => api.get(`/tasks/${id}/summary`),
}

// ── Logs ──
export const logApi = {
  entries: (taskId, params) => api.get(`/logs/${taskId}/entries`, { params }),
  failures: (taskId, params) => api.get(`/logs/${taskId}/failures`, { params }),
  getFailure: (failureId) => api.get(`/logs/failures/${failureId}`),
  raw: (taskId, params) => api.get(`/logs/${taskId}/raw`, { params }),
  fileRaw: (fileId, params) => api.get(`/logs/files/${fileId}/raw`, { params }),
}

// ── Analysis ──
export const analysisApi = {
  run: (taskId) => api.post(`/analysis/${taskId}/run`),
  results: (taskId, params) => api.get(`/analysis/${taskId}/results`, { params }),
  resultDetail: (resultId) => api.get(`/analysis/results/${resultId}`),
  dashboard: (taskId) => api.get(`/analysis/${taskId}/dashboard`),
  // files: 向后兼容 v3.1 现有参数（review_status / file_type / category_id /
  //   is_fallback / summary_result）；v5 新增 tree_node_id / round_filter 透传
  files: (taskId, params = {}) => {
    const { treeNodeId, roundFilter, ...rest } = params
    const query = { ...rest }
    if (treeNodeId) query.tree_node_id = treeNodeId
    if (roundFilter != null) query.round_filter = roundFilter
    return api.get(`/analysis/${taskId}/files`, { params: query })
  },
  fileDetail: (fileId) => api.get(`/analysis/files/${fileId}`),
  relatedFiles: (fileId) => api.get(`/analysis/files/${fileId}/related`),
  report: (taskId) => api.get(`/analysis/${taskId}/report`),

  // ── v5: 任务树视图 API ──
  // 列当前 task 所属 TestVersion 下的所有 JSON 树轮次
  getTaskTrees: (taskId) => api.get(`/analysis/${taskId}/trees`),
  // 拉指定 round 的树。round 缺省 = 当前 task 所在 round（后端按 tree_node_id 推）
  getTaskTree: (taskId, round = null) =>
    api.get(`/analysis/${taskId}/tree`, {
      params: round == null ? {} : { round },
    }),
  // 整体视图：节点元信息（execution_count / latest_round / missing_rounds）
  getAggregate: (taskId, treeNodeId) => {
    if (!treeNodeId) return Promise.reject(new Error('treeNodeId 必填'))
    return api.get(`/analysis/${taskId}/aggregate`, {
      params: { tree_node_id: treeNodeId },
    })
  },
  // 整体视图右表：跨 round 按 testcase_name 聚合的 TestCase 行
  getAggregateTestcases: (taskId, treeNodeId) => {
    if (!treeNodeId) return Promise.reject(new Error('treeNodeId 必填'))
    return api.get(`/analysis/${taskId}/aggregate/testcases`, {
      params: { tree_node_id: treeNodeId },
    })
  },
  // 单轮次右表：当前 task 下 file_type=testcase 的 LogFile，按 testcase_name 分组
  getTestcases: (taskId, { treeNodeId } = {}) =>
    api.get(`/analysis/${taskId}/testcases`, {
      params: treeNodeId ? { tree_node_id: treeNodeId } : {},
    }),
}

// ── Review ──
export const reviewApi = {
  confirm: (fileId, data) => api.post(`/review/files/${fileId}/confirm`, data),
  override: (fileId, data) => api.post(`/review/files/${fileId}/override`, data),
  reset: (fileId) => api.post(`/review/files/${fileId}/reset`),
  overridden: (params) => api.get('/review/overridden', { params }),
  archive: (fileId) => api.post(`/review/files/${fileId}/archive`),
  unarchive: (fileId) => api.post(`/review/files/${fileId}/unarchive`),
  archived: (params) => api.get('/review/archived', { params }),
  markHighValue: (fileId, data) => api.post(`/review/files/${fileId}/high-value`, data),
  highValueList: (params) => api.get('/review/high-value', { params }),
  updateHighValueNotes: (recordId, data) => api.put(`/review/high-value/${recordId}/notes`, data),
}

// ── Rules ──
export const ruleApi = {
  list: () => api.get('/rules/'),
  get: (ruleId) => api.get(`/rules/${ruleId}`),
  source: (ruleId) => api.get(`/rules/${ruleId}/source`, { responseType: 'text' }),
  audit: (ruleId) => api.get(`/rules/${ruleId}/audit`),
  create: (data) => api.post('/rules/', data),
  update: (ruleId, data) => api.put(`/rules/${ruleId}`, data),
  updateMeta: (ruleId, data) => api.patch(`/rules/${ruleId}/meta`, data),
  publish: (ruleId) => api.post(`/rules/${ruleId}/publish`),
  unpublish: (ruleId) => api.post(`/rules/${ruleId}/unpublish`),
  toggleEnabled: (ruleId, enabled) => api.patch(`/rules/${ruleId}/enabled`, { enabled }),
  delete: (ruleId) => api.delete(`/rules/${ruleId}`),
  reload: () => api.post('/rules/reload'),
}

// ── Feedback ──
export const feedbackApi = {
  submit: (data) => api.post('/feedback/', data),
  stats: (taskId) => api.get(`/feedback/${taskId}/stats`),
  list: (params) => api.get('/feedback/list', { params }),
}

// ── Browse ──
export const browseApi = {
  roots: () => api.get('/browse/roots'),
  tree: (provider, path) => api.get('/browse/tree', { params: { provider, path } }),
  file: (provider, path) => api.get('/browse/file', { params: { provider, path } }),
  fileMeta: (provider, path) => api.get('/browse/file/meta', { params: { provider, path } }),
  search: (provider, path, q) => api.get('/browse/search', { params: { provider, path, q } }),
  s3Config: () => api.get('/browse/s3-config'),
}

// ── Categories ──
export const categoryApi = {
  list: () => api.get('/tasks/categories'),
  create: (data) => api.post('/tasks/categories', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  }),
}

// ── Auth ──
export const authApi = {
  login: (username, password) => api.post('/auth/login', { username, password }),
  me: () => api.get('/auth/me'),
  listUsers: () => api.get('/auth/users'),
  createUser: (data) => api.post('/auth/users', data),
  updateUser: (userId, data) => api.put(`/auth/users/${userId}`, data),
  deleteUser: (userId) => api.delete(`/auth/users/${userId}`),
}

// ── Mapping ──
export const mappingApi = {
  listVersions: () => api.get('/mapping/versions'),
  createVersion: (data) => api.post('/mapping/versions', data),
  discoverTasks: (versionId) => api.post(`/mapping/versions/${versionId}/discover`),
  listPurposes: (versionId) => api.get('/mapping/purposes', { params: { version_id: versionId } }),
  createPurpose: (data) => api.post('/mapping/purposes', data),
  updatePurpose: (purposeId, data) => api.put(`/mapping/purposes/${purposeId}`, data),
  deletePurpose: (purposeId) => api.delete(`/mapping/purposes/${purposeId}`),

  // ── v5: JSON 树管理（按轮次） ──
  // previewTree 会触发 S3 探测；给较长超时（concurrency=8 × 5s timeout per leaf）
  previewTree: (versionId, jsonText) => {
    if (!jsonText || typeof jsonText !== 'string') {
      return Promise.reject(new Error('jsonText 必填且为字符串'))
    }
    return api.post(
      `/mapping/versions/${versionId}/tree`,
      { json: jsonText },
      { params: { mode: 'preview' }, timeout: 120000 },
    )
  },
  // appendTree 写库 + 跨 round 冲突检查；超时给 60s 兜底
  appendTree: (versionId, jsonText, note) => {
    if (!jsonText || typeof jsonText !== 'string') {
      return Promise.reject(new Error('jsonText 必填且为字符串'))
    }
    if (!note || typeof note !== 'string') {
      return Promise.reject(new Error('note 必填（轮次备注）'))
    }
    return api.post(
      `/mapping/versions/${versionId}/tree/append`,
      { json: jsonText },
      { params: { note }, timeout: 60000 },
    )
  },
  listTrees: (versionId) => api.get(`/mapping/versions/${versionId}/trees`),
  // includeS3Probe 默认 false；开启会触发 S3 list_dir（按 leaf 数计费）
  getTree: (versionId, round, { includeS3Probe = false } = {}) =>
    api.get(`/mapping/versions/${versionId}/trees/${round}`, {
      params: { include_s3_probe: includeS3Probe },
      timeout: includeS3Probe ? 60000 : 30000,
    }),
  deleteTree: (versionId, round) =>
    api.delete(`/mapping/versions/${versionId}/trees/${round}`),
  createTasksFromTree: (versionId, round) =>
    api.post(`/mapping/versions/${versionId}/trees/${round}/create_tasks`, null, {
      timeout: 120000, // S3 探测 + DB 写
    }),
  autoFetchTree: (versionId, executionId) =>
    api.post(`/mapping/versions/${versionId}/tree/auto-fetch`, null, {
      params: { execution_id: executionId },
    }),
  updateNote: (versionId, round, note) => {
    if (!note || typeof note !== 'string') {
      return Promise.reject(new Error('note 必填'))
    }
    return api.put(`/mapping/versions/${versionId}/trees/${round}/note`, { note })
  },
}
