# RustFS Folder Design for Uploader and Analyzer

## Summary

Use one shared RustFS bucket and one shared run identity path, but separate ownership below each run folder.

The uploader writes immutable source evidence under `upload/`. The analyzer reads `upload/` and writes derived analysis under `analyzer/`.

## Folder Layout

```text
s3://<bucket>/<prefix>/
  <package_version>/
    <task_id>/
      <node_id>/
        <task_block_id>/
          upload/
          analyzer/
```

Example:

```text
s3://ci-logs/automation/
  1.2.3/
    nightly_regression/
      ci-node-001/
        task-block-20260606-001/
          upload/
          analyzer/
```

Path segment meaning:

- `<package_version>` identifies the released package version under test.
- `<task_id>` identifies the automation test task or suite trigger.
- `<node_id>` identifies the CI machine or worker node.
- `<task_block_id>` is the normalized folder name of the `--task-root` parameter and must be unique within the package/task/node path.

## Uploader-Owned Folder

The uploader writes only this folder:

```text
<task_block_id>/
  upload/
    summary.json
    manifest.json
    upload_report.json

    metadata/
      env.xml
      summary_report.yaml
      autotask.yaml
      tdb_config.json
      sources/
        <original sqlite/yaml/json/xml metadata files>

    indexes/
      text_index.json

    artifacts/
      task/
        AgentTaskLog.log
        HwtdlAgent_Python.log
        TaskRunLog_Python.log
        debug.timestamp.log
        error.timestamp.log

      testsuite/
        testsuitereport.irpx
        testsuitename.html

      testcases/
        <testcase_name>/
          main/
            <testcase_name>.html
          raw/
            <testcase_name>_aux.zip

      raw/
        <all unmatched files>
```

Uploader rules:

- `upload/` is immutable after upload completion.
- `summary.json` is the analyzer's first entrypoint.
- `manifest.json` records every uploaded, archived, ignored, and raw-file decision.
- For paired `<name>.html` and `<name>.log`, upload only `.html` when `.log` contains the same content.
- Archive each testcase auxiliary folder as one raw artifact in `testcases/<testcase_name>/raw/`.
- Put unmatched files under `artifacts/raw/`.

## Analyzer-Owned Folder

The analyzer writes only this folder:

```text
<task_block_id>/
  analyzer/
    analysis_summary.json
    testcase_findings.json
    analyzer_report.json

    generated_indexes/
      testcase_index.json
      error_index.json
      search_index.json

    extracted_signals/
      failures.json
      warnings.json
      environment.json

    reports/
      human_readable_report.html
      compact_report.json

    human_notes/
      annotations.json

    ui_cache/
      <cache files>
```

Analyzer rules:

- Analyzer must not modify `upload/`.
- Analyzer outputs should reference uploader artifacts by object key or artifact id.
- Analyzer may regenerate files under `analyzer/`.
- Human notes, UI cache, and derived reports stay separate from immutable uploaded evidence.

## Permission Boundary

Recommended RustFS access model:

- Uploader credential:
  - write: `.../<package_version>/<task_id>/<node_id>/<task_block_id>/upload/`
  - read: optional, only for upload verification
  - no write access to `analyzer/`

- Analyzer credential:
  - read: `.../<package_version>/<task_id>/<node_id>/<task_block_id>/upload/`
  - write: `.../<package_version>/<task_id>/<node_id>/<task_block_id>/analyzer/`
  - no write access to uploader source files

- UI/human credential:
  - read: `upload/` and `analyzer/`
  - write only to controlled paths such as `analyzer/human_notes/`, if needed

## Assumptions

- Same RustFS bucket is shared by uploader and analyzer.
- Same `package_version/task_id/node_id/task_block_id` path is used to connect uploaded logs and analyzer results.
- `task_block_id` replaces `run_id` as the visible storage identifier and is derived from the `--task-root` folder name; if a generated ULID is still needed, store it inside `summary.json` and `manifest.json`.
- Ownership is separated by `upload/` and `analyzer/`, not by separate buckets.
- Retention/lifecycle policy is managed outside the uploader.
