# Log Analyzer

> 自动化测试日志解析与智能分类平台 — 从 S3 / RustFS 拉测试执行结果，按规则引擎自动归类失败事件，支持多轮次回放和人工审核。

## 它做什么

CI 测试系统在 S3 上每天产出大量日志（按 `package_version / task_id / node_id / task_block_id` 路径组织），其中 HTML 报告 + `summary_report.yaml` 描述每次执行的测试套 / 测试用例结果。本平台：

1. **按 JSON 任务树批量建分析任务** — 粘贴测试系统的任务树 JSON，逐叶子探测 S3 路径，批量创建分析任务
2. **自动分类失败事件** — 解析 HTML / log → 定位失败 → 套用规则（builtin / 用户自定义）归类成根因
3. **多轮次回放** — 同一版本可以追加多轮 JSON 树，对比「同一用例在不同轮次的执行情况」
4. **人工审核 / 覆盖** — UI 展示自动分类结果，人工可确认或覆盖，支持键盘审核 (R / O / Space)
5. **完整重分析** — 改了规则 / 解析器代码后，一键清旧数据重跑整条流水线

## 主要页面

| 页面 | 路径 | 用途 |
|---|---|---|
| Dashboard | `/` | 总体分析趋势、Top 类别、统计 |
| 任务列表 | `/tasks` | 全部 Task，可批量启动 / 重新分析 |
| 任务详情 | `/tasks/:id` | 单任务的文件级结果 + JSON 树视图（按轮次） |
| 映射管理 | `/mapping` | 测试版本 + JSON 树轮次管理 |
| 审核 Dashboard | `/review` | 待人工确认 / 覆盖列表（连续审核） |
| 规则编辑 | `/rules` | 用户规则的 CRUD + publish / sync |

## 技术栈

**Backend** (`backend/`)
- Python 3.8+ / FastAPI / SQLAlchemy 2.0 async / aiosqlite / Pydantic v2
- BeautifulSoup + lxml（HTML 报告解析）
- PyYAML（summary_report 解析）
- pytest + pytest-asyncio（测试 ~80 用例）

**Frontend** (`frontend/`)
- Vue 3 (Composition API + `<script setup>`) / Vue Router
- Element Plus / @element-plus/icons-vue
- Axios / Vite 6

**Storage**
- RustFS / S3 兼容对象存储 — 详见 `rustfs-folder-design.md`
- 路径格式: `s3://<bucket>/<prefix>/<version>/<task_id>/<node_id>/<task_block_id>/{upload,analyzer}/`

## 快速开始

### 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"       # Windows
# source .venv/bin/activate && pip install -e ".[dev]"   # Linux/Mac

.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

启动后访问：
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

第一次启动会跑 `init_db()` 自动建表 + `_apply_manual_migrations()` 兜底补列。

### 前端

```bash
cd frontend
npm install
npm run dev     # http://localhost:5173
```

默认连接 `http://localhost:8000/api`（见 `vite.config.js`）。

### 环境变量

后端通过 `.env` 或环境变量读取（参见 `backend/app/config.py`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LA_S3_BUCKET` | `""` | RustFS / S3 bucket 名称 |
| `LA_S3_PREFIX` | `""` | object key 前缀 |
| `LA_S3_ACCESS_KEY` | `""` | S3 access key |
| `LA_S3_SECRET_KEY` | `""` | S3 secret key |
| `LA_S3_ENDPOINT_URL` | `""` | RustFS / MinIO 自定义 endpoint，留空走 AWS S3 |
| `LA_APP_DEBUG_LOGGING` | `true` | dev 模式 (INFO/DEBUG)，生产可设为 `false` 只看 WARNING |
| `LA_LOG_FILE` | `./data/app.log` | 日志文件路径 |
| `LA_DB_URL` | `sqlite+aiosqlite:///./data/log_analyzer.db` | 数据库 URL |

## 项目结构

