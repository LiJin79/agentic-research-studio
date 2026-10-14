const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

const output = path.resolve(__dirname, process.env.UI_OUTPUT_DIR || '../evaluation/model-font-controls')
const baseURL = process.env.UI_BASE_URL || 'http://127.0.0.1:5175/'

/** 固定的布局测试数据只在浏览器拦截层存在，不写数据库、不调用云端模型。 */
async function installFixtures(page, state) {
  const session = { id: 'layout-test', title: '布局测试：报销制度与资料核对' }
  const source = { citation_id: 'K1', source_type: 'knowledge', title: '布局测试_企业报销制度.md',
    snippet: '本段是界面测试资料，不是实际业务制度。员工提交申请后，由财务完成材料审核和付款。', score: .91 }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url())
    let data = {}
    if (url.pathname.endsWith('/runtime')) data = { llm_configured: true, llm_provider: 'dashscope',
      llm_model: 'qwen-plus', embedding_configured: true, embedding_model: 'text-embedding-v4',
      embedding_dimensions: 1024, collection: 'ui_test_collection', web_configured: true,
      tools: [
        { name: 'read_webpage', label: '网页正文读取', category: 'web', configured: true },
        { name: 'get_weather', label: '天气预报', category: 'travel', configured: false, key_env: 'QWEATHER_API_KEY + QWEATHER_API_HOST' },
      ],
      models: [
        { id: 'default', label: '当前默认', provider: 'dashscope', model: 'qwen-plus', configured: true },
        { id: 'deepseek', label: 'DeepSeek', provider: 'deepseek', model: 'deepseek-flash', configured: true },
        { id: 'minimax', label: 'MiniMax', provider: 'minimax', model: 'MiniMax-M3', configured: false, key_env: 'MINIMAX_API_KEY' },
      ] }
    else if (url.pathname.endsWith('/health/ready')) data = { status: 'ok' }
    else if (url.pathname.endsWith('/sessions')) data = { items: [session] }
    else if (url.pathname.endsWith('/messages')) data = { items: state.empty ? [] : [
      { id: 'test-user', role: 'user', content: '请整理报销流程，并列出对应的资料依据。' },
      { id: 'test-answer', role: 'assistant', content: '## 报销流程\n\n按资料整理，流程包含 **申请、审核和付款** 三个环节 [K1]。\n\n| 环节 | 负责人 |\n| --- | --- |\n| 提交申请 | 员工 |\n| 材料审核 | 财务 |\n\n### 注意事项\n\n- 核对原始凭据和申请信息。\n- 具体制度以原文为准。\n\n```python\nawait session.commit()\n```',
        message_metadata: { verified: true, verification_status: 'evidence_checked', sources: [source],
          trace: [{ node: 'knowledge_researcher', detail: '检索知识库并核对资料来源' }],
          tool_events: [{ name: 'search_knowledge', detail: '找到 1 条测试资料', query: '报销流程', success: true }] } }
    ] }
    else if (url.pathname.endsWith('/chat/stream')) {
      state.lastModel = route.request().postDataJSON().model_id
      await route.fulfill({ contentType: 'text/event-stream', body:
        'event: token\ndata: {"content":"模型菜单测试回答。"}\n\n' +
        'event: done\ndata: ' + JSON.stringify({ answer: '模型菜单测试回答。', sources: [], trace: [],
          metadata: { message_id: 'test-switch', verified: true, verification_status: 'general_review',
            model_id: state.lastModel, model: 'deepseek-flash' } }) + '\n\n' })
      return
    }
    else if (url.pathname.endsWith('/documents')) data = { items: [
      { id: 'test-ready', filename: '布局测试_企业报销制度.md', status: 'ready', created_at: '2026-10-12T08:00:00Z', document_metadata: { chunk_count: 12, stage: 'completed' } },
      { id: 'test-processing', filename: '布局测试_用于验证长文件名称在移动端能够完整换行的年度市场分析报告.pdf', status: 'processing', created_at: '2026-10-12T08:00:00Z', document_metadata: { progress: .35, stage: 'embedding' } },
      { id: 'test-failed', filename: '布局测试_需要重建索引.docx', status: 'failed', created_at: '2026-10-12T08:00:00Z', error_message: '测试错误：向量服务暂不可用', document_metadata: {} }
    ] }
    await route.fulfill({ json: data })
  })
}

