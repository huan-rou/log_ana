// frontend API 客户端烟雾测试 — 验证 mapping/analysis API v5 方法
// 用 esbuild bundle + globalThis 共享 mock 状态

const path = require('path')
const fs = require('fs')
const esbuild = require(path.join(__dirname, 'node_modules', 'esbuild'))

// 全局状态（被 bundle 内的 mock 和 test 共享）
globalThis.__mockCalls = []
globalThis.__mockAxiosCreateCount = 0

const axiosStub = `
globalThis.__axiosStubCalls = globalThis.__axiosStubCalls || []
function make() {
  globalThis.__mockAxiosCreateCount++
  return {
    interceptors: { request: { use: () => {} }, response: { use: () => {} } },
    get: (...a) => { globalThis.__axiosStubCalls.push({ m: 'get', a }); return Promise.resolve({ data: { mocked: true } }) },
    post: (...a) => { globalThis.__axiosStubCalls.push({ m: 'post', a }); return Promise.resolve({ data: { mocked: true } }) },
    put: (...a) => { globalThis.__axiosStubCalls.push({ m: 'put', a }); return Promise.resolve({ data: { mocked: true } }) },
    delete: (...a) => { globalThis.__axiosStubCalls.push({ m: 'delete', a }); return Promise.resolve({ data: { mocked: true } }) },
    patch: (...a) => { globalThis.__axiosStubCalls.push({ m: 'patch', a }); return Promise.resolve({ data: { mocked: true } }) },
  }
}
module.exports = { create: make, __calls: globalThis.__axiosStubCalls }
module.exports.default = module.exports
`
const elStub = `module.exports = { ElMessage: { error: () => {} } }; module.exports.default = module.exports\n`

const axiosStubPath = path.join(__dirname, '.tmp-axios-stub.cjs')
const elStubPath = path.join(__dirname, '.tmp-elplus-stub.cjs')
fs.writeFileSync(axiosStubPath, axiosStub)
fs.writeFileSync(elStubPath, elStub)

const apiSrcPath = path.join(__dirname, 'src', 'api', 'index.js').replace(/\\/g, '/')
const entryPath = path.join(__dirname, '.tmp-entry.cjs')
fs.writeFileSync(entryPath, `module.exports = require(${JSON.stringify(apiSrcPath)})\n`)

const outPath = path.join(__dirname, '.tmp-bundled.cjs')

