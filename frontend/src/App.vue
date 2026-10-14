<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ArrowUp, BookOpen, Check, CheckCircle2, ChevronRight, CircleHelp, Copy, Download,
  Database, FileText, FolderOpen, Globe2, Library, LoaderCircle, Menu, MessageSquare, MessageSquarePlus,
  PanelRightClose, PanelRightOpen, Pencil, RefreshCw, Search, Settings2,
  ShieldCheck, Square, Trash2, Upload, Workflow, X, Plus, Minus, Presentation, FileDown, Type,
  Code2, Compass, BarChart3, FlaskConical, Wrench } from '@lucide/vue'
import MarkdownMessage from './components/MarkdownMessage.vue'
import { createSession, deleteSession, downloadDocument, getHealth, getRuntime, listDocuments,
  listMessages, listSessions, reindexDocument, renameSession, setAccessToken, streamChat,
  uploadDocument, deleteDocument, exportArtifact } from './api'
import { normalizeReadingSize, requiresWebSearch, verificationLabel, webSearchDenied } from './workspace'

const sessions = ref([]), documents = ref([]), messages = ref([])
const activeId = ref(null), input = ref(''), sessionSearch = ref('')
const view = ref('chat'), inspectorTab = ref('sources'), showInspector = ref(window.matchMedia('(min-width: 1201px)').matches), showMenu = ref(false)
const runtime = ref(null), health = ref(null), error = ref(''), toast = ref('')
const loading = ref(true), sending = ref(false), uploading = ref(false)
const useWeb = ref(localStorage.getItem('web-search-enabled') === 'true')
const fontSize = ref(normalizeReadingSize(localStorage.getItem('reading-size')))
const selectedModelId = ref(localStorage.getItem('generation-model') || 'default')
const exporting = ref(null)
// 只保存开关和阅读偏好，不保存任何供应商密钥。
watch(useWeb, value => localStorage.setItem('web-search-enabled', String(value)))
watch(fontSize, value => localStorage.setItem('reading-size', value))
watch(selectedModelId, value => localStorage.setItem('generation-model', value))
const loadingConversation = ref(false), creatingSession = ref(false)
const status = ref('就绪'), sources = ref([]), trace = ref([]), toolEvents = ref([])
const scrollEl = ref(null), fileInput = ref(null), copiedId = ref(null), selectedCitation = ref(null)
const modal = ref(null), modalInput = ref(''), modalBusy = ref(false)
const dialogEl = ref(null)
const activeSession = computed(() => sessions.value.find(s => s.id === activeId.value))
const filteredSessions = computed(() => sessions.value.filter(s =>
  s.title.toLowerCase().includes(sessionSearch.value.toLowerCase())))
const readyDocs = computed(() => documents.value.filter(d => d.status === 'ready' && !d.document_metadata.needs_reindex))
const busyDocs = computed(() => documents.value.filter(d => ['pending', 'processing'].includes(d.status)))
const lastAssistant = computed(() => [...messages.value].reverse().find(m => m.role === 'assistant'))
const modelOptions = computed(() => runtime.value?.models || [{ id: 'default',
  label: '当前默认', model: runtime.value?.llm_model || '连接中', provider: runtime.value?.llm_provider,
  configured: runtime.value?.llm_configured }])
const selectedModel = computed(() => modelOptions.value.find(item => item.id === selectedModelId.value))
const modelReady = computed(() => selectedModel.value?.configured)
const suggestions = [
  { icon: Code2, tone: 'blue', text: '科技与代码研究', detail: '官方资料 · 仓库解读', query: '请联网搜索 FastAPI 官方资料，读取最相关页面正文，说明它的适用场景、局限和来源。', web: true },
  { icon: BookOpen, tone: 'green', text: '知识库与资料整理', detail: '原文依据 · 结论整理', query: '请根据知识库文档总结核心内容，并列出资料来源。' },
  { icon: Compass, tone: 'amber', text: '天气与出行规划', detail: '地点路线 · 行程安排', query: '请联网研究杭州两天的旅游路线。优先使用已配置的地点和天气工具；缺少实时数据时明确说明，不要编造预报或票价。', web: true },
  { icon: BarChart3, tone: 'coral', text: '数据分析与报告', detail: 'CSV 统计 · Word / PPT', query: '请查看已上传的 CSV 文档，使用统计工具计算行数和适合的数值汇总，说明计算口径，整理成报告。' },
]
const toolGroups = [
  { category: 'web', title: '网页与正文', icon: Globe2, tone: 'blue' },
  { category: 'knowledge', title: '知识库与文档', icon: BookOpen, tone: 'green' },
  { category: 'code', title: '代码与技术文档', icon: Code2, tone: 'blue' },
  { category: 'science', title: '论文与科研', icon: FlaskConical, tone: 'green' },
  { category: 'travel', title: '天气与出行', icon: Compass, tone: 'amber' },
  { category: 'data', title: '数据与计算', icon: BarChart3, tone: 'coral' },
]
const enabledTools = computed(() => (runtime.value?.tools || []).filter(tool => tool.configured))
let controller = null, poller = null, toastTimer = null
let dialogTrigger = null

