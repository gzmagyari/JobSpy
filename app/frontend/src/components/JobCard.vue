<template>
  <div class="card" :class="{ dimmed: job.user_state === 'dismissed' }" @click="open">
    <div class="card-head">
      <img v-if="job.company_logo" :src="job.company_logo" class="logo" @error="hideLogo" alt="" />
      <div class="head-text">
        <h3 class="title">{{ job.title }}</h3>
        <div class="company">{{ job.company || 'Unknown company' }}</div>
      </div>
      <div v-if="job.match_score != null" class="score" :class="scoreClass">
        {{ job.match_score }}
      </div>
    </div>

    <div class="meta">
      <span class="badge site" :class="job.site">{{ job.site }}</span>
      <span v-if="job.is_remote" class="badge remote">Remote</span>
      <span v-if="job.user_state === 'applied'" class="badge applied">Applied</span>
      <span v-if="job.location" class="loc">{{ job.location }}</span>
      <span v-if="job.date_posted" class="date">{{ job.date_posted }}</span>
      <span v-if="salary" class="salary">{{ salary }}</span>
    </div>

    <p v-if="job.match_reason" class="reason">💡 {{ job.match_reason }}</p>

    <div class="card-actions" @click.stop>
      <a :href="job.job_url" target="_blank" rel="noopener" class="btn primary">Open posting ↗</a>
      <a v-if="job.job_url_direct" :href="job.job_url_direct" target="_blank" rel="noopener" class="btn">
        Direct apply ↗
      </a>
      <span class="spacer"></span>
      <button class="btn" :class="{ on: job.user_state === 'applied' }" @click="setState('applied')">
        ✓ Applied
      </button>
      <button class="btn" :class="{ on: job.user_state === 'dismissed' }" @click="setState('dismissed')">
        ✕ Dismiss
      </button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'JobCard',
  props: {
    job: { type: Object, required: true },
  },
  computed: {
    salary() {
      const { min_amount, max_amount, currency } = this.job
      if (!min_amount && !max_amount) return ''
      const c = currency || ''
      const fmt = (n) => (n != null ? Math.round(n).toLocaleString() : '')
      if (min_amount && max_amount) return `${c}${fmt(min_amount)}–${fmt(max_amount)}`
      return `${c}${fmt(min_amount || max_amount)}`
    },
    scoreClass() {
      const s = this.job.match_score
      if (s == null) return ''
      if (s >= 70) return 'high'
      if (s >= 40) return 'mid'
      return 'low'
    },
  },
  methods: {
    open() {
      if (this.job.job_url) window.open(this.job.job_url, '_blank', 'noopener')
    },
    hideLogo(e) {
      e.target.style.display = 'none'
    },
    setState(s) {
      // Toggle off back to "new" if the same state is clicked again.
      const next = this.job.user_state === s ? 'new' : s
      this.$emit('set-state', { id: this.job.id, user_state: next })
    },
  },
}
</script>
