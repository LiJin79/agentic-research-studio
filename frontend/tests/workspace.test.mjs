import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeReadingSize, requiresWebSearch, verificationLabel, webSearchDenied } from '../src/workspace.js'

test('explicit search prompts require permission', () => {
  assert.equal(requiresWebSearch('请进行网页搜索 site:fastapi.tiangolo.com FastAPI features'), true)
  assert.equal(requiresWebSearch('只使用 fastapi.tiangolo.com 域名下的官方资料'), true)
  assert.equal(requiresWebSearch('请查询知识库的负责人'), false)
  assert.equal(requiresWebSearch('你好，不需要查询资料或联网搜索。'), false)
  assert.equal(requiresWebSearch('请解释网页搜索是什么。'), false)
  assert.equal(webSearchDenied('不要联网，直接回答。'), true)
  assert.equal(webSearchDenied('请进行网页搜索'), false)
})
test('verification labels describe scope rather than factual certainty', () => {
  assert.equal(verificationLabel({ verified: true }), '模型检查通过')
  assert.equal(verificationLabel({ verified: false, verification_status: 'insufficient_evidence' }), '证据不足')
  assert.equal(verificationLabel({ verified: true, verification_status: 'general_review' }), '一般回答')
  assert.equal(verificationLabel({ verified: false, verification_status: 'general_review' }), '待核对')
  assert.equal(verificationLabel({ verified: true, verification_status: 'evidence_checked' }), '证据检查通过')
})

test('reading size migrates old preferences and rejects unsafe stored values', () => {
  assert.equal(normalizeReadingSize('large'), 20)
  assert.equal(normalizeReadingSize('standard'), 18)
  assert.equal(normalizeReadingSize(null), 18)
  assert.equal(normalizeReadingSize('16'), 16)
  assert.equal(normalizeReadingSize('22'), 22)
  assert.equal(normalizeReadingSize('1000'), 18)
  assert.equal(normalizeReadingSize('broken'), 18)
})
