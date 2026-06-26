<template>
  <div class="runbar" :class="{ active: rs.is_running }">
    <div class="status">
      <span v-if="rs.is_running" class="spinner"></span>
      <span class="dot" :class="rs.status" v-else></span>
      <span class="msg">{{ statusText }}</span>
    </div>
    <div class="actions">
      <span class="next" v-if="nextRunText">Next auto-run: {{ nextRunText }}</span>
      <button class="btn primary" @click="run" :disabled="rs.is_running">
        {{ rs.is_running ? 'Running…' : 'Run now' }}
      </button>
    </div>
  </div>
</template>

<script>
export default {
  name: 'RunStatusBar',
  computed: {
    rs() {
      return this.$store.state.runStatus
    },
    statusText() {
      const rs = this.rs
      if (rs.is_running) return rs.message || 'Running…'
      return rs.message || 'Idle'
    },
    nextRunText() {
      const t = this.rs.next_run_at
      if (!t) return ''
      try {
        return new Date(t).toLocaleString()
      } catch {
        return t
      }
    },
  },
  methods: {
    async run() {
      try {
        await this.$store.dispatch('startRun')
      } catch (e) {
        alert('Could not start run: ' + e.message)
      }
    },
  },
}
</script>
