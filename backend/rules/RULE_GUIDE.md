# 规则实现指南（Rule Implementation Guide）

本文档面向规则脚本作者，描述规则的生命周期、输入输出契约、排序/最终结论语义，
以及当规则设计或返回结果需要变更时应遵循的约定。

## 1. 规则生命周期

1. **发现**：`rules/` 目录下每个继承 `BaseRule` 的模块在启动时被
   `rule_registry.discover()` 加载，并通过 `sync_to_db()` 写入 `analysis_rules` 表。
2. **执行**：分析流水线（解析 → 失败检测 → 分类）对每个 `FailureEvent`
   依次评估所有已启用规则：
   - `LA_RULE_EXECUTION_MODE=serial`（默认）：按 `priority` 升序逐条评估，**首个
     matched 即终止**。
   - `parallel`：并发评估全部规则；`rule_first_match_wins=true` 时取
     `(priority 最小, confidence 最高)` 的匹配，否则取 `(confidence 最高, priority 最小)`。
3. **落库**：匹配产生一条 `AnalysisResult`；无任何匹配时产生 fallback 结果
   （类别"无法识别"，`is_fallback=True`）。

## 1.5 html 日志的全局预处理（重要）

本阶段仅解析 `.html` 文件，且解析时执行以下全局处理
（`log_parser.py`，对所有规则生效）：

1. **公共页头剔除**：以下区块仅用于导航/过滤，不属于日志内容，解析前直接移除
   （`HTML_EXCLUDED_SELECTORS`）：
   - `div` with `class="filters if_js"`
   - `div` with `id="hellobaby"`
   - `div` with `id="mainAnchorDivId"`
2. **只分析红色文本**：所有行都会入库（审核界面保留完整上下文），但只有红色
   文本被标记 `is_error=True` 并参与失败检测。红色判定（含祖先元素继承，
   `log_parser._is_red_element`）：
   - inline style 的 `color:`（不含 background-color），或
   - `color` 属性（如报告中的 `<font color="#E64046">`），或
   - class 名含 error/fail/red。
   颜色值支持颜色名（red/darkred/crimson 等）、`#rgb`/`#rrggbb`、`rgb(r,g,b)`；
   十六进制/rgb 按分量启发式判断偏红（R≥160 且明显高于 G/B，见
   `_is_red_color_value`）。
3. **失败块 = 连续红色行**：相邻的红色行归并为一个块，每块产生一个
   `FailureEvent`（`failure_detector._detect_red_blocks`），`relevant_log` /
   `traceback` 即整块文本，`line_start/line_end` 为块的行号范围。块按文档顺序
   生成，因此"包含某字符串的第一个块"天然对应行号最小的匹配结果。

## 1.6 当前规则集

| rule_id | priority | 适用范围 | 匹配条件 | 分类 |
|---------|----------|----------|----------|------|
| `assertion_error` | 10 | 仅 html 文件 | 失败块含 `AssertionError:` | 产品问题/断言失败 |
| `port_reserved_error` | 15 | 全部文件 | 失败块含 `RuntimeError: ... Port ... reserved error.` | 产品问题/端口占用失败 |
| `runtime_error` | 20 | 全部文件 | 失败块含 `RuntimeError:` | 产品问题/未知问题 |

注意：`port_reserved_error` 是 `runtime_error` 的特化——同一块两者都会匹配时，
priority 较小的端口规则胜出；其余 RuntimeError 落入未知问题。

"第一个匹配块为根因"由排序键 `(priority, -confidence, line_start)` 保证：
assertion_error 的 priority 更小，故文件中同时存在两类错误时，断言失败块
（即便出现在更后面）优先成为最终结论；同一规则的多个匹配块取最早者。

## 2. 输入：RuleContext

| 字段 | 说明 |
|------|------|
| `failure_event` | 失败事件字典：`script_name`、`exception_type`、`exception_message`、`traceback`、`relevant_log`、`line_start`/`line_end`（源文件内行号范围）、`log_file`（`{"name", "file_type", "testcase_name"}`，`file_type` 为 `testsuite`/`testcase`/`task_log`） |
| `log_entries` | 失败行 ±20 行的上下文条目（`line_number`、`level`、`message`、`raw_line` 等） |
| `traceback` | Python traceback 纯文本 |
| `workspace_path` | 任务工作区，可写临时文件 |
| `extra_files` | 按 `required_files()` 声明预取的附加文件内容 `{filename: content}` |

