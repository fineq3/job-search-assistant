<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

type Source = { source: string; score: number; snippet: string }
type Job = {
  source: string
  company: string
  position: string
  location: string
  days_per_week: number | null
  duration_months: number | null
  eligibility: string | null
}
type Message = { role: 'user' | 'bot'; text: string; sources?: Source[]; jobs?: Job[] }
type StatusResponse = { docs: string[] }
type UploadResponse = { filename: string; chunks: number }
type AskResponse = { answer: string; sources: Source[]; jobs?: Job[] }

const documents = ref<string[]>([])
const question = ref('')
const messages = ref<Message[]>([])
const statusError = ref('')
const pending = ref<'upload' | 'ask' | 'reset' | null>(null)
const busy = computed(() => pending.value !== null)
const chat = ref<HTMLDivElement | null>(null)
const resetDialog = ref<HTMLDialogElement | null>(null)

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `请求失败（${response.status}）`)
  }
  return response.json()
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : '请求失败，请重试。'
}

function addMessage(role: Message['role'], text: string) {
  const message = reactive<Message>({ role, text })
  messages.value.push(message)
  return message
}

async function refreshStatus() {
  statusError.value = ''
  try {
    const status = await requestJson<StatusResponse>('/api/status')
    documents.value = status.docs
  } catch (error) {
    statusError.value = `无法读取知识库。${errorText(error)}`
  }
}

async function uploadDocuments(event: Event) {
  const input = event.currentTarget as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ''
  if (!files.length || busy.value) return

  pending.value = 'upload'
  const message = addMessage('bot', `正在上传 ${files.length} 份文档…`)
  let uploadedCount = 0
  let chunkCount = 0
  const failures: string[] = []

  try {
    for (const [index, file] of files.entries()) {
      message.text = `正在上传 ${index + 1}/${files.length}：「${file.name}」`
      const form = new FormData()
      form.append('file', file)
      try {
        const result = await requestJson<UploadResponse>('/api/upload', { method: 'POST', body: form })
        if (result.chunks === 0) throw new Error('文档没有可索引的文本。')
        uploadedCount += 1
        chunkCount += result.chunks
      } catch (error) {
        failures.push(`「${file.name}」：${errorText(error)}`)
      }
    }
    await refreshStatus()
    const summary = `上传结束。成功 ${uploadedCount}/${files.length} 份，共入库 ${chunkCount} 段。`
    message.text = failures.length ? [summary, '上传失败的文件', ...failures].join('\n') : summary
  } finally {
    pending.value = null
  }
}

async function ask() {
  const text = question.value.trim()
  if (!text || busy.value) return

  pending.value = 'ask'
  addMessage('user', text)
  question.value = ''
  const message = addMessage('bot', '思考中…')
  try {
    const result = await requestJson<AskResponse>('/api/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: text }),
    })
    message.text = result.answer || '(无返回)'
    message.sources = result.sources
    message.jobs = result.jobs
  } catch (error) {
    message.text = `❌ 出错：${errorText(error)}`
  } finally {
    pending.value = null
  }
}

async function resetKnowledgeBase() {
  if (busy.value) return
  resetDialog.value?.close()
  pending.value = 'reset'
  try {
    await requestJson('/api/reset', { method: 'POST' })
    await refreshStatus()
    messages.value = []
    addMessage('bot', '知识库已清空。')
  } catch (error) {
    addMessage('bot', `清空失败。${errorText(error)}`)
  } finally {
    pending.value = null
  }
}

onMounted(refreshStatus)

watch(messages, () => {
  if (chat.value) chat.value.scrollTop = chat.value.scrollHeight
}, { deep: true, flush: 'post' })
</script>

<template>
  <div class="sidebar">
    <h1>招聘信息助手<small>岗位问答 · 条件筛选 · 来源核对</small></h1>
    <label class="upload-box">
      📄 {{ pending === 'upload' ? '正在上传文档…' : '点击上传文档' }}<br />
      <span style="font-size:11px">支持多选 .txt / .md / .pdf，单文件 ≤ 10 MB</span>
      <input
        type="file"
        id="fileInput"
        accept=".txt,.md,.pdf"
        multiple
        :disabled="busy"
        hidden
        @change="uploadDocuments"
      />
    </label>
    <div class="doc-list">
      <div class="label">已入库文档（{{ documents.length }} 份）</div>
      <div id="docList">
        <div v-if="statusError" class="status-error" role="alert">{{ statusError }}</div>
        <template v-else-if="documents.length">
          <div v-for="document in documents" :key="document" class="doc-item">
            <span>{{ document }}</span>
          </div>
        </template>
        <div v-else style="color:#c9cdd4;font-size:12px">暂无</div>
      </div>
    </div>
    <button class="btn btn-reset" id="resetBtn" type="button" :disabled="busy" @click="resetDialog?.showModal()">
      清空知识库
    </button>
  </div>

  <div class="main">
    <div id="chat" ref="chat" class="chat" role="log" aria-label="岗位问答">
      <div v-if="!messages.length" class="empty" id="empty">
        {{ documents.length ? '招聘资料已就绪，可以开始提问' : '👈 先在左侧上传招聘文档' }}<br />
        例如：筛选合肥的实习岗位，实习时长不超过 3 个月<br />
        <span style="font-size:12px">回答基于已上传资料，招聘实时状态请到官方渠道核对</span>
      </div>
      <div v-for="(message, index) in messages" :key="index" class="msg" :class="message.role">
        <div class="bubble">{{ message.text }}</div>
        <section v-if="message.jobs?.length" class="job-results" aria-label="岗位筛选结果">
          <article v-for="job in message.jobs" :key="job.source" class="job-card">
            <strong>{{ job.company }} · {{ job.position }}</strong>
            <p>{{ job.location }}</p>
            <p v-if="job.days_per_week || job.duration_months">
              <span v-if="job.days_per_week">每周 {{ job.days_per_week }} 天</span>
              <span v-if="job.days_per_week && job.duration_months"> · </span>
              <span v-if="job.duration_months">实习 {{ job.duration_months }} 个月</span>
            </p>
            <p v-if="job.eligibility">{{ job.eligibility }}</p>
            <small>{{ job.source }}</small>
          </article>
        </section>
        <div v-if="message.sources?.length" class="sources">
          检索资料
          <details v-for="(source, sourceIndex) in message.sources" :key="sourceIndex" class="source-tag">
            <summary>{{ source.source }} · 相关度 {{ source.score }}</summary>
            <p>{{ source.snippet }}</p>
          </details>
        </div>
      </div>
    </div>
    <form class="input-bar" @submit.prevent="ask">
      <input id="qInput" v-model="question" maxlength="2000" aria-label="岗位问题" placeholder="基于已上传文档提问…" />
      <button id="askBtn" type="submit" :disabled="busy || !question.trim()">发送</button>
    </form>
  </div>

  <dialog ref="resetDialog" aria-labelledby="reset-title">
    <h2 id="reset-title">清空知识库？</h2>
    <p>当前知识库中的所有文档索引都会被清空。</p>
    <form method="dialog" class="dialog-actions">
      <button class="btn btn-reset" autofocus>取消</button>
      <button type="button" class="btn btn-confirm" @click="resetKnowledgeBase">确认清空</button>
    </form>
  </dialog>
