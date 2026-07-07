# Frontend — Log Analyzer

Vue 3 (Composition API + `<script setup>`) + Element Plus + Axios + ECharts。

## 目录

```
frontend/
├── src/
│   ├── api/
│   │   └── index.js            # Axios 实例 + 所有 API 绑定（taskApi / analysisApi / mappingApi / reviewApi / rulesApi / browseApi / feedbackApi / authApi）
│   ├── components/
│   │   ├── TreeNode.vue        # 文件浏览器树组件（看 node.type / _children）—— 用于 FileTree
│   │   ├── TaskTreeNode.vue    # 任务树节点组件（看 node.children / is_leaf / s3_matched）—— 用于 MappingManager
│   │   ├── FileTree.vue        # 浏览器面板，用 TreeNode
│   │   ├── ReviewDrawer.vue    # 审核抽屉（人工 confirm / override）
│   │   └── layout/             # AppPageHeader / AppSection 等共用布局
│   ├── views/                  # 顶层页面（Vue Router 入口）
│   │   ├── Dashboard.vue
│   │   ├── TaskList.vue         # /tasks — Task 列表 + 多选 + 批量启动 / 重分析
│   │   ├── TaskDetail.vue       # /tasks/:id — 详情 + JSON 树 + S3 探测 + 重新分析
│   │   ├── MappingManager.vue   # /mapping — 版本 + JSON 树轮次管理
│   │   ├── ReviewDashboard.vue  # /review — 人工审核（键盘友好）
│   │   ├── RuleEditor.vue       # /rules — 规则 CRUD
│   │   ├── UserManager.vue      # /users
│   │   ├── Browser.vue          # /browser — S3 文件浏览
│   │   └── Login.vue
│   ├── router.js
│   ├── App.vue
│   └── main.js                  # Element Plus + Element Plus Icons 全局注册
└── package.json
```

## 跑起来

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

Vite 默认 `proxy` 把 `/api` 转发到 `http://localhost:8000`（见 `vite.config.js`）。

## 关键概念

### 两类树组件

**重要区分**——别用错：

| 组件 | 数据形状 | 用例 |
|---|---|---|
| `TreeNode.vue` | `{ type, name, path, size, _children }` | 文件浏览器（FileTree、S3 浏览） |
| `TaskTreeNode.vue` | `{ name, node_id, is_leaf, s3_matched, children: [...] }` | 任务树（MappingManager preview / view、TaskDetail 树） |

错用会让子树渲染不出来（详见 `frontend/src/components/TaskTreeNode.vue` 头部注释）。

### 多选 / 批量操作（TaskList）

`/tasks` 页面：
- `el-table-column type="selection"` 多选
- `:selectable="row => isActionable(row)"` —— 根据状态决定哪些行能勾（pending / failed / completed）
- `batchResultAction: 'start' | 'rerun'` 决定结果 dialog 语义
- `batchSubmitting`、`batchResultVisible` 等 state 在 setup() 顶层

### 状态自动轮询（TaskDetail）

```js
function startAutoRefresh() {
  refreshTimer = setInterval(async () => {
    if (task.value?.status === 'parsing' || task.value?.status === 'analyzing') {
      await loadTask()
    }
  }, 3000)
}
```

rerun / run 启动后调一次，task 进 completed / failed 自动停。

### localStorage 鉴权

```js
// 登录后存
localStorage.setItem('token', token)
localStorage.setItem('user', JSON.stringify(user))

// axios 拦截器
api.interceptors.request.use(config => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})
```

`user.role` 决定 UI 权限（`canStartTask` computed）。

## 样式约定

- 用 Element Plus 主题变量：`var(--color-primary)`、`var(--text-small)`、`var(--space-md)` 等
- 别写散落的 #hex，全走 CSS 变量；详见 `src/assets/`（如果有）
- 表格 row 高 / cell padding 走 `var(--table-row-h)` / `var(--table-cell-py)`

## 国际化

当前仅中文。所有 el-table / dialog 的 label 直接写在模板里。如需多语言，可改用 `vue-i18n`。