esbuild.build({
  entryPoints: [entryPath],
  bundle: true,
  format: 'cjs',
  platform: 'node',
  outfile: outPath,
  alias: { axios: axiosStubPath, 'element-plus': elStubPath },
  logLevel: 'error',
}).then(() => {
  const api = require(outPath)

  let pass = 0, fail = 0
  const assert = (cond, msg) => {
    if (!cond) { console.error('  FAIL:', msg); fail++ }
    else { console.log('  PASS:', msg); pass++ }
  }

  console.log('=== mappingApi ===')
  assert(typeof api.mappingApi === 'object', 'mappingApi exported')
  const expectedMapping = [
    'listVersions', 'createVersion', 'discoverTasks',
    'listPurposes', 'createPurpose', 'updatePurpose', 'deletePurpose',
    'previewTree', 'appendTree', 'listTrees', 'getTree', 'deleteTree',
    'createTasksFromTree', 'autoFetchTree', 'updateNote',
  ]
  for (const m of expectedMapping) {
    assert(typeof api.mappingApi[m] === 'function', `mappingApi.${m} is function`)
  }

  console.log('=== analysisApi ===')
  assert(typeof api.analysisApi === 'object', 'analysisApi exported')
  const expectedAnalysis = [
    'run', 'results', 'resultDetail', 'dashboard', 'files',
    'fileDetail', 'relatedFiles', 'report',
    'getTaskTrees', 'getTaskTree', 'getAggregate',
    'getAggregateTestcases', 'getTestcases',
  ]
  for (const m of expectedAnalysis) {
    assert(typeof api.analysisApi[m] === 'function', `analysisApi.${m} is function`)
  }

  const calls = () => globalThis.__axiosStubCalls
  const last = () => calls()[calls().length - 1]

  console.log('=== 调用行为 ===')
  ;(async () => {
    try {
      // previewTree
      await api.mappingApi.previewTree('ver-123', '{"Name":"r","Id":"1","child_tasks":[]}')
      const c1 = last()
      assert(c1.m === 'post', 'previewTree uses POST')
      assert(c1.a[0].endsWith('/mapping/versions/ver-123/tree'), 'previewTree URL ok')
      assert(c1.a[1].json === '{"Name":"r","Id":"1","child_tasks":[]}', 'previewTree body has json field')
      assert(c1.a[2].params.mode === 'preview', 'previewTree query mode=preview')
      assert(c1.a[2].timeout === 120000, 'previewTree has 120s timeout')

      // appendTree
      await api.mappingApi.appendTree('ver-123', '{"x":1}', 'first round')
      const c2 = last()
      assert(c2.m === 'post', 'appendTree uses POST')
      assert(c2.a[0].endsWith('/mapping/versions/ver-123/tree/append'), 'appendTree URL ok')
      assert(c2.a[1].json === '{"x":1}', 'appendTree body has json field')
      assert(c2.a[2].params.note === 'first round', 'appendTree has note query')
      assert(c2.a[2].timeout === 60000, 'appendTree has 60s timeout')

      // updateNote
      await api.mappingApi.updateNote('ver-123', 2, 'updated note')
      const c3 = last()
      assert(c3.m === 'put', 'updateNote uses PUT')
      assert(c3.a[0].endsWith('/mapping/versions/ver-123/trees/2/note'), 'updateNote URL ok')
      assert(c3.a[1].note === 'updated note', 'updateNote body has note')

      // input validation
      let vErr = null
      try { await api.mappingApi.previewTree('v', '') } catch (e) { vErr = e.message }
      assert(vErr && vErr.includes('jsonText'), 'previewTree rejects empty jsonText')

      vErr = null
      try { await api.mappingApi.appendTree('v', '{}', '') } catch (e) { vErr = e.message }
      assert(vErr && vErr.includes('note'), 'appendTree rejects empty note')

      vErr = null
      try { await api.mappingApi.updateNote('v', 1, '') } catch (e) { vErr = e.message }
      assert(vErr && vErr.includes('note'), 'updateNote rejects empty note')

      // analysis.files backward compat
      await api.analysisApi.files('task-1', { review_status: 'pending', file_type: 'testcase' })
      const c4 = last()
      assert(c4.a[1].params.review_status === 'pending', 'analysis.files preserves review_status')
      assert(c4.a[1].params.file_type === 'testcase', 'analysis.files preserves file_type')

      // analysis.files new params
      await api.analysisApi.files('task-1', { treeNodeId: 'n-1', roundFilter: 2 })
      const c5 = last()
      assert(c5.a[1].params.tree_node_id === 'n-1', 'analysis.files maps treeNodeId → tree_node_id')
      assert(c5.a[1].params.round_filter === 2, 'analysis.files maps roundFilter → round_filter')

      // getAggregate validation
      vErr = null
      try { await api.analysisApi.getAggregate('t-1', '') } catch (e) { vErr = e.message }
      assert(vErr && vErr.includes('treeNodeId'), 'getAggregate rejects empty treeNodeId')

      vErr = null
      try { await api.analysisApi.getAggregateTestcases('t-1', '') } catch (e) { vErr = e.message }
      assert(vErr && vErr.includes('treeNodeId'), 'getAggregateTestcases rejects empty treeNodeId')

      // getTaskTree null round
      await api.analysisApi.getTaskTree('t-1', null)
      const c6 = last()
      assert(c6.a[0].endsWith('/analysis/t-1/tree'), 'getTaskTree URL ok')
      assert(!c6.a[1].params || !c6.a[1].params.round, 'getTaskTree null round omits param')

      // getTaskTree round=2
      await api.analysisApi.getTaskTree('t-1', 2)
      const c7 = last()
      assert(c7.a[1].params.round === 2, 'getTaskTree round=2 sends round param')

      // getTree defaults
      await api.mappingApi.getTree('ver-1', 1)
      const c8 = last()
      assert(c8.a[1].params.include_s3_probe === false, 'getTree default include_s3_probe=false')
      assert(c8.a[1].timeout === 30000, 'getTree default 30s timeout')

      await api.mappingApi.getTree('ver-1', 1, { includeS3Probe: true })
      const c9 = last()
      assert(c9.a[1].params.include_s3_probe === true, 'getTree includeS3Probe=true sends true')
      assert(c9.a[1].timeout === 60000, 'getTree includeS3Probe=true uses 60s timeout')

      // autoFetchTree
      await api.mappingApi.autoFetchTree('ver-1', 'exec-abc')
      const c10 = last()
      assert(c10.m === 'post', 'autoFetchTree uses POST')
      assert(c10.a[0].endsWith('/mapping/versions/ver-1/tree/auto-fetch'), 'autoFetchTree URL ok')
      assert(c10.a[2].params.execution_id === 'exec-abc', 'autoFetchTree has execution_id query')

      // createTasksFromTree
      await api.mappingApi.createTasksFromTree('ver-1', 1)
      const c11 = last()
      assert(c11.m === 'post', 'createTasksFromTree uses POST')
      assert(c11.a[0].endsWith('/mapping/versions/ver-1/trees/1/create_tasks'), 'createTasksFromTree URL ok')
      assert(c11.a[2].timeout === 120000, 'createTasksFromTree has 120s timeout')

      // deleteTree
      await api.mappingApi.deleteTree('ver-1', 1)
      const c12 = last()
      assert(c12.m === 'delete', 'deleteTree uses DELETE')
      assert(c12.a[0].endsWith('/mapping/versions/ver-1/trees/1'), 'deleteTree URL ok')

      // listTrees / listPurposes / listVersions
      await api.mappingApi.listTrees('ver-1')
      assert(last().m === 'get' && last().a[0].endsWith('/mapping/versions/ver-1/trees'), 'listTrees URL ok')

      await api.mappingApi.listPurposes('ver-1')
      const lp = last()
      assert(lp.a[1].params.version_id === 'ver-1', 'listPurposes passes version_id')

      await api.mappingApi.listVersions()
      const lv = last()
      assert(lv.a[0] === '/mapping/versions', 'listVersions URL ok')

      // analysis.getTestcases with treeNodeId
      await api.analysisApi.getTestcases('t-1', { treeNodeId: 'n-1' })
      const tc1 = last()
      assert(tc1.a[1].params.tree_node_id === 'n-1', 'getTestcases passes tree_node_id')

      await api.analysisApi.getTestcases('t-1', {})
      const tc2 = last()
      assert(!tc2.a[1].params || !tc2.a[1].params.tree_node_id, 'getTestcases empty params omits tree_node_id')

      console.log()
      console.log('Total mocked axios calls:', calls().length)
      console.log('Passed:', pass, 'Failed:', fail)
      process.exitCode = fail > 0 ? 1 : 0
    } catch (e) {
      console.error('UNEXPECTED ERROR:', e)
      process.exitCode = 1
    } finally {
      for (const f of [
        entryPath,
        axiosStubPath,
        elStubPath,
        outPath,
        path.join(__dirname, '.tmp-debug.cjs'),
        path.join(__dirname, '.tmp-test-entry.cjs'),
        path.join(__dirname, '.tmp-test-out.cjs'),
        path.join(__dirname, '.tmp-test-out.js'),
        path.join(__dirname, '.tmp-bundle-inspect.txt'),
        path.join(__dirname, '.tmp-api-test.cjs'),
        path.join(__dirname, '.tmp-api-test2.cjs'),
      ]) {
        try { fs.unlinkSync(f) } catch {}
      }
    }
  })()
}).catch(e => {
  console.error('Build failed:', e)
  process.exitCode = 1
})