</template>

<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
       background: #f5f6f8; color: #1f2329; height: 100vh; display: flex; }
.sidebar { width: 280px; flex-shrink: 0; background: #fff; border-right: 1px solid #e5e6eb;
           padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.main { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; }
h1 { font-size: 17px; }
h1 small { color: #86909c; font-weight: normal; font-size: 12px; display: block; margin-top: 4px; }
.upload-box { border: 2px dashed #c9cdd4; border-radius: 8px; padding: 18px;
              text-align: center; cursor: pointer; color: #4e5969; font-size: 13px; transition: .2s; }
.upload-box:hover { border-color: #165dff; color: #165dff; }
.doc-list { flex: 1; overflow-y: auto; font-size: 13px; }
.doc-list .label { color: #86909c; margin-bottom: 8px; }
.doc-item { background: #f2f3f5; border-radius: 6px; padding: 6px 10px; margin-bottom: 6px;
            display: flex; justify-content: space-between; }
.doc-item span:last-child { color: #86909c; }
.btn { border: none; border-radius: 6px; padding: 8px; font-size: 13px; cursor: pointer; }
.btn-reset { background: #f2f3f5; color: #4e5969; }
.btn-reset:hover { background: #e5e6eb; }
.chat { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 18px; }
.msg { max-width: 720px; }
.msg.user { align-self: flex-end; }
.bubble { padding: 12px 16px; border-radius: 10px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.user .bubble { background: #165dff; color: #fff; }
.bot .bubble { background: #fff; border: 1px solid #e5e6eb; }
.sources { margin-top: 8px; font-size: 12px; color: #86909c; }
.source-tag { display: inline-block; background: #f2f3f5; border-radius: 4px;
              padding: 2px 8px; margin: 3px 4px 0 0; }
.empty { color: #86909c; text-align: center; margin-top: 80px; font-size: 14px; line-height: 2; }
.input-bar { border-top: 1px solid #e5e6eb; background: #fff; padding: 16px 24px; display: flex; gap: 10px; }
.input-bar input { flex: 1; min-width: 0; border: 1px solid #c9cdd4; border-radius: 8px; padding: 10px 14px; font-size: 14px; outline: none; }
.input-bar input:focus { border-color: #165dff; }
.input-bar button { background: #165dff; color: #fff; border: none; border-radius: 8px; padding: 0 22px; cursor: pointer; }
.input-bar button:disabled { background: #94bfff; cursor: not-allowed; }

#app { display: contents; }
.status-error { color: #a33232; font-size: 12px; }
dialog { max-width: calc(100% - 32px); border: 1px solid #e5e6eb; border-radius: 10px; padding: 20px; margin: auto; }
dialog::backdrop { background: rgb(0 0 0 / 35%); }
dialog h2 { font-size: 16px; }
dialog p { margin: 12px 0 16px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
.btn-confirm { background: #165dff; color: #fff; }
.source-tag summary { cursor: pointer; }
.source-tag p { white-space: pre-wrap; margin-top: 4px; overflow-wrap: anywhere; }
.job-results { display: grid; gap: 8px; margin-top: 10px; }
.job-card { padding: 10px 14px; border: 1px solid #e5e6eb; border-radius: 8px; background: #fff; line-height: 1.6; }
.job-card small { color: #4e5969; overflow-wrap: anywhere; }
@media (max-width: 640px) {
  body { flex-direction: column; height: 100dvh; }
  .sidebar { width: 100%; max-height: 38vh; padding: 12px; gap: 8px; border-bottom: 1px solid #e5e6eb; }
  .upload-box { padding: 8px; }
  .chat { padding: 12px; }
  .input-bar { padding: 12px; }
  .empty { margin-top: 24px; }
}
</style>
