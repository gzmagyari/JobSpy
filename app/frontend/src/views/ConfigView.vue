<template>
  <div class="config" v-if="form">
    <section class="panel">
      <h2>Matching prompt</h2>
      <p class="hint">
        Describe the jobs you want in plain English. The LLM reads each job and uses this to
        decide whether it's a match (and a 0–100 score).
      </p>
      <textarea v-model="form.match_prompt" rows="12" class="prompt"></textarea>
    </section>

    <section class="panel">
      <h2>Search settings</h2>
      <div class="grid">
        <div class="field">
          <div class="field-head">
            <span>Search terms (one per line)</span>
            <button type="button" class="btn small" @click="suggestTerms" :disabled="suggesting">
              {{ suggesting ? 'Thinking…' : '✨ Suggest from prompt' }}
            </button>
          </div>
          <textarea v-model="termsText" rows="4"></textarea>
          <span class="sub-hint">
            Keep these broad (job titles / keywords). Filters like “remote”, seniority or “no
            clearance” go in the prompt above — the LLM applies those.
          </span>
        </div>

        <div class="field">
          <span>Job boards</span>
          <label class="chk"><input type="checkbox" value="indeed" v-model="form.sites" /> Indeed</label>
          <label class="chk"><input type="checkbox" value="linkedin" v-model="form.sites" /> LinkedIn</label>
          <label class="chk"><input type="checkbox" value="reed" v-model="form.sites" /> Reed</label>
          <label class="chk"><input type="checkbox" value="totaljobs" v-model="form.sites" /> Totaljobs</label>
          <label class="chk">
            <input type="checkbox" v-model="form.linkedin_fetch_description" />
            Fetch full LinkedIn descriptions (slower, better matching)
          </label>
        </div>

        <label class="field">Location<input v-model="form.location" /></label>
        <label class="field">Indeed country<input v-model="form.country_indeed" /></label>
        <label class="field">OpenAI model<input v-model="form.openai_model" /></label>
        <label class="field">Results per site<input type="number" v-model.number="form.results_wanted" min="1" max="1000" /></label>
        <label class="field">Max age (hours)<input type="number" v-model.number="form.hours_old" min="1" /></label>
      </div>
    </section>

    <section class="panel">
      <h2>Daily schedule</h2>
      <div class="grid">
        <label class="chk">
          <input type="checkbox" v-model="form.schedule_enabled" /> Run automatically every day
        </label>
        <label class="field">Hour (0–23)<input type="number" v-model.number="form.schedule_hour" min="0" max="23" /></label>
        <label class="field">Minute<input type="number" v-model.number="form.schedule_minute" min="0" max="59" /></label>
      </div>
    </section>

    <div class="save-row">
      <button class="btn primary" @click="save" :disabled="saving">
        {{ saving ? 'Saving…' : 'Save settings' }}
      </button>
      <span class="msg" :class="msgClass">{{ message }}</span>
    </div>

    <section class="panel danger">
      <h2>Danger zone</h2>
      <p class="hint">
        Re-evaluate every job already in the database against the current prompt. Useful after
        editing the prompt. This uses OpenAI credits.
      </p>
      <button class="btn" @click="rematch">Re-match all stored jobs</button>
      <hr class="sep" />
      <p class="hint">
        Remove every stored job and run history to start fresh. Your settings and prompt are
        kept. This cannot be undone.
      </p>
      <button class="btn danger-btn" @click="clearJobs">
        Clear all jobs ({{ stats.total }})
      </button>
    </section>
  </div>
  <div v-else class="empty">Loading settings…</div>
</template>

<script>
import api from '../api'

export default {
  name: 'ConfigView',
  data() {
    return { form: null, termsText: '', saving: false, suggesting: false, message: '', msgClass: '' }
  },
  async mounted() {
    if (!this.$store.state.config) await this.$store.dispatch('fetchConfig')
    this.load()
  },
  computed: {
    stats() {
      return this.$store.state.stats
    },
  },
  methods: {
    load() {
      const c = this.$store.state.config
      if (!c) return
      this.form = { ...c, sites: [...c.sites] }
      this.termsText = (c.search_terms || []).join('\n')
    },
    async suggestTerms() {
      this.suggesting = true
      this.message = ''
      try {
        const res = await api.suggestTerms(this.form.match_prompt, this.form.openai_model)
        if (res.terms && res.terms.length) {
          this.termsText = res.terms.join('\n') // replace existing terms
          this.message = `Suggested ${res.terms.length} search terms — review and Save.`
          this.msgClass = 'ok'
        } else {
          this.message = 'No terms suggested — try a more detailed prompt.'
          this.msgClass = 'err'
        }
      } catch (e) {
        this.message = 'Error: ' + e.message
        this.msgClass = 'err'
      } finally {
        this.suggesting = false
      }
    },
    async save() {
      this.saving = true
      this.message = ''
      try {
        const payload = {
          match_prompt: this.form.match_prompt,
          openai_model: this.form.openai_model,
          search_terms: this.termsText.split('\n').map((s) => s.trim()).filter(Boolean),
          sites: this.form.sites,
          location: this.form.location,
          country_indeed: this.form.country_indeed,
          hours_old: this.form.hours_old,
          results_wanted: this.form.results_wanted,
          linkedin_fetch_description: this.form.linkedin_fetch_description,
          schedule_enabled: this.form.schedule_enabled,
          schedule_hour: this.form.schedule_hour,
          schedule_minute: this.form.schedule_minute,
        }
        await this.$store.dispatch('saveConfig', payload)
        this.message = 'Saved!'
        this.msgClass = 'ok'
        this.load()
      } catch (e) {
        this.message = 'Error: ' + e.message
        this.msgClass = 'err'
      } finally {
        this.saving = false
      }
    },
    async rematch() {
      if (!confirm('Re-match all stored jobs with the current prompt? This uses OpenAI credits.'))
        return
      try {
        await this.$store.dispatch('rematch', 'all')
        this.message = 'Re-matching started — watch the status bar.'
        this.msgClass = 'ok'
      } catch (e) {
        this.message = 'Error: ' + e.message
        this.msgClass = 'err'
      }
    },
    async clearJobs() {
      const n = this.$store.state.stats.total
      if (!confirm(`Delete all ${n} stored jobs and run history? Your settings and prompt are kept. This cannot be undone.`))
        return
      try {
        const res = await api.clearJobs()
        this.message = res.detail || 'Cleared.'
        this.msgClass = 'ok'
        await this.$store.dispatch('fetchStats')
        await this.$store.dispatch('fetchRunStatus')
      } catch (e) {
        this.message = 'Error: ' + e.message
        this.msgClass = 'err'
      }
    },
  },
}
</script>
