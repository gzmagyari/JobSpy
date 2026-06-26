<template>
  <div class="chat">
    <div class="chat-head">
      <div class="chat-title">Chat with your jobs</div>
      <button v-if="messages.length" class="btn small" @click="clearChat">Clear chat</button>
    </div>

    <div class="messages" ref="scroll">
      <div v-if="!messages.length" class="chat-empty">
        <p>Ask the agent anything about your scraped jobs — it can search them all
          (matched <em>and</em> rejected), explain the reasons, and surface the best as cards.</p>
        <div class="examples">
          <button class="chip" v-for="ex in examples" :key="ex" @click="useExample(ex)">{{ ex }}</button>
        </div>
      </div>

      <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
        <template v-if="m.role === 'assistant'">
          <template v-for="(seg, si) in segments(m)">
            <div v-if="seg.type === 'text'" :key="'t' + si" class="bubble md" v-html="renderMd(seg.text)"></div>
            <div v-else :key="'c' + si" class="msg-cards">
              <JobCard :job="seg.job" @set-state="onSetState" />
            </div>
          </template>
        </template>
        <div v-else class="bubble">{{ m.content }}</div>
      </div>

      <div v-if="loading" class="msg assistant">
        <div class="bubble thinking"><span class="spinner"></span> thinking…</div>
      </div>
    </div>

    <form class="composer" @submit.prevent="send">
      <textarea
        v-model="input"
        class="composer-input"
        rows="1"
        placeholder="Ask about your jobs… (Enter to send, Shift+Enter for newline)"
        @keydown.enter.exact.prevent="send"
      ></textarea>
      <button class="btn primary" type="submit" :disabled="loading || !input.trim()">Send</button>
    </form>
  </div>
</template>

<script>
import JobCard from '../components/JobCard.vue'
import api from '../api'
import MarkdownIt from 'markdown-it'

const STORAGE_KEY = 'jobmatcher.chat'

// html:false (default) escapes any raw HTML in the agent's text — safe for v-html.
const md = new MarkdownIt({ linkify: true, breaks: true })
const _openLink =
  md.renderer.rules.link_open || ((t, i, o, e, s) => s.renderToken(t, i, o))
md.renderer.rules.link_open = (tokens, idx, opts, env, self) => {
  tokens[idx].attrSet('target', '_blank')
  tokens[idx].attrSet('rel', 'noopener')
  return _openLink(tokens, idx, opts, env, self)
}

export default {
  name: 'ChatView',
  components: { JobCard },
  data() {
    return {
      messages: [],
      input: '',
      loading: false,
      examples: [
        'Show me the best remote jobs you found',
        'Why were most jobs rejected?',
        'Any jobs that mention LLMs or AI?',
        'Compare the top 2 matches for me',
      ],
    }
  },
  mounted() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      if (saved) this.messages = JSON.parse(saved)
    } catch (e) {
      /* ignore */
    }
    this.scrollDown()
  },
  methods: {
    useExample(text) {
      this.input = text
      this.send()
    },
    renderMd(text) {
      return md.render(text || '')
    },
    // Split an assistant message into ordered text/card segments by parsing the
    // ```jobcard fences the agent emits; cards resolve against message.jobs.
    segments(m) {
      const byId = {}
      for (const j of m.jobs || []) byId[j.id] = j
      const text = m.content || ''
      const re = /```jobcard\s*\n([\s\S]*?)```/gi
      const out = []
      let last = 0
      let match
      while ((match = re.exec(text)) !== null) {
        const before = text.slice(last, match.index).trim()
        if (before) out.push({ type: 'text', text: before })
        const ids = match[1]
          .split('\n')
          .map((s) => s.trim().replace(/^[-•\s]+/, '').replace(/`/g, '').trim())
          .filter(Boolean)
        for (const id of ids) {
          if (byId[id]) out.push({ type: 'card', job: byId[id] })
        }
        last = re.lastIndex
      }
      const tail = text.slice(last).trim()
      if (tail) out.push({ type: 'text', text: tail })
      return out.length ? out : [{ type: 'text', text }]
    },
    async send() {
      const text = this.input.trim()
      if (!text || this.loading) return
      this.messages.push({ role: 'user', content: text })
      this.input = ''
      this.loading = true
      this.scrollDown()
      try {
        const history = this.messages.map((m) => ({ role: m.role, content: m.content }))
        const res = await api.chat(history)
        this.messages.push({ role: 'assistant', content: res.reply, jobs: res.jobs || [] })
      } catch (e) {
        this.messages.push({ role: 'assistant', content: 'Error: ' + e.message, jobs: [] })
      } finally {
        this.loading = false
        this.persist()
        this.scrollDown()
      }
    },
    async onSetState({ id, user_state }) {
      try {
        await api.setJobState(id, user_state)
        // reflect locally on any card showing this job
        for (const m of this.messages) {
          if (!m.jobs) continue
          for (const j of m.jobs) if (j.id === id) j.user_state = user_state
        }
        this.persist()
      } catch (e) {
        alert('Could not update job: ' + e.message)
      }
    },
    persist() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(this.messages))
      } catch (e) {
        /* ignore quota */
      }
    },
    clearChat() {
      this.messages = []
      this.persist()
    },
    scrollDown() {
      this.$nextTick(() => {
        const el = this.$refs.scroll
        if (el) el.scrollTop = el.scrollHeight
      })
    },
  },
}
</script>