规则可通过 `failure_event["log_file"]["file_type"]` 针对测试套/测试用例做差异化判断。
本阶段仅 `.html` 文件会被解析（testsuite 报告 + 各 testcase 的 main html）。

## 3. 输出：RuleResult

```python
return RuleResult.match(
    category="脚本缺陷/断言失败",   # "大类/子类" 路径；缺失的节点会自动创建
    confidence=0.85,                # 0.0 ~ 1.0
    evidence="traceback 中包含断言: assert x == y",  # 必须引用决定性的日志内容
    line_start=215, line_end=216,   # 可选：证据行号；缺省采用失败事件的行号范围
    fw_version="2.4.0",             # 其余 kwargs 进入 extractions（结构化提取）
)
```

约定：

- **category 必须使用 `大类/子类` 两级路径**（如 `环境问题/设备失联`）。只写大类名
  会归入大类本身，仅在该大类确实没有子类时使用。当前默认分类树见
  `app/database.py:DEFAULT_CATEGORY_TREE`，运行期通过 `/api/tasks/categories` 管理。
- **evidence 应直接引用决定性的日志行**，审核人会拿它与原始日志对照。
- confidence 语义：`>=0.7` 高可信（UI 绿色），`0.3~0.7` 需人工注意（黄色）。

## 4. 排序与最终结论（重要）

一条规则只对**单个失败事件**分类；之后执行器按**日志文件**聚合
（`rule_executor._rank_results_per_file`）：

- 每个文件最多保留 **2 条主要错误**：排序键为
  `(规则 priority 升序, confidence 降序, 失败行号升序)`；
  第 1 名 `rank=1`，第 2 名 `rank=2`，其余 `rank=NULL`。
- **`rank=1` 即该文件的最终结论（唯一根因）**；`rank=2` 与 `rank=NULL` 仅在
  UI 的"其他可能原因"区展示，不影响最终结果。
- 仅有 fallback 结果的文件，取其一作为 `rank=1`（最终结论 = 无法识别）。

**含义**：`priority` 直接决定根因选择。分配建议：

| priority 区间 | 用途 |
|---------------|------|
| 0–19 | 确定性强、特征唯一的故障签名（如特定错误码） |
| 20–49 | 一般性故障类型（断言失败、超时等） |
| 50+  | 宽泛的兜底模式（泛化的 Error 关键字匹配） |

新规则若总被更高优先级规则"抢走"根因位，优先检查 priority 是否过大，而不是
盲目调高 confidence——serial 模式下 confidence 不参与先后裁决。

## 5. 人工审核如何反哺规则

审核人在 UI 上对每个文件做 确认 / 覆盖 / 重置：

- **确认** → rank=1 结果获得 `Feedback(is_correct=True)`。
- **覆盖** → rank=1 结果获得 `Feedback(is_correct=False,
  suggested_category_id=人工选择的子类, comment=审核备注)`；同时 `log_files`
  表记录 `override_category_id`、`override_evidence`、`override_line_start/end`。

定位需要改进的规则（覆盖率高 = 误判多）：

```sql
SELECT r.rule_id, COUNT(*) AS overridden
FROM feedbacks f
JOIN analysis_results ar ON ar.id = f.analysis_result_id
JOIN analysis_rules  r  ON r.id = ar.rule_id
WHERE f.is_correct = 0
GROUP BY r.rule_id ORDER BY overridden DESC;
```

`feedbacks.comment`（审核备注）与 `log_files.override_evidence`（人工选择的证据行）
是改写规则匹配逻辑时最直接的素材。

## 6. 变更规则输出时的注意事项

- **改 category 名/路径**：类别按名字 get-or-create——改名后会创建新节点，旧结果仍
  指向旧节点。需要迁移时手工 UPDATE `analysis_results.category_id`，或保留旧节点
  仅停止使用。
- **改 priority**：会改变所有后续分析的根因选择顺序；调整后应抽查若干历史任务的
  rank=1 是否仍合理。
- **改 confidence 公式**：serial 模式不影响匹配先后，仅影响 UI 展示与 parallel
  模式裁决。
- **删除/禁用规则**：通过 DB 中 `analysis_rules.enabled=false` 禁用，不要直接删
  文件（历史结果的 `rule_id` 外键仍引用它）。
- 规则崩溃不会中断流水线：异常被记入审计日志并计入 fallback 证据
  （"N 条出错"），但应尽量在规则内部自行兜底。
