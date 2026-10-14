/** 本轮明确要求联网时，显示许可确认；不依据旧消息自动开启搜索。 */
export function requiresWebSearch(question) {
  if (webSearchDenied(question)) return false
  if (/\bsite\s*:/i.test(question)
    || /(?:只使用|只根据|仅使用|仅根据|域名下).*?(?:[a-z0-9-]+\.)+[a-z]{2,}/i.test(question)) return true
  if (/(?:解释|介绍|什么是|含义|原理).*(?:网页搜索|联网搜索|网上搜索|搜索网页|web\s*search)|(?:网页搜索|联网搜索|网上搜索|搜索网页|web\s*search).*(?:是什么|什么含义|如何工作)/i.test(question)) return false
  return /(?:请|帮我|需要|使用|进行|通过|开启|执行|利用).{0,16}(?:网页搜索|联网搜索|网上搜索|搜索网页|web\s*search)|搜索词|^(?:网页搜索|联网搜索|网上搜索|搜索网页|web\s*search)/i.test(question)
}

/** 本轮拒绝联网优先于持久偏好，不改变用户下一轮的开关设置。 */
export function webSearchDenied(question) {
  return /(?:不要|不需要|无需|不用|禁止|不允许|不得|不进行|不使用)[^。！？\n,，;；]{0,24}?(?:网页搜索|联网搜索|网上搜索|搜索网页|联网|访问互联网|web\s*search)/i.test(question)
}

/** 显示检查的真实范围，兼容旧消息但不把模型判断包装成事实认证。 */
export function verificationLabel(metadata = {}) {
  if (metadata.verification_status === 'insufficient_evidence') return '证据不足'
  if (metadata.verification_status === 'general_review') return metadata.verified === false ? '待核对' : '一般回答'
  if (metadata.verification_status === 'evidence_checked') return '证据检查通过'
  if (metadata.verified === false) return '待核对'
  if (metadata.verified) return '模型检查通过'
  return ''
}

/** 兼容旧大字偏好，并限制字号范围，防止错误的本地存储值破坏布局。 */
export function normalizeReadingSize(value) {
  if (value === 'large') return 20
  const size = Number(value)
  return Number.isFinite(size) && size >= 16 && size <= 22 ? Math.round(size) : 18
}