/** 同时检查视口溢出和可见按钮之间的碰撞，避免只看截图漏掉布局问题。 */
async function assertLayout(page, name) {
  const problems = await page.evaluate(() => {
    const problems = []
    if (document.documentElement.scrollWidth > innerWidth) problems.push('page overflow')
    for (const selector of ['.composer-toolbar', '.header-actions', '.doc-actions']) {
      for (const parent of document.querySelectorAll(selector)) {
        const buttons = [...parent.querySelectorAll('button')].filter(el => el.getClientRects().length)
        for (let i = 1; i < buttons.length; i++) {
          const previous = buttons[i - 1].getBoundingClientRect(), current = buttons[i].getBoundingClientRect()
          if (Math.min(previous.right, current.right) > Math.max(previous.left, current.left) + 1 &&
              Math.min(previous.bottom, current.bottom) > Math.max(previous.top, current.top) + 1) problems.push(selector + ' button collision')
        }
      }
    }
    return problems
  })
  assert.deepEqual(problems, [], name)
}

/** 复用实际控件验证大字、来源、办公导出弹窗、键盘焦点与手机导航。 */
async function inspectViewport(browser, name, width, height) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 })
  const state = { empty: false }, errors = []
  page.on('pageerror', error => errors.push(error.message))
  await installFixtures(page, state)
  try {
    await page.goto(baseURL, { waitUntil: 'networkidle' })
    await page.locator('.markdown').waitFor()
    await page.evaluate(() => document.fonts.ready)
    assert.ok(await page.locator('.markdown').evaluate(el => getComputedStyle(el).fontFamily.includes('Noto Sans SC Variable')), 'self-hosted Chinese font')
    const font = await page.locator('.markdown').evaluate(el => parseFloat(getComputedStyle(el).fontSize))
    assert.ok(font >= 17, 'body should remain readable')
    const navFont = await page.locator('.workspace-nav button').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))
    assert.ok(navFont >= 18, 'navigation should be readable without enlarging chat')
    assert.ok(await page.locator('.session-select').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize)) >= 16, 'conversation list type floor')
    assert.ok(await page.locator('.sidebar-label').evaluate(el => parseFloat(getComputedStyle(el).fontSize)) >= 14, 'sidebar metadata floor')
    assert.ok(await page.locator('.brand strong').evaluate(el => getComputedStyle(el).fontFamily.includes('LXGW WenKai')), 'distinct heading family')
    await page.getByRole('button', { name: '放大字体', exact: true }).click()
    const largeFont = await page.locator('.markdown').evaluate(el => parseFloat(getComputedStyle(el).fontSize))
    assert.ok(largeFont > font, 'large reading mode')
    assert.ok(await page.locator('.workspace-nav button').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize)) > navFont, 'font controls also enlarge navigation')
    await page.getByRole('button', { name: '缩小字体', exact: true }).click()
    assert.equal(await page.locator('.markdown').evaluate(el => parseFloat(getComputedStyle(el).fontSize)), font)
    await assertLayout(page, name + ' chat')
    await page.screenshot({ path: path.join(output, name + '-chat.png'), animations: 'disabled' })

    await page.getByRole('button', { name: '生成 Word 文档', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.waitFor()
    assert.equal(await dialog.locator('input').evaluate(el => el === document.activeElement), true)
    await dialog.getByRole('button', { name: '关闭弹窗' }).focus()
    await page.keyboard.press('Shift+Tab')
    assert.equal(await dialog.getByRole('button', { name: '生成并下载' }).evaluate(el => el === document.activeElement), true)
    await page.keyboard.press('Tab')
    assert.equal(await dialog.getByRole('button', { name: '关闭弹窗' }).evaluate(el => el === document.activeElement), true)
    await page.screenshot({ path: path.join(output, name + '-word-dialog.png'), animations: 'disabled' })
    await page.keyboard.press('Escape')
    assert.equal(await dialog.count(), 0)
    assert.equal(await page.getByRole('button', { name: '生成 Word 文档', exact: true }).evaluate(el => el === document.activeElement), true)
    await page.getByRole('button', { name: '生成 PPT 演示', exact: true }).click()
    await page.getByRole('dialog', { name: '生成 PPT 演示' }).waitFor()
    await page.keyboard.press('Escape')

    if (width <= 1200) await page.getByRole('button', { name: '来源与执行记录' }).click()
    await page.locator('.inspector-tabs button').filter({ hasText: '执行记录' }).click()
    await page.locator('.activity-list').waitFor()
    await page.screenshot({ path: path.join(output, name + '-activity.png'), animations: 'disabled' })
    if (width < 350) await page.locator('.inspector').getByRole('button', { name: '关闭详情' }).click()
    else if (width <= 1200) await page.getByRole('button', { name: '关闭研究详情遮罩' }).click({ position: { x: 5, y: 5 } })

    if (width <= 720) await page.getByRole('button', { name: '会话菜单', exact: true }).click()
    await page.locator('.workspace-nav button').filter({ hasText: '知识库' }).click()
    await page.locator('.document-line').first().waitFor()
    await assertLayout(page, name + ' knowledge')
    assert.equal(await page.getByRole('button', { name: '下载原文' }).count(), 3)
    assert.equal(await page.locator('.doc-state.ready').count(), 1)
    assert.equal(await page.locator('.doc-state.failed').count(), 1)
    await page.screenshot({ path: path.join(output, name + '-knowledge.png'), animations: 'disabled' })

    if (width <= 720) await page.getByRole('button', { name: '会话菜单', exact: true }).click()
    await page.locator('.workspace-nav button').filter({ hasText: '工具' }).click()
    await page.locator('.tools-content').waitFor()
    assert.equal(await page.locator('.tool-state.ready').count(), 1)
    await assertLayout(page, name + ' tools')
    await page.screenshot({ path: path.join(output, name + '-tools.png'), animations: 'disabled' })
    state.empty = true
    await page.reload({ waitUntil: 'networkidle' })
    await page.locator('.welcome').waitFor()
    await assertLayout(page, name + ' welcome')
    await page.screenshot({ path: path.join(output, name + '-welcome.png'), animations: 'disabled' })
    await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('请进行网页搜索 FastAPI')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.getByRole('dialog', { name: '允许本次联网搜索' }).waitFor()
    await page.keyboard.press('Escape')
    // 选择模型的 ID 必须真正进入请求，而不只是改变右上角标签。
    const picker = page.getByRole('combobox', { name: '生成模型' })
    assert.equal(await picker.locator('option[value="minimax"]').evaluate(el => el.disabled), true)
    await picker.selectOption('deepseek')
    await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('你好')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.locator('.message-model').filter({ hasText: 'deepseek-flash' }).waitFor()
    assert.equal(state.lastModel, 'deepseek')
    await page.reload({ waitUntil: 'networkidle' })
    assert.equal(await picker.inputValue(), 'deepseek')
    for (let i = 0; i < 6; i++) {
      const increase = page.getByRole('button', { name: '放大字体', exact: true })
      if (await increase.isEnabled()) await increase.click()
    }
    assert.equal(await page.getByRole('button', { name: '放大字体', exact: true }).isDisabled(), true)
    await assertLayout(page, name + ' maximum type')
    if (width <= 720) await page.getByRole('button', { name: '会话菜单', exact: true }).click()
    await page.screenshot({ path: path.join(output, name + '-large-sidebar.png'), animations: 'disabled' })
    if (width <= 720) await page.locator('.drawer-shade').click({ position: { x: width - 5, y: 5 } })
    for (let i = 0; i < 6; i++) await page.getByRole('button', { name: '缩小字体', exact: true }).click()
    assert.equal(await page.getByRole('button', { name: '缩小字体', exact: true }).isDisabled(), true)
    await page.getByRole('button', { name: '重置字体', exact: true }).click()
    await picker.selectOption('default')
    assert.deepEqual(errors, [], name + ' browser errors')
    return { name, viewport: [width, height], font, largeFont, errors, layout: 'passed', keyboard: 'passed', officeDialogs: 'passed', modelPayload: 'passed', fontBounds: 'passed' }
  } finally { await page.close() }
}

/** 输出独立验收报告，不覆盖上一轮真实模型调用的功能验收结果。 */
async function main() {
  fs.mkdirSync(output, { recursive: true })
  const browser = await chromium.launch({ channel: process.env.UI_BROWSER_CHANNEL || 'msedge', headless: true })
  try {
    const results = []
    for (const viewport of [['desktop', 1440, 1000], ['mobile', 390, 844], ['small-mobile', 320, 800], ['tablet', 1024, 900], ['wide', 1920, 1080]]) {
      results.push(await inspectViewport(browser, ...viewport))
    }
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ fixture: true, results }, null, 2))
    console.log(JSON.stringify(results, null, 2))
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