```
log_ana/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routers
│   │   │   ├── analysis.py    # 分析流水线 / rerun / run_batch
│   │   │   ├── mapping.py     # TestVersion / JSON 树管理 / 任务映射
│   │   │   ├── review.py      # 人工确认 / 覆盖 / 归档
│   │   │   ├── rules.py       # 规则 CRUD + sync
│   │   │   ├── tasks.py       # Task CRUD
│   │   │   └── ...
│   │   ├── models/        # SQLAlchemy ORM
│   │   ├── services/      # 业务逻辑
│   │   │   ├── log_parser.py        # HTML / log → LogEntry
│   │   │   ├── failure_detector.py   # LogEntry → FailureEvent
│   │   │   ├── rule_executor.py      # FailureEvent → AnalysisResult
│   │   │   ├── task_tree.py          # JSON 解析 + 跨 round 冲突
│   │   │   ├── task_tree_s3.py       # S3 叶子探测
│   │   │   └── ...
│   │   └── core/          # audit_logger / logging_setup
│   ├── rules/             # 内置规则（Python 脚本动态加载）
│   ├── tests/             # pytest 套件
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── views/         # 顶层页面
│   │   ├── components/    # 共享组件（含 TaskTreeNode / TreeNode / ReviewDrawer）
│   │   └── api/           # Axios 客户端 + 所有 API 绑定
│   └── package.json
├── example_task_result*.json      # JSON 树格式样例
├── summary_report_example.yaml     # S3 summary_report 样例
├── rustfs-folder-design.md         # S3 路径设计契约
├── ui improvement.md               # UI 改进实施计划（总览）
├── ui improvement - task tree grouping.md
└── task_tree_implementation_progress.md
```

## 关键特性

### v5：JSON 任务树 + 多轮次回放

测试系统的任务结构是一棵 JSON 树（如 `S1-10G-8S28/R45_B2B_part1` → 子任务）。v5 引入了完整的任务树管理：

- **追加轮次**：版本下可追加多棵 JSON 树，自动 `round_number += 1`
- **S3 叶子探测**：解析 JSON 时探测每个叶子 Id 在 S3 上的路径存在性，作为「可建任务」标记
- **跨轮次冲突检查**：同 leaf_id 已存在其他轮次 → 整次 append 拒绝
- **任务详情两个视图**：
  - **单轮次视图**（默认）：左树 + 顶部轮次选择器 + 右表 = 当前 round 的 TestCase 行
  - **整体视图**：左树（round=1 骨架）+ 右表 = 跨 round 聚合的 TestCase 行（每行带执行次数 / 参与轮次 / 最新结果）
- **数据缺失告警**：节点存在但 S3 没数据 = 日志缺失

参见 `ui improvement - task tree grouping.md`（设计）和 `task_tree_implementation_progress.md`（实施记录）。

### v6：批量操作 + 完整重分析

| 端点 | 用途 |
|---|---|
| `POST /api/analysis/run_batch` | 批量启动分析（一次 ≤200 个 Task） |
| `POST /api/analysis/{id}/rerun` | 单任务完整重分析（清旧数据 + 后台重跑） |
| `POST /api/analysis/rerun_batch` | 批量完整重分析 |
| `POST /api/analysis/{id}/files` | 列文件分析结果（含 `summary_report` 元数据） |
| `POST /api/mapping/tree/append` | 追加 JSON 树轮次 |
| `GET  /api/mapping/tree/{round}` | 获取轮次（返回嵌套树） |

#### 完整重分析的关键设计

`_reset_task_data()` 按外键依赖顺序清 `Feedback → AnalysisResult → FailureEvent → LogEntry / TestCase → Archive / HighValue → LogFile`：

