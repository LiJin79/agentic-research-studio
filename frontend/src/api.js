const API_PREFIX = '/api/v1'

/** 仅在本浏览器会话保存可选访问口令，模型密钥始终留在服务器。 */
export function setAccessToken(value) {
  if (value) sessionStorage.setItem('workspace-token', value)
  else sessionStorage.removeItem('workspace-token')
}

/** 为普通与流式接口提供一致的鉴权请求头。 */
function authHeaders() {
  const token = sessionStorage.getItem('workspace-token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** 统一 JSON/文件请求，并保留 HTTP 状态便于界面处理 401。 */
async function request(path, options = {}) {
  let response
  try {
    response = await fetch(API_PREFIX + path, {
      ...options, headers: { ...authHeaders(), ...options.headers },
    })
  } catch (error) {
    if (error.name === 'AbortError') throw error
    if (error instanceof TypeError) throw new Error('无法连接到项目服务，请检查 Docker、本机地址和代理设置后重试。')
    throw error
  }
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : detail } catch {}
    const error = new Error(detail)
    error.status = response.status
    throw error
  }
  return response
}

/** 包装 JSON 请求，避免各个调用方重复序列化。 */
async function jsonRequest(path, method = 'GET', payload) {
  const response = await request(path, {
    method, ...(payload ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {}),
  })
  return response.status === 204 ? null : response.json()
}

/** 分页读取工作台会话。 */
export const listSessions = () => jsonRequest('/sessions?limit=100')
/** 创建可持久化的新会话。 */
export const createSession = (title = '新会话') => jsonRequest('/sessions', 'POST', { title })
/** 重命名会话，不清空聊天。 */
export const renameSession = (id, title) => jsonRequest(`/sessions/${id}`, 'PATCH', { title })
/** 删除会话、关联消息和 Checkpoint。 */
export const deleteSession = (id) => jsonRequest(`/sessions/${id}`, 'DELETE')
/** 读取完整分页历史，避免超过 200 条后悄悄丢失消息。 */
export async function listMessages(id) {
  let items = [], offset = 0, page
  do {
    page = await jsonRequest(`/sessions/${id}/messages?limit=200&offset=${offset}`)
    items.push(...page.items)
    offset += page.items.length
  } while (offset < page.total && page.items.length)
  return { items, total: page.total }
}
/** 读取后台入库进度与模型指纹状态。 */
export const listDocuments = () => jsonRequest('/documents?limit=100')
/** 获取不含密钥的运行配置。 */
export const getRuntime = () => jsonRequest('/runtime')
/** 查询基础设施健康状态。 */
export const getHealth = () => jsonRequest('/health/ready')
/** 将文件排入持久入库任务队列。 */
export async function uploadDocument(file) {
  const form = new FormData()
  form.append('file', file)
  return (await request('/documents/upload', { method: 'POST', body: form })).json()
}
/** 重试入库或以当前模型重新索引。 */
export const reindexDocument = (id) => jsonRequest(`/documents/${id}/reindex`, 'POST')
/** 删除原文件、各版本向量及业务记录。 */
export const deleteDocument = (id) => jsonRequest(`/documents/${id}`, 'DELETE')
/** 带访问口令下载原文，并释放临时 Blob URL。 */
export async function downloadDocument(id, filename) {
  const blob = await (await request(`/documents/${id}/download`)).blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 办公技能下载二进制文件，密钥留在后端，PPT 大纲由已配置的模型生成。 */
export async function exportArtifact(messageId, format, title) {
  const response = await request('/artifacts', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_id: messageId, format, title }),
  })
  const blob = await response.blob()
  const match = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get('content-disposition') || '')
  const filename = match ? decodeURIComponent(match[1]) : `研究报告.${format}`
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url; link.download = filename; link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** 解析 SSE 帧，支持 CRLF、多行 data 以及注释心跳。 */
export function parseFrame(frame) {
  let event = 'message'
  const data = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
  }
  return data.length ? { event, data: JSON.parse(data.join('\n')) } : null
}

/** 真正消费增量响应；必须收到 done，连接提前结束不能误标成功。 */
export async function streamChat(payload, onEvent, signal) {
  const response = await request('/chat/stream', {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.headers.get('content-type')?.includes('text/event-stream'))
    throw new Error('服务器没有返回事件流')
  const reader = response.body.getReader(), decoder = new TextDecoder()
  let buffer = '', completed = false
  function consume() {
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const item = parseFrame(frame)
      if (!item) continue
      if (item.event === 'error') throw new Error(item.data.message || '执行失败')
      if (item.event === 'done') completed = true
      onEvent(item.event, item.data)
    }
  }
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) { buffer += decoder.decode(); consume(); break }
      buffer += decoder.decode(value, { stream: true })
      consume()
      if (completed) break
    }
    if (!completed) throw new Error('连接提前结束，回答尚未确认完成')
  } finally {
    await reader.cancel().catch(() => {})
    reader.releaseLock()
  }
}
