# 新增规则确认模板

使用此模板收集新增规则所需的全部信息，确认后即可编码。

---

## 1. 基本信息

| 字段 | 说明 | 示例 |
|------|------|------|
| `rule_id` | 唯一标识符（snake_case，见名知义） | `agile_test_failed` |
| `name` | 规则显示名称（中文简短描述） | `AgileTest 失败检测` |

## 2. 匹配条件

| 字段 | 说明 | 示例 |
|------|------|------|
| 匹配特征 | 失败块中识别该错误的关键字符串或正则 | `"AssertionError: False is not true : Agile test run failed"` |
| 匹配方式 | `exact`（精确子串）或 `regex`（正则表达式） | `exact` |
| 文件限制 | `all`（全部文件）或 `html_only`（仅 .html） | `all` |

> **匹配输入**：规则从 `ctx.failure_event.relevant_log`（失败块文本）中查找特征，fallback 到 `ctx.traceback`。特征只需**包含在块中任意一行**即可命中。

## 3. 分类与优先级

| 字段 | 说明 | 示例 |
|------|------|------|
| `category` | `大类/子类` 两级路径。大类必须存在于 `DEFAULT_CATEGORY_TREE` 或手动添加 | `产品问题/AgileTest失败` |
| 是否需要新增分类到 `database.py` | 见下方分类树 | — |
| `priority` | 见下方优先级区间 | `9` |

### 优先级分配参考

| 区间 | 含义 | 示例 |
|------|------|------|
| **0–19** | 确定性强、特征唯一的故障签名 | 特定错误码、唯一字符串 |
| **20–49** | 一般性故障类型 | 断言失败、超时、通用异常 |
| **50+** | 宽泛兜底 | 泛化 Error 关键字 |

**必须指定该规则与现有规则的先后关系**（谁更优先匹配）：

```
现有优先级链：
  9  agile_test_failed        → 产品问题/AgileTest失败
 10  assertion_error           → 产品问题/断言失败 (仅 html)
 15  port_reserved_error       → 产品问题/端口占用失败
 16  firmware_version_mismatch → 环境问题/版本不匹配
 20  runtime_error             → 产品问题/未知问题

新规则 priority = ?
排在哪条规则之前/之后？理由？
```

## 4. 置信度

| 字段 | 说明 | 示例 |
|------|------|------|
| `confidence` | 0.0~1.0。`≥0.7` 高可信（绿色），`0.3~0.7` 需注意（黄色） | `0.95` |

## 5. 当前分类树

```
环境问题 → 工具问题, 端口被占用, 环境映射失败, 版本不匹配
脚本问题 → 等待时间问题, 脚本逻辑问题, 前后脚本影响
产品问题 → 断言失败, 已知问题, 未知问题, 端口占用失败, AgileTest失败
无法识别 → 测试套失败
```

> 如果新规则的子类不在上述列表中，需要同时修改 `app/database.py` 的 `DEFAULT_CATEGORY_TREE`。

---

## 确认清单

```
□ rule_id:     _______________
□ name:        _______________
□ 匹配特征:    _______________
□ 匹配方式:    exact / regex
□ 文件限制:    all / html_only
□ category:    _______________ / _______________
□ 需加分类:    是 / 否（若是，写清楚父子类名）
□ priority:    ___
□ 与现有规则的关系: _______________
□ confidence:  ___
```

---

## 代码模板

确认上述信息后，按以下模板编写规则文件 `backend/rules/<rule_id>.py`：

```python
from __future__ import annotations

from rules.base import BaseRule, RuleContext, RuleResult

# 【匹配特征】直接子串匹配用 MARKER，正则匹配用 PATTERN
MARKER = "目标字符串"


class RuleClassName(BaseRule):
    """规则描述：匹配特征 → 分类。"""

    @property
    def rule_id(self) -> str:
        return "rule_id_here"

    @property
    def name(self) -> str:
        return "规则显示名称"

    @property
    def category(self) -> str:
        return "大类/子类"

    @property
    def priority(self) -> int:
        return 0  # 替换为实际值

    @property
    def description(self) -> str:
        return "描述匹配条件和分类逻辑的一句话"

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        # ── 可选：文件类型过滤 ──
        # log_file = ctx.failure_event.get("log_file") or {}
        # if not str(log_file.get("name", "")).lower().endswith((".html", ".htm")):
        #     return RuleResult.no_match()

        # ── 匹配逻辑 ──
        block = ctx.failure_event.get("relevant_log") or ctx.traceback or ""
        if MARKER not in block:
            return RuleResult.no_match()

        # ── 提取命中行作为证据 ──
        hit_line = next(
            (line.strip() for line in block.split("\n") if MARKER in line),
            MARKER,
        )

        # ── 返回匹配结果 ──
        return RuleResult.match(
            category=self.category,
            confidence=0.9,            # 替换为实际值
            evidence=hit_line,
            line_start=ctx.failure_event.get("line_start"),
            line_end=ctx.failure_event.get("line_end"),
        )
```

> **子串匹配**直接用 `if MARKER in block:`，**正则匹配**参考 `port_reserved_error.py` 或 `firmware_version_mismatch.py` 的写法。
