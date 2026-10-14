const fs = require('node:fs')
const path = require('node:path')
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright')

/** 仅在显式 smoke 模式创建真实会话，完成后删除自己的测试数据。 */
async function exerciseChat(page) {
  if (page.viewportSize().width < 720) await page.getByRole('button', { name: '会话菜单', exact: true }).click()
  const created = page.waitForResponse(response =>
    response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/sessions')
  await page.getByRole('button', { name: '新会话' }).click()
  const response = await created
  if (response.status() !== 201) throw new Error('new session failed')
  const session = await response.json()
  try {
    if (page.viewportSize().width < 720) await page.waitForTimeout(250)
    await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('你好')
    await page.getByRole('button', { name: '发送', exact: true }).click()
    await page.locator('.message.assistant .markdown').waitFor({ state: 'visible' })
    await page.getByRole('button', { name: '发送', exact: true }).waitFor({ state: 'visible' })
    if (await page.locator('.error-banner').count()) throw new Error('chat showed an error')
    return session.id
  } catch (error) {
    await page.request.delete(new URL('/api/v1/sessions/' + session.id, page.url()).href)
    throw error
  }
}

/** 浏览器布局验证；fixture 模式只用于 UI 测试，不写进运行结果。 */
async function main() {
  const browser = await chromium.launch({ headless: true, ...(process.env.UI_BROWSER_CHANNEL ? { channel: process.env.UI_BROWSER_CHANNEL } : {}) })
  const out = path.resolve(__dirname, '../evaluation/screenshots')
  fs.mkdirSync(out, { recursive: true })
  const results = []
  try {
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 })
      const errors = []
      page.on('pageerror', error => errors.push(error.message))
      if (process.env.UI_FIXTURES === '1') {
        const source = { citation_id: 'K1', source_type: 'knowledge', title: '企业报销制度.md',
          snippet: '员工应在出差结束后30日内提交报销申请，财务审核后完成付款。', score: .91,
          document_id: '00000000-0000-0000-0000-000000000002', url: null }
        const session = { id: '00000000-0000-0000-0000-000000000001', title: '报销制度与执行流程', updated_at: new Date().toISOString() }
        await page.route('**/api/v1/**', async route => {
          const pathname = new URL(route.request().url()).pathname
          let data
          if (pathname.endsWith('/runtime')) data = { llm_provider: 'mock', llm_model: 'demo', demo: true, llm_configured: true,
            embedding_provider: 'hash', embedding_model: 'hash-test', embedding_dimensions: 384, embedding_configured: true, web_configured: true, max_upload_mb: 10, collection: 'qa_fixture' }
          else if (pathname.includes('/health/ready')) data = { status: 'ok' }
          else if (pathname.includes('/messages')) data = { items: [
            { id: 'm1', role: 'user', content: '根据知识库，报销需要在多少天内提交？' },
            { id: 'm2', role: 'assistant', content: '员工需要在出差结束后 **30 日内**提交报销申请 [K1]。\n\n| 步骤 | 负责人 |\n|---|---|\n| 提交申请 | 员工 |\n| 审核 | 财务 |',
              message_metadata: { verified: true, sources: [source], trace: [{ node: 'knowledge_researcher', detail: '调用 search_knowledge 获得原文依据' }] } }
          ], total: 2 }
          else if (pathname.endsWith('/sessions')) data = { items: [session], total: 1 }
          else if (pathname.endsWith('/documents')) data = { items: [
            { id: source.document_id, filename: '企业报销制度.md', status: 'ready', document_metadata: { chunk_count: 12, embedding_fingerprint: 'test' }, created_at: new Date().toISOString() },
            { id: 'd2', filename: '年度市场分析_非常长的文件名称用于验证手机页面布局.pdf', status: 'processing', document_metadata: { progress: .35, stage: 'embedding' }, created_at: new Date().toISOString() },
            { id: 'd3', filename: '索引失败_可以重新处理.docx', status: 'failed', error_message: '测试用 API 配额不足', document_metadata: {}, created_at: new Date().toISOString() },
          ], total: 3 }
          else if (pathname.endsWith('/chat/stream')) {
            const payload = route.request().postDataJSON()
            if (/不需要|解释网页搜索/.test(payload.message) && payload.use_web_search) throw new Error('negated or conceptual request enabled network')
            await route.fulfill({ contentType: 'text/event-stream', body:
              'event: token\ndata: {"content":"这是正常的概念回答。"}\n\n' +
              'event: done\ndata: ' + JSON.stringify({ answer: '这是正常的概念回答。', sources: [], trace: [],
                metadata: { verified: true, verification_status: 'general_review', message_id: 'm3' } }) + '\n\n' })
            return
          }
          else data = {}
          await route.fulfill({ json: data })
        })
      }
      await page.goto(process.env.UI_BASE_URL || 'http://127.0.0.1:5174/', { waitUntil: 'networkidle' })
      if (process.env.UI_FIXTURES === '1') {
        // 明确联网请求必须先出现许可确认，不能静默给出知识库答案。
        await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('请进行网页搜索 site:fastapi.tiangolo.com FastAPI')
        await page.getByRole('button', { name: '发送', exact: true }).click()
        await page.getByRole('dialog', { name: '允许本次联网搜索' }).waitFor()
        await page.getByRole('button', { name: '取消', exact: true }).click()
        const bodyFont = await page.locator('.markdown').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))
        if (bodyFont < 17) throw new Error('body font too small: ' + bodyFont)
        await page.getByRole('button', { name: '放大字体', exact: true }).click()
        const larger = await page.locator('.markdown').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize))
        if (larger <= bodyFont) throw new Error('reading toggle does not increase font size')
        await page.getByRole('button', { name: '缩小字体', exact: true }).click()
        await page.getByRole('button', { name: '生成 Word 文档', exact: true }).click()
        await page.getByRole('dialog', { name: '生成 Word 文档' }).waitFor()
        await page.screenshot({ path: path.join(out, name + '-word-dialog.png'), fullPage: true })
        await page.getByRole('button', { name: '取消', exact: true }).click()
        await page.getByRole('button', { name: '生成 PPT 演示', exact: true }).click()
        await page.getByRole('dialog', { name: '生成 PPT 演示' }).waitFor()
        await page.getByRole('button', { name: '取消', exact: true }).click()
        await page.locator('.web-switch').click()
        if (!await page.getByRole('checkbox', { name: '联网搜索', exact: true }).isChecked()) throw new Error('web search toggle did not enable')
        await page.reload({ waitUntil: 'networkidle' })
        if (!await page.getByRole('checkbox', { name: '联网搜索', exact: true }).isChecked()) throw new Error('web search permission preference did not persist')
        await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('你好，不需要查询资料或联网搜索。')
        await page.getByRole('button', { name: '发送', exact: true }).click()
        await page.getByRole('button', { name: '发送', exact: true }).waitFor({ state: 'visible' })
        if (await page.getByRole('dialog').count()) throw new Error('negative question triggered permission modal')
        if (await page.locator('.error-banner').count()) throw new Error('negative question failed')
        await page.reload({ waitUntil: 'networkidle' })
        await page.locator('.web-switch').click()
        await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('请解释网页搜索是什么。')
        await page.getByRole('button', { name: '发送', exact: true }).click()
        await page.getByRole('button', { name: '发送', exact: true }).waitFor({ state: 'visible' })
        if (await page.getByRole('dialog').count()) throw new Error('conceptual question triggered permission modal')
        await page.route('**/api/v1/chat/stream', route => route.abort('connectionrefused'))
        await page.getByRole('textbox', { name: '输入问题', exact: true }).fill('你好')
        await page.getByRole('button', { name: '发送', exact: true }).click()
        await page.locator('.error-banner').filter({ hasText: '无法连接到项目服务' }).waitFor()
        await page.reload({ waitUntil: 'networkidle' })
      }
      const ownSession = process.env.UI_SMOKE === '1' ? await exerciseChat(page) : null
      try {
        await page.screenshot({ path: path.join(out, name + '-chat.png'), fullPage: true })
        const chatOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
        if (chatOverflow) throw new Error(name + ' chat overflows')
      } finally {
        if (ownSession) {
          const deleted = await page.request.delete(new URL('/api/v1/sessions/' + ownSession, page.url()).href)
          if (deleted.status() !== 204) throw new Error('test session cleanup failed')
        }
      }
      if (width < 720) await page.getByRole('button', { name: '会话菜单', exact: true }).click()
      await page.locator('.workspace-nav button').filter({ hasText: '知识库' }).click()
      await page.waitForTimeout(250)
      await page.screenshot({ path: path.join(out, name + '-knowledge.png'), fullPage: true })
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
      if (errors.length || overflow) throw new Error(JSON.stringify({ name, errors, overflow }))
      results.push({ name, viewport: [width, height], errors, overflow })
      await page.close()
    }
    fs.writeFileSync(path.resolve(__dirname, '../evaluation/ui-report.json'), JSON.stringify({
      fixture: process.env.UI_FIXTURES === '1', results,
    }, null, 2))
    console.log(JSON.stringify(results))
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
