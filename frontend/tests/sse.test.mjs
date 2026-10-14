import assert from 'node:assert/strict'
import test from 'node:test'
import { parseFrame, streamChat } from '../src/api.js'

globalThis.sessionStorage = { getItem: () => null }
/** 可控网络字节流，用于检验消息边界和中文字符跨块传输。 */
function mockStream(text, split = 1) {
  const bytes = new TextEncoder().encode(text)
  globalThis.fetch = async () => new Response(new ReadableStream({
    start(controller) {
      for (let index = 0; index < bytes.length; index += split)
        controller.enqueue(bytes.slice(index, index + split))
      controller.close()
    },
  }), { headers: { 'content-type': 'text/event-stream' } })
}

test('SSE parses CRLF, multiline JSON and ignores heartbeat', () => {
  assert.equal(parseFrame(': keepalive'), null)
  assert.deepEqual(parseFrame('event: token\r\ndata: {\r\ndata: "content":"你好"}'),
    { event: 'token', data: { content: '你好' } })
})

test('Chinese UTF-8 and frames survive one-byte network chunks', async () => {
  mockStream('event: token\r\ndata: {"content":"你好"}\r\n\r\nevent: done\r\ndata: {"answer":"你好"}\r\n\r\n')
  const events = []
  await streamChat({}, (event, data) => events.push({ event, data }))
  assert.equal(events[0].data.content, '你好')
  assert.equal(events[1].event, 'done')
})

test('truncated response is not reported as completed', async () => {
  mockStream('event: token\ndata: {"content":"partial"}\n\n', 5)
  await assert.rejects(streamChat({}, () => {}), /提前结束/)
})

test('server error is shown instead of silently ending the stream', async () => {
  mockStream('event: error\ndata: {"message":"上游失败"}\n\n')
  await assert.rejects(streamChat({}, () => {}), /上游失败/)
})

test('failed fetch explains the local service connection rather than exposing raw English', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(streamChat({}, () => {}), /无法连接到项目服务/)
})

test('user cancellation keeps AbortError instead of claiming a network failure', async () => {
  globalThis.fetch = async () => { throw new DOMException('cancelled', 'AbortError') }
  await assert.rejects(streamChat({}, () => {}), { name: 'AbortError' })
})
