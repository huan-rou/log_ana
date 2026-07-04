# UI Improvement Plan: Summary Report Metadata in Task Detail

## Summary
Implement a Task Detail table enhancement that surfaces original testsuite/testcase metadata from `metadata/summary_report.yaml`. The current code still returns only analyzer fields from `GET /api/analysis/{task_id}/files`, and `frontend/src/views/TaskDetail.vue` still renders the original file/analyzer/review columns.

## Backend Changes
- Add YAML support:
  - Add `PyYAML>=6.0.0` to `backend/requirements.txt`.
  - Add `PyYAML>=6.0.0` to `backend/pyproject.toml` dependencies.
- Add a small summary-report loader near `backend/app/api/analysis.py` helpers:
  - Use `yaml.safe_load`.
  - Read `metadata/summary_report.yaml` through `provider_manager.read_file("s3", path)` for RustFS/S3.
  - For local uploads, support only structured local upload layouts that contain `metadata/summary_report.yaml`; otherwise return `None`.
  - Never fail `/api/analysis/{task_id}/files` if YAML is missing, malformed, or unreadable; return `summary_report: null`.
- Derive report path from each `LogFile.source_dir`:
  - If `source_dir` contains `/artifacts/`, use the prefix before `/artifacts/` and append `/metadata/summary_report.yaml`.
  - Example: `<upload>/artifacts/testcases/TC_id_1/main` maps to `<upload>/metadata/summary_report.yaml`.
  - Cache parsed reports per `(provider, report_path)` during one request to avoid repeated reads.
- Normalize YAML into lookup records:
  - Input schema is `testsuites[]`, each with `id`, `desc`, `result`, `start_time`, `end_time`, `fail_detail`, and nested `testcases[]` with the same useful fields.
  - Build suite lookup by lowercased `id`, `desc`, and stem-like names.
  - Build testcase lookup by lowercased testcase `id`, `desc`, and `LogFile.testcase_name` candidates.
- Extend `GET /api/analysis/{task_id}/files` response with:
  - `summary_report: null | { suite_id, suite_desc, suite_result, case_id, case_desc, case_result, display_result, normalized_status, start_time, end_time, fail_detail, fail_reason_short, source_path }`
  - For testcase files, prefer testcase fields and include parent suite fields.
  - For testsuite files, use suite fields and leave testcase fields null.
  - For task logs, return `summary_report: null`.
- Result normalization:
  - Known statuses are case-insensitive: `Success`, `failed`, `blocked`.
  - `Success` maps to `normalized_status: "success"`.
  - `failed` maps to `normalized_status: "failed"`.
  - `blocked` maps to `normalized_status: "blocked"`.
  - Any other status preserves original `display_result` but maps to `normalized_status: "blocked"`.
- Short failure reason:
  - Collapse whitespace in `fail_detail`.
  - Use about 120 characters plus `...` when truncated.
  - Empty or missing `fail_detail` becomes an empty string, not an error.

## Frontend Changes
- Update `frontend/src/views/TaskDetail.vue` only for the main Task Detail `分析结果` table.
- Add helper functions:
  - `summaryResult(row)` returns `row.summary_report?.display_result || '—'`.
  - `summaryStatusTag(row)` maps `success -> success`, `failed -> danger`, `blocked -> warning`.
  - `summaryIdentity(row)` returns testcase `case_id / case_desc` for testcase rows, suite `suite_id / suite_desc` for testsuite rows, or `—`.
  - `summaryFailReason(row)` returns `fail_reason_short || '—'`.
- Add table columns between file type and analyzer conclusion:
  - `原始结果`, width about `100`, colored `el-tag`.
  - `用例/套件`, min-width about `180`, show `case_id`/`suite_id` prominently and `desc` as secondary text when present.
  - `失败原因`, min-width about `220`, use `show-overflow-tooltip` or an `el-tooltip` with full `fail_detail`.
- Keep existing analyzer columns:
  - `最终结论`, `置信度`, `匹配规则`, `审核状态`, and `审核`.
- Preserve current behavior:
  - Existing filters by review status and file type continue to call `loadFiles`.
  - Opening the review drawer still passes `row.id`.
  - Missing summary report data renders as `—`, without affecting review or analysis state.
- Styling:
  - Keep dense, table-first layout.
  - Use compact text classes for id/description and a muted secondary line for descriptions.
  - Do not move this feature into `ReviewDrawer.vue`.

## Test Plan
- Backend:
  - Add focused tests for parsing `summary_report_example.yaml`.
  - Verify testcase match by `LogFile.testcase_name == TC_id_1`.
  - Verify testsuite match by suite `id` or single-suite fallback.
  - Verify `Success`, `failed`, `blocked`, and unknown result normalization.
  - Verify missing/malformed YAML returns `summary_report: null` and does not fail the files endpoint.
- Frontend:
  - Run `npm run build`.
  - Manually verify the Task Detail table with rows containing `summary_report`.
  - Check long `fail_detail` truncation and tooltip/full text visibility.
  - Check unknown result text displays verbatim but uses blocked/warning styling.
- Regression:
  - Existing analysis result review flow still opens the drawer.
  - Existing file type and review filters still work.
  - Existing analyzer conclusion and confidence rendering remains unchanged.

## Assumptions
- The plan file target is exactly `D:\log_analyzer\ui improvement` with no extension.
- The implementation should not persist summary report metadata into SQLite for this iteration; it is read on demand from storage.
- `summary_report.yaml` is the authoritative source for original testsuite/testcase result, description, timing, and failure detail.
- RustFS/S3 upload layout follows `rustfs-folder-design.md`, where metadata lives under `<upload>/metadata/summary_report.yaml`.