/** 打开弹窗后聚焦输入框，关闭后将焦点还给原按钮，方便键盘操作。 */
watch(modal, async (value, previous) => {
  if (value && !previous) dialogTrigger = document.activeElement
  await nextTick()
  if (value) {
    const target = dialogEl.value?.querySelector('input:not(:disabled)') || dialogEl.value?.querySelector('button:not(:disabled)')
    target?.focus()
  }
  else if (dialogTrigger?.isConnected) dialogTrigger.focus()
}, { flush: 'post' })

/** Tab 焦点留在当前弹窗；忙碌时不能用 Escape 中断提交。 */
function handleDialogKeydown(event) {
  if (event.key === 'Escape' && !modalBusy.value) {
    event.preventDefault()
    modal.value = null
  }
  if (event.key !== 'Tab') return
  const controls = [...dialogEl.value.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href], [tabindex="0"]')]
  const first = controls[0], last = controls.at(-1)
  if (!first) return
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

/** 同时调节正文与界面字号；CSS 按用途保留层级，不改变浏览器缩放。 */
function adjustFontSize(delta) { fontSize.value = normalizeReadingSize(fontSize.value + delta) }

/** 提示短暂结果，错误保留在页面供重试和排查。 */
function notify(message) { toast.value = message; clearTimeout(toastTimer); toastTimer = setTimeout(() => toast.value = '', 3000) }
/** 统一处理鉴权错误，其余错误显示在当前工作区。 */
function handleError(exc) {
  error.value = exc.message
  if (exc.status === 401) { modal.value = { kind: 'token', title: '工作台访问口令' }; modalInput.value = '' }
}
/** 只有接近底部才跟随新内容，阅读旧消息时不会被强制拉走。 */
async function scrollBottom(force = false) {
  const el = scrollEl.value
  const follow = force || !el || el.scrollHeight - el.scrollTop - el.clientHeight < 180
  await nextTick()
  if (follow && scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}
/** 从持久消息恢复该次回答的引用和轨迹，刷新页面不丢失来源。 */
function inspectMessage(message) {
  const counters = { knowledge: 0, web: 0 }
  sources.value = (message.message_metadata?.sources || []).map(source => {
    const kind = source.source_type === 'web' ? 'web' : 'knowledge'
    counters[kind] += 1
    return { ...source, citation_id: source.citation_id || (kind === 'web' ? 'W' : 'K') + counters[kind] }
  })
  trace.value = message.message_metadata?.trace || []
  toolEvents.value = message.message_metadata?.tool_events || []
  selectedCitation.value = null
}
/** 切换会话时读取数据库历史，进行中的会话保持固定。 */
async function selectSession(id) {
  if (sending.value || loadingConversation.value) return
  loadingConversation.value = true
  activeId.value = id; view.value = 'chat'; showMenu.value = false; error.value = ''
  try {
    messages.value = (await listMessages(id)).items
    const latest = [...messages.value].reverse().find(m => m.role === 'assistant')
    if (latest) inspectMessage(latest)
    else { sources.value = []; trace.value = [] }
    if (!latest) toolEvents.value = []
    status.value = '就绪'
    localStorage.setItem('active-session', id)
    await scrollBottom(true)
  } catch (exc) { handleError(exc) } finally { loadingConversation.value = false }
}
/** 新建会话立即保存，标题在首次提问后自动更新。 */
async function newSession() {
  if (sending.value || loadingConversation.value || creatingSession.value) return
  creatingSession.value = true
  try {
    const item = await createSession()
    sessions.value.unshift(item)
    await selectSession(item.id)
  } catch (exc) { handleError(exc) } finally { creatingSession.value = false }
}
/** 初始化运行配置和真实数据，不插入伪造文档或聊天记录。 */
async function initialize() {
  loading.value = true; error.value = ''
  try {
    const [s, d, r, h] = await Promise.all([listSessions(), listDocuments(), getRuntime(), getHealth()])
    sessions.value = s.items; documents.value = d.items; runtime.value = r; health.value = h
    if (!modelOptions.value.some(item => item.id === selectedModelId.value && item.configured)) selectedModelId.value = 'default'
    if (!r.web_configured) useWeb.value = false
    if (s.items.length) {
      const saved = localStorage.getItem('active-session')
      await selectSession(s.items.some(i => i.id === saved) ? saved : s.items[0].id)
    }
  } catch (exc) { handleError(exc) } finally { loading.value = false }
}
/** 发送真实事件流，修订事件会替换草稿，done 才确认最终回答。 */
async function sendQuestion(question = input.value) {
  question = question.trim()
  if (!question || sending.value || loadingConversation.value || creatingSession.value || !modelReady.value) return
  if (requiresWebSearch(question) && !useWeb.value) {
    if (!runtime.value?.web_configured) { error.value = '本次需要网页搜索，但搜索服务尚未配置。请先填写博查或 Tavily 密钥。'; return }
    modal.value = { kind: 'web-permission', title: '允许本次联网搜索', question }
    return
  }
  if (!activeId.value) await newSession()
  if (!activeId.value) return
  sending.value = true; input.value = ''; error.value = ''; status.value = '开始分析'
  sources.value = []; trace.value = []; toolEvents.value = []
  const assistant = reactive({ id: crypto.randomUUID(), role: 'assistant', content: '', status: 'pending', message_metadata: {} })
  messages.value.push({ id: crypto.randomUUID(), role: 'user', content: question })
  messages.value.push(assistant)
  controller = new AbortController()
  await scrollBottom(true)
  try {
    if (activeSession.value?.title === '新会话') {
      const renamed = await renameSession(activeId.value, question.slice(0, 36))
      Object.assign(activeSession.value, renamed)
    }
    await streamChat({ session_id: activeId.value, message: question, model_id: selectedModelId.value, use_web_search: useWeb.value && !webSearchDenied(question),
      request_id: crypto.randomUUID() }, (event, data) => {
      if (event === 'status') status.value = data.message
      if (event === 'token') assistant.content += data.content
      if (event === 'answer_reset') { assistant.content = ''; status.value = '修订回答' }
      if (event === 'tool_start') toolEvents.value.push({ ...data, running: true })
      if (event === 'tool_end') {
        const row = [...toolEvents.value].reverse().find(i => i.running && i.name === data.name && i.agent === data.agent)
        if (row) Object.assign(row, data, { running: false })
      }
      if (event === 'done') {
        assistant.content = data.answer
        assistant.status = 'completed'
        if (data.metadata.message_id) assistant.id = data.metadata.message_id
        assistant.message_metadata = { ...data.metadata, sources: data.sources, trace: data.trace }
        inspectMessage(assistant)
        status.value = verificationLabel(data.metadata) || '回答完成'
      }
      scrollBottom()
    }, controller.signal)
    sessions.value = (await listSessions()).items
  } catch (exc) {
    assistant.status = exc.name === 'AbortError' ? 'cancelled' : 'failed'
    status.value = exc.name === 'AbortError' ? '已取消' : '执行失败'
    if (exc.name !== 'AbortError') handleError(exc)
  } finally {
    sending.value = false; controller = null
    toolEvents.value.forEach(i => i.running = false)
  }
}
/** 取消网络读取，后端同步终止图并记录取消状态。 */
function cancelRun() { controller?.abort() }
/** 中文输入法提交候选词时不发送，Shift+Enter 保留换行。 */
function handleComposerEnter(event) {
  if (event.isComposing || event.keyCode === 229 || event.shiftKey) return
  event.preventDefault()
  sendQuestion()
}
/** 选择建议问题可直接开始，联网建议仍受配置和用户开关约束。 */
function chooseSuggestion(item) { if (item.web && runtime.value?.web_configured) useWeb.value = true; input.value = item.query }
/** 把最后一个问题再次提交为新的有记录请求。 */
function retry() { const question = [...messages.value].reverse().find(m => m.role === 'user'); if (question) sendQuestion(question.content) }
/** 复制回答原文，Markdown 格式保留。 */
async function copyMessage(message) {
  try { await navigator.clipboard.writeText(message.content); copiedId.value = message.id; setTimeout(() => copiedId.value = null, 2000) } catch { notify('复制失败') }
}
/** 引用点击打开来源详情并聚焦对应条目。 */
async function openCitation(id, message) {
  inspectMessage(message); inspectorTab.value = 'sources'; showInspector.value = true; selectedCitation.value = id
  await nextTick()
  document.getElementById('source-' + id)?.scrollIntoView({ block: 'nearest' })
}
/** 多文件逐个排队，入库进度由后台 worker 通过列表接口回传。 */
async function uploadFiles(files) {
  uploading.value = true; error.value = ''
  let queued = 0, reused = 0
  try {
    for (const file of files) {
      if (file.size > (runtime.value?.max_upload_mb || 10) * 1024 * 1024) throw new Error(file.name + ' 超过大小限制')
      const result = await uploadDocument(file)
      if (result.deduplicated && result.document.status === 'ready') reused += 1
      else queued += 1
    }
    documents.value = (await listDocuments()).items
    notify([queued ? queued + ' 份文件进入入库队列' : '', reused ? reused + ' 份文件复用已有索引' : ''].filter(Boolean).join('，'))
  } catch (exc) { handleError(exc) } finally { uploading.value = false; if (fileInput.value) fileInput.value.value = '' }
}
/** 轮询只获取文档状态，不在前端自行伪造进度。 */
async function refreshDocuments() {
  try { documents.value = (await listDocuments()).items } catch (exc) { if (!modal.value) handleError(exc) }
}
/** 给危险操作和重命名提供明确确认，避免误点直接删数据。 */
function openModal(kind, item) {
  modal.value = { kind, item, title: kind === 'rename' ? '重命名会话' : kind === 'deleteSession' ? '删除会话' : kind === 'deleteDocument' ? '删除文档' : '运行配置' }
  modalInput.value = kind === 'rename' ? item.title : ''
}
/** 选择输出格式后确认标题；Word 保留原文，PPT 调用模型提炼大纲。 */
function openExport(message, format) {
  modal.value = { kind: 'export', item: message, format, title: format === 'docx' ? '生成 Word 文档' : '生成 PPT 演示' }
  modalInput.value = activeSession.value?.title?.slice(0, 100) || '研究报告'
}
/** 执行确认操作，成功后刷新对应持久数据。 */
async function confirmModal() {
  if (!modal.value || modalBusy.value) return
  modalBusy.value = true
  try {
    const { kind, item } = modal.value
    if (kind === 'web-permission') {
      const question = modal.value.question
      useWeb.value = true; modal.value = null
      await sendQuestion(question)
      return
    }
    if (kind === 'export') {
      if (!modalInput.value.trim()) return
      exporting.value = item.id
      const format = modal.value.format
      try {
        await exportArtifact(item.id, format, modalInput.value.trim())
        modal.value = null; notify(format === 'docx' ? 'Word 文档已生成并下载' : 'PPT 演示已生成并下载')
      } finally { exporting.value = null }
      return
    }
    if (kind === 'rename') { if (!modalInput.value.trim()) return; Object.assign(item, await renameSession(item.id, modalInput.value.trim())) }
    if (kind === 'deleteSession') {
      await deleteSession(item.id)
      sessions.value = sessions.value.filter(s => s.id !== item.id)
      if (activeId.value === item.id) {
        activeId.value = null; messages.value = []; sources.value = []; trace.value = []
        if (sessions.value.length) await selectSession(sessions.value[0].id)
      }
    }
    if (kind === 'deleteDocument') { await deleteDocument(item.id); await refreshDocuments() }
    if (kind === 'token') { setAccessToken(modalInput.value.trim()); modal.value = null; await initialize(); return }
    modal.value = null
  } catch (exc) { handleError(exc) } finally { modalBusy.value = false }
}
/** 重建文档索引，适用于失败重试和 Embedding 模型切换。 */
async function rebuild(document) {
  try { await reindexDocument(document.id); await refreshDocuments(); notify('已提交重建任务') } catch (exc) { handleError(exc) }
}
/** 保留口令鉴权的原文下载。 */
async function download(item) { try { await downloadDocument(item.id || item.document_id, item.filename || item.title) } catch (exc) { handleError(exc) } }
/** 状态文本由后端数据决定。 */
function docLabel(item) { return item.document_metadata.needs_reindex ? '需要重建' : ({ pending: '排队中', processing: '正在入库', ready: '已就绪', failed: '入库失败' }[item.status]) }
/** 格式化列表时间，不改变服务器保存的时间。 */
function dateLabel(value) { return new Date(value).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) }
onMounted(async () => { await initialize(); poller = setInterval(refreshDocuments, 4000) })
onUnmounted(() => { clearInterval(poller); clearTimeout(toastTimer); controller?.abort() })
</script>

<template>
  <div class="workspace" :class="{ 'inspector-hidden': !showInspector, 'knowledge-view': view === 'knowledge' }" :style="{ '--desktop-reading-font': fontSize + 'px' }">
    <div v-if="showMenu" class="drawer-shade" @click="showMenu = false"></div>
    <aside class="sidebar" :class="{ open: showMenu }">
      <a class="brand" href="#" @click.prevent="view = 'chat'; showMenu = false"><span class="brand-symbol"><Workflow :size="22" /></span><span><strong>知研工作台</strong><small>Knowledge Studio</small></span></a>
      <button class="new-button" @click="newSession" :disabled="sending || loadingConversation || creatingSession"><MessageSquarePlus :size="18" />新会话<span aria-hidden="true"><Plus :size="16" /></span></button>
      <nav class="workspace-nav" aria-label="工作台导航">
        <button :class="{ active: view === 'chat' }" :aria-current="view === 'chat' ? 'page' : undefined" @click="view = 'chat'; showMenu = false"><MessageSquare :size="18" />对话</button>
        <button class="nav-knowledge" :class="{ active: view === 'knowledge' }" :aria-current="view === 'knowledge' ? 'page' : undefined" @click="view = 'knowledge'; showMenu = false"><Library :size="18" />知识库<span>{{ documents.length }}</span></button>
        <button class="nav-tools" :class="{ active: view === 'tools' }" :aria-current="view === 'tools' ? 'page' : undefined" @click="view = 'tools'; showMenu = false"><Wrench :size="18" />工具<span>{{ enabledTools.length }}</span></button>
      </nav>
      <div class="sidebar-label">会话记录 <span>{{ sessions.length }}</span></div>
      <label class="session-search"><Search :size="14" /><input v-model="sessionSearch" placeholder="搜索会话" aria-label="搜索会话" /></label>
      <div class="session-list">
        <div v-if="loading" class="skeleton-list"><i v-for="n in 4" :key="n"></i></div>
        <div v-for="session in filteredSessions" :key="session.id" class="session-item" :class="{ active: activeId === session.id }">
          <button class="session-select" :title="session.title" :aria-current="activeId === session.id ? 'true' : undefined" @click="selectSession(session.id)" :disabled="sending || loadingConversation || creatingSession"><MessageSquare :size="15" /><span>{{ session.title }}</span></button>
          <div class="session-actions">
            <button class="icon-button" title="重命名" aria-label="重命名" @click="openModal('rename', session)" :disabled="sending"><Pencil :size="13" /></button>
            <button class="icon-button" title="删除会话" aria-label="删除会话" @click="openModal('deleteSession', session)" :disabled="sending"><Trash2 :size="13" /></button>
          </div>
        </div>
        <p v-if="!loading && !filteredSessions.length" class="quiet">暂无会话</p>
      </div>
      <button class="sidebar-settings" @click="openModal('settings')"><Settings2 :size="18" /><span>运行配置</span><small>{{ health?.status === 'ok' ? '服务正常' : '待连接' }}</small><span class="connection-dot" :class="{ ok: health?.status === 'ok' }" aria-hidden="true"></span></button>
    </aside>

    <main class="main-panel">
      <header class="page-header">
        <button class="icon-button mobile-menu" aria-label="会话菜单" title="会话菜单" @click="showMenu = true"><Menu :size="20" /></button>
        <div class="breadcrumb"><span>工作空间</span><ChevronRight :size="13" /><strong>{{ view === 'knowledge' ? '知识库' : view === 'tools' ? '研究工具' : activeSession?.title || '新会话' }}</strong></div>
        <div class="header-actions">
          <div class="reading-controls" role="group" aria-label="界面与正文字号">
            <button class="icon-button" title="缩小字体" aria-label="缩小字体" :disabled="fontSize <= 16" @click="adjustFontSize(-1)"><Minus :size="17" /></button>
            <button class="icon-button reading-reset" :title="'重置字体（当前 ' + fontSize + 'px）'" aria-label="重置字体" @click="fontSize = 18"><Type :size="17" /><span>{{ fontSize }}</span></button>
            <button class="icon-button" title="放大字体" aria-label="放大字体" :disabled="fontSize >= 22" @click="adjustFontSize(1)"><Plus :size="17" /></button>
          </div>
          <label class="model-picker" :class="{ warning: !modelReady || runtime?.demo }">
            <span class="model-status-dot" aria-hidden="true"></span>
            <select v-model="selectedModelId" aria-label="生成模型" :title="selectedModel?.model" :disabled="sending || loading || loadingConversation || creatingSession">
              <option v-for="item in modelOptions" :key="item.id" :value="item.id" :disabled="!item.configured">{{ item.id === 'default' ? (runtime?.demo ? '演示模式' : item.model) : item.label }}{{ !item.configured ? '（未配置）' : '' }}</option>
            </select>
          </label>
          <button v-if="view === 'chat'" class="icon-button" title="来源与执行记录" aria-label="来源与执行记录" @click="showInspector = !showInspector"><PanelRightClose v-if="showInspector" :size="19" /><PanelRightOpen v-else :size="19" /></button>
        </div>
      </header>
      <div v-if="error" class="error-banner" role="alert"><CircleHelp :size="16" /><span>{{ error }}</span><button class="icon-button" title="关闭提示" @click="error = ''"><X :size="16" /></button></div>
      <div v-if="runtime && !modelReady" class="configuration-banner"><Settings2 :size="17" /><span>生成模型尚未配置 API Key</span><button @click="openModal('settings')">查看配置</button></div>

      <template v-if="view === 'chat'">
        <div ref="scrollEl" class="conversation">
          <div v-if="!messages.length" class="welcome">
            <div class="welcome-mark"><Workflow :size="28" :stroke-width="1.8" /></div>
            <h1>知研工作台</h1>
            <p>{{ readyDocs.length ? readyDocs.length + ' 份文档已就绪' : '知识库尚未添加文档' }}</p>
            <div class="suggestions"><button v-for="item in suggestions" :key="item.text" :class="'tone-' + item.tone" @click="chooseSuggestion(item)"><span class="scenario-icon"><component :is="item.icon" :size="23" /></span><span class="scenario-copy"><strong>{{ item.text }}</strong><small>{{ item.detail }}</small></span><ChevronRight :size="16" /></button></div>
          </div>
          <div v-for="message in messages" :key="message.id" class="message" :class="message.role">
            <template v-if="message.role === 'user'"><div class="user-message">{{ message.content }}</div><span v-if="['failed','cancelled'].includes(message.message_metadata?.status)" class="message-note">未完成的请求</span></template>
            <template v-else>
              <div class="assistant-heading"><span class="assistant-mark"><Workflow :size="18" /></span><strong>知研</strong><span v-if="message.message_metadata?.model" class="message-model">{{ message.message_metadata.model }}</span><span v-if="message.status === 'pending'" class="draft-label">草稿</span><span v-else-if="verificationLabel(message.message_metadata)" class="verified" :class="{ warning: message.message_metadata?.verified === false }"><ShieldCheck :size="14" />{{ verificationLabel(message.message_metadata) }}</span></div>
              <MarkdownMessage v-if="message.content" :content="message.content" @citation="id => openCitation(id, message)" />
              <div v-else-if="message.status === 'pending'" class="thinking"><i></i><i></i><i></i><span>{{ status }}</span></div>
              <p v-if="message.status === 'failed'" class="message-note error">执行失败，当前内容可能不完整</p>
              <p v-if="message.status === 'cancelled'" class="message-note">已取消生成</p>
              <p v-if="message.message_metadata?.verified === false" class="message-note warning">校验未通过：{{ message.message_metadata.verification_feedback }}</p>
              <div v-if="message.status !== 'pending'" class="message-actions">
                <button class="icon-button" :title="copiedId === message.id ? '已复制' : '复制回答'" @click="copyMessage(message)" :disabled="!message.content"><Check v-if="copiedId === message.id" :size="15" /><Copy v-else :size="15" /></button>
                <button v-if="message.message_metadata?.sources?.length" class="text-button" @click="inspectMessage(message); showInspector = true; inspectorTab = 'sources'"><BookOpen :size="14" />{{ message.message_metadata.sources.length }} 个来源</button>
                <button v-if="message === lastAssistant" class="icon-button" title="重新生成" aria-label="重新生成" @click="retry" :disabled="sending"><RefreshCw :size="15" /></button>
                <button class="icon-button" title="生成 Word 文档" aria-label="生成 Word 文档" @click="openExport(message, 'docx')" :disabled="sending || exporting || !message.content || ['failed','cancelled'].includes(message.status)"><FileDown :size="18" /></button>
                <button class="icon-button" title="生成 PPT 演示" aria-label="生成 PPT 演示" @click="openExport(message, 'pptx')" :disabled="sending || exporting || !message.content || ['failed','cancelled'].includes(message.status)"><Presentation :size="18" /></button>
              </div>
            </template>
          </div>
        </div>
        <div class="composer-zone">
          <div v-if="sending" class="run-status" role="status"><LoaderCircle :size="14" class="spin" /><span>{{ status }}</span></div>
          <form class="composer" @submit.prevent="sendQuestion()">
            <textarea v-model="input" rows="2" placeholder="输入问题…" aria-label="输入问题" @keydown.enter="handleComposerEnter" :disabled="sending || loadingConversation || creatingSession"></textarea>
            <div class="composer-toolbar"><label class="web-switch" :class="{ enabled: useWeb }"><Globe2 :size="17" /><span>{{ useWeb ? '联网搜索已开启' : '联网搜索关闭' }}</span><input type="checkbox" aria-label="联网搜索" v-model="useWeb" :disabled="sending || !runtime?.web_configured" /><span class="switch-track"></span></label><span class="composer-model">{{ selectedModel?.provider || '—' }}</span><button v-if="sending" type="button" class="send-button cancel" title="取消生成" aria-label="取消生成" @click="cancelRun"><Square :size="16" /></button><button v-else class="send-button" title="发送" aria-label="发送" :disabled="!input.trim() || !modelReady || loadingConversation || creatingSession"><ArrowUp :size="20" /></button></div>
          </form>
          <div class="composer-footer"><span><ShieldCheck :size="13" />{{ runtime?.demo ? '演示模型' : 'AI 生成内容，请核对重要信息' }}</span><span>{{ readyDocs.length }} 份已就绪文档</span></div>
        </div>
      </template>

      <section v-else-if="view === 'knowledge'" class="knowledge-content" @dragover.prevent @drop.prevent="uploadFiles($event.dataTransfer.files)">
        <div class="section-heading"><div><h1>知识库</h1><p>{{ documents.length }} 份文档 · {{ readyDocs.length }} 份已就绪<span v-if="busyDocs.length"> · {{ busyDocs.length }} 份处理中</span></p></div><button class="primary-button" @click="fileInput.click()" :disabled="uploading"><LoaderCircle v-if="uploading" :size="16" class="spin" /><Upload v-else :size="16" />上传文档</button></div>
        <div class="document-table">
          <div class="table-heading"><span>文档</span><span>状态</span><span>片段</span><span>添加时间</span><span></span></div>
          <div v-for="doc in documents" :key="doc.id" class="document-line">
            <div class="doc-name"><span class="file-symbol"><FileText :size="19" /></span><div><strong>{{ doc.filename }}</strong><small>{{ doc.error_message || doc.document_metadata.stage || '—' }}</small></div></div>
            <div><span class="doc-state" :class="doc.document_metadata.needs_reindex ? 'stale' : doc.status">{{ docLabel(doc) }}</span><progress v-if="['pending','processing'].includes(doc.status)" :value="doc.document_metadata.progress || 0" max="1"></progress></div>
            <span class="table-number"><span class="mobile-column-label">片段数 · </span>{{ doc.document_metadata.chunk_count || '—' }}</span><span class="table-date">{{ dateLabel(doc.created_at) }}</span>
            <div class="doc-actions"><button class="icon-button" title="下载原文" @click="download(doc)"><Download :size="15" /></button><button class="icon-button" title="重建索引" @click="rebuild(doc)" :disabled="['pending','processing'].includes(doc.status)"><RefreshCw :size="15" /></button><button class="icon-button" title="删除文档" @click="openModal('deleteDocument', doc)" :disabled="['pending','processing'].includes(doc.status)"><Trash2 :size="15" /></button></div>
          </div>
          <div v-if="!documents.length" class="empty-library"><FolderOpen :size="36" :stroke-width="1.3" /><strong>暂无文档</strong><button class="text-button" @click="fileInput.click()"><Upload :size="15" />添加文件</button></div>
        </div>
        <div class="index-info"><Database :size="15" /><span>{{ runtime?.embedding_model || '—' }}</span><span>{{ runtime?.embedding_dimensions || '—' }} 维</span><span>{{ runtime?.collection || '—' }}</span></div>
      </section>
      <section v-else class="tools-content">
        <div class="section-heading"><div><h1>研究工具</h1><p>{{ enabledTools.length }} 项已启用 · {{ (runtime?.tools || []).length }} 项能力</p></div><button class="secondary-button" @click="openModal('settings')"><Settings2 :size="17" />配置状态</button></div>
        <div class="tool-groups">
          <section v-for="group in toolGroups" :key="group.category" class="tool-group" :class="'tone-' + group.tone">
            <h2><component :is="group.icon" :size="20" />{{ group.title }}</h2>
            <div v-for="tool in (runtime?.tools || []).filter(item => item.category === group.category)" :key="tool.name" class="tool-row">
              <div><strong>{{ tool.label }}</strong><small>{{ tool.name }}</small><p v-if="!tool.configured">{{ tool.key_env }}</p></div>
              <span class="tool-state" :class="{ ready: tool.configured }">{{ tool.configured ? '已启用' : '需配置' }}</span>
            </div>
          </section>
        </div>
      </section>
    </main>

    <button v-if="showInspector && view === 'chat'" class="inspector-shade" aria-label="关闭研究详情遮罩" tabindex="-1" @click="showInspector = false"></button>
    <aside v-if="showInspector && view === 'chat'" class="inspector" aria-label="研究详情">
      <div class="inspector-heading"><strong>研究详情</strong><button class="icon-button" title="关闭详情" @click="showInspector = false"><X :size="17" /></button></div>
      <div class="inspector-tabs"><button :class="{ active: inspectorTab === 'sources' }" :aria-pressed="inspectorTab === 'sources'" @click="inspectorTab = 'sources'">来源 <span>{{ sources.length }}</span></button><button :class="{ active: inspectorTab === 'activity' }" :aria-pressed="inspectorTab === 'activity'" @click="inspectorTab = 'activity'">执行记录 <span>{{ trace.length + toolEvents.length }}</span></button></div>
      <div class="inspector-body">
        <template v-if="inspectorTab === 'sources'">
          <div v-if="!sources.length" class="inspector-empty"><BookOpen :size="26" :stroke-width="1.3" /><p>{{ sending ? '正在收集资料' : '本次回答暂无引用来源' }}</p></div>
          <div v-for="source in sources" :key="source.citation_id" :id="'source-' + source.citation_id" class="source-item" :class="{ selected: selectedCitation === source.citation_id }">
            <div class="source-top" :class="{ web: source.source_type === 'web' }"><span class="citation-id">{{ source.citation_id }}</span><Globe2 v-if="source.source_type === 'web'" :size="14" /><FileText v-else :size="14" /><span>{{ source.source_type === 'web' ? '网页资料' : '内部文档' }}</span></div>
            <a v-if="source.url && /^https?:\/\//.test(source.url)" :href="source.url" target="_blank" rel="noopener noreferrer">{{ source.title }}</a><button v-else class="source-title" @click="download(source)">{{ source.title }}</button>
            <p>{{ source.snippet }}</p><small v-if="source.score != null">相关度 {{ source.score.toFixed(2) }}</small>
          </div>
        </template>
        <template v-else>
          <div v-if="!trace.length && !toolEvents.length" class="inspector-empty"><Workflow :size="26" :stroke-width="1.3" /><p>暂无执行记录</p></div>
          <ol class="activity-list"><li v-for="(step, i) in toolEvents" :key="'tool-' + i"><LoaderCircle v-if="step.running" class="spin" :size="17" /><CircleHelp v-else-if="step.success === false" :size="17" class="error" /><CheckCircle2 v-else :size="17" /><div><strong>{{ step.name }}</strong><p>{{ step.detail || '正在调用工具' }}</p><p v-if="step.query" class="search-query">{{ step.query }}</p><small v-if="step.domains?.length">域名：{{ step.domains.join('、') }}</small><small v-else>{{ step.agent }}</small></div></li><li v-for="(step, i) in trace" :key="i"><CheckCircle2 :size="17" /><div><strong>{{ step.node }}</strong><p>{{ step.detail }}</p></div></li></ol>
        </template>
      </div>
      <div class="inspector-bottom"><Library :size="15" /><span>{{ readyDocs.length }} 份资料可检索</span><button class="icon-button" title="打开知识库" @click="view = 'knowledge'"><ChevronRight :size="16" /></button></div>
    </aside>
    <input ref="fileInput" class="hidden-input" type="file" multiple accept=".txt,.md,.csv,.json,.pdf,.docx,.pptx" @change="uploadFiles($event.target.files)" />
    <div v-if="toast" class="toast" role="status"><CheckCircle2 :size="16" />{{ toast }}</div>
    <div v-if="modal" class="modal-shade" @click.self="!modalBusy && (modal = null)">
      <section ref="dialogEl" class="modal" role="dialog" aria-modal="true" :aria-label="modal.title" @keydown="handleDialogKeydown"><div class="modal-heading"><h2>{{ modal.title }}</h2><button class="icon-button" title="关闭" aria-label="关闭弹窗" @click="modal = null" :disabled="modalBusy"><X :size="19" /></button></div>
        <template v-if="modal.kind === 'settings'">
          <dl class="runtime-list"><dt>生成模型</dt><dd>{{ selectedModel?.provider }} / {{ selectedModel?.model }}</dd><dt>生成 API Key</dt><dd :class="{ error: !modelReady }">{{ modelReady ? '已配置' : '未配置' }}</dd><dt>向量模型</dt><dd>{{ runtime?.embedding_model }} · {{ runtime?.embedding_dimensions }} 维</dd><dt>向量 API Key</dt><dd>{{ runtime?.embedding_configured ? '已配置' : '未配置' }}</dd><dt>网页搜索</dt><dd>{{ runtime?.web_configured ? '已配置' : '未配置' }}</dd><dt>基础设施</dt><dd>{{ health?.status === 'ok' ? 'PostgreSQL / Redis / Qdrant 正常' : '连接异常' }}</dd></dl>
          <ul class="model-configuration-list"><li v-for="item in modelOptions" :key="item.id"><span>{{ item.label }} · {{ item.model }}</span><small :class="{ error: !item.configured }">{{ item.configured ? '已配置' : item.key_env }}</small></li></ul>
          <button class="text-button" @click="modal = { kind: 'token', title: '工作台访问口令' }; modalInput = ''"><ShieldCheck :size="15" />设置访问口令</button>
        </template>
        <template v-else-if="['rename','token','export'].includes(modal.kind)"><label class="modal-field">{{ modal.kind === 'rename' ? '会话名称' : modal.kind === 'export' ? '文档标题' : '访问口令' }}<input v-model="modalInput" :type="modal.kind === 'token' ? 'password' : 'text'" :maxlength="modal.kind === 'export' ? 100 : modal.kind === 'rename' ? 200 : 256" :disabled="modalBusy" @keydown.enter="confirmModal" /></label><p v-if="modal.kind === 'export'" class="export-note">{{ modal.format === 'docx' ? '保留当前回答的正文、表格和资料来源。' : '模型将当前回答整理为幻灯片大纲，包含演讲备注和资料来源；会消耗少量模型额度。' }}</p></template>
        <p v-else-if="modal.kind === 'web-permission'" class="delete-copy">这个问题要求访问互联网。开启后，会将搜索词发送给已配置的搜索服务，并消耗相应额度。</p>
        <p v-else class="delete-copy">{{ modal.kind === 'deleteSession' ? '将删除该会话的消息和运行状态。' : '将删除该文档的原文件和向量索引。' }}<strong>{{ modal.item?.title || modal.item?.filename }}</strong></p>
        <div class="modal-actions"><button class="secondary-button" @click="modal = null" :disabled="modalBusy">{{ modal.kind === 'settings' ? '关闭' : '取消' }}</button><button v-if="modal.kind !== 'settings'" class="primary-button" :class="{ danger: modal.kind.startsWith('delete') }" @click="confirmModal" :disabled="modalBusy"><LoaderCircle v-if="modalBusy" :size="15" class="spin" />{{ modalBusy && modal.kind === 'export' ? '正在生成' : modal.kind.startsWith('delete') ? '确认删除' : modal.kind === 'web-permission' ? '开启并发送' : modal.kind === 'export' ? '生成并下载' : '保存' }}</button></div>
      </section>
    </div>
  </div>
</template>
