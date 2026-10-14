<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({ content: { type: String, default: '' } })
const emit = defineEmits(['citation'])
/** Markdown 是模型输出的不可信文本，必须过滤脚本、事件属性和危险链接。 */
const html = computed(() => DOMPurify.sanitize(marked.parse(
  props.content.replace(/\[([KW]\d+)\]/g, '[$1](#source-$1)'),
  { breaks: true, gfm: true },
), {
  ALLOWED_TAGS: ['p','h1','h2','h3','h4','h5','h6','a','pre','code','blockquote','table',
    'thead','tbody','tr','th','td','br','hr','ol','ul','li','strong','em','del'],
  ALLOWED_ATTR: ['href','title'],
}))
/** 引用在工作台中打开详情，外部 HTTP 链接使用独立窗口且禁用 opener。 */
function onClick(event) {
  const link = event.target.closest('a')
  if (!link) return
  const href = link.getAttribute('href') || ''
  if (href.startsWith('#source-')) {
    event.preventDefault()
    emit('citation', href.slice(8))
  } else {
    link.setAttribute('target', '_blank')
    link.setAttribute('rel', 'noopener noreferrer')
  }
}
</script>
<template><div class="markdown" v-html="html" @click="onClick"></div></template>