- **LogFile 必须清**：上一版只 reset `review_status`，保留 row，但因为表无 `(task_id, file_path)` 唯一约束，`parse_log_file` 重跑会留下旧 + 新两份 row，每文件 UI 列表显示两次（已修）
- **commit 后用新 session 二次验证** `COUNT(*)`，leftover > 0 则拒绝启动 pipeline（防御 SQLite + async 极端 race）
- **`preserve_review` 选项**（`run_batch` / `rerun` body 里 `false`）：
  - `False`（默认）：review 字段全部重置，Archive / HighValue 删除
  - `True`：Archive / HighValue 保留

### v4：原始结果联动 summary_report

`summary_report.yaml`（测试系统元数据）映射到分析结果的左侧三列：

- 原始结果（Success / failed / blocked）→ `el-tag` 颜色
- 用例 / 套件 ID + desc
- 失败原因（截断 + tooltip）

缺 YAML → 返回 `null` 不报错；缺字段 → 用 `—` 占位。

### 规则引擎

- **Builtin 规则**：在 `backend/rules/` 下的 Python 模块，运行时由 `rule_registry` 动态加载
- **用户规则**：用 `RULE_TEMPLATE.md` 模板写，存数据库，通过 RuleEditor 发布
- **匹配方式**：
  - `parallel`（默认）：所有 enabled 规则并行 evaluate，取最佳
  - `serial`：按 priority 顺序逐个试，首次匹配返回
  - 详见 `RULE_GUIDE.md`

### 人工审核

- **ReviewDashboard** 是连续审核模式：键盘 ← / → 翻页，`R` confirm、`O` override、`Space` skip
- **快速操作**：基于 rank=1 的 primary result 出判定，自动 upsert Feedback（用于反馈统计）
- **审核 / 覆盖状态**：LogFile 表上 `review_status = pending|confirmed|overridden` + `override_*` 字段
- **归档**（ArchivedReview）：永久不再显示在待处理页

## 文档索引

| 文件 | 内容 |
|---|---|
| `README.md`（本文件） | 项目总览 / 快速开始 / 特性 |
| `rustfs-folder-design.md` | S3 路径契约（uploader / analyzer 边界） |
| `ui improvement.md` | v4 UI 改进（summary_report 联动） |
| `ui improvement - task tree grouping.md` | v5 UI 改进（任务树 + 多轮次 + 双视图） |
| `task_tree_implementation_progress.md` | v5 完整实施进度（commit / 决定 / 已知坑） |
| `backend/RULE_TEMPLATE.md` | 用户规则编写模板 |
| `backend/RULE_GUIDE.md` | 规则系统完整指南 |
| `backend/README.md` | 后端开发说明 |
| `frontend/README.md` | 前端开发说明 |

## 测试

```bash
cd backend
.venv\Scripts\python.exe -m pytest -q          # 全套约 ~80 用例
.venv\Scripts\python.exe -m pytest tests/test_task_tree.py -v
```

测试用 in-memory SQLite，跑得快；CI 可加 `--cov`。

## 已知坑 / 设计取舍

1. **`task.result_binding`**：version_id 是 12 字符 hex UUID，`version_name` 是用户在测试系统里写的字符串。调用 `probe_leaves_in_s3_batch` 时**必须**用 `version.version_name`——历史上因 fallback 路径错误传成了 version_id 主键，导致 S3 探测全 miss（已修，建议看 commit `100f481`）
2. **LogFile 表无唯一约束**：rerun 必须 `DELETE FROM log_files WHERE task_id = ?`，否则同 `file_path` 会存两份
3. **`compute_name_key` 名字聚合**：`name.rsplit('_', 1)[0]` 对 `BGP0_reRun6458` 这种「基础名 = 整段名字」会切错最后一段（v5 决策接受这个误伤）
4. **分析流水线是后台任务**：通过 FastAPI `BackgroundTasks` 异步跑，状态由前端轮询（`/tasks/:id` 自动 refresh）
5. **SQLite in dev**：并发写有锁，生产环境建议迁 Postgres（改 `LA_DB_URL` 即可，不用改代码）

## License

Internal / 项目内部使用。
