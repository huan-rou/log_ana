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
  files: (taskId, params) => api.get(`/analysis/${taskId}/files`, { params }),
  fileDetail: (fileId) => api.get(`/analysis/files/${fileId}`),
  relatedFiles: (fileId) => api.get(`/analysis/files/${fileId}/related`),
  report: (taskId) => api.get(`/analysis/${taskId}/report`),
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
}
