<template>
  <div class="jobs">
    <div class="toolbar">
      <div class="filters">
        <select v-model="filters.status" @change="reload">
          <option value="matched">Matched</option>
          <option value="all">All</option>
          <option value="rejected">Rejected</option>
          <option value="pending">Pending</option>
          <option value="error">Errors</option>
        </select>
        <select v-model="filters.site" @change="reload">
          <option value="">All sites</option>
          <option value="indeed">Indeed</option>
          <option value="linkedin">LinkedIn</option>
        </select>
        <select v-model="filters.sort" @change="reload">
          <option value="date">Newest first</option>
          <option value="score">Highest score</option>
        </select>
        <input v-model.lazy="filters.q" @change="reload" placeholder="Search title / company…" />
        <label class="chk">
          <input type="checkbox" v-model="filters.include_dismissed" @change="reload" />
          show dismissed
        </label>
      </div>
      <div class="summary">
        <strong>{{ total }}</strong> shown · <strong>{{ stats.matched }}</strong> matched ·
        <strong>{{ stats.total }}</strong> scraped
      </div>
    </div>

    <div v-if="loading" class="empty">Loading…</div>
    <div v-else-if="!jobs.length" class="empty">
      No jobs here yet. Set your preferences in <router-link to="/config">Config</router-link>,
      then hit <strong>Run now</strong>.
    </div>
    <div v-else class="cards">
      <JobCard v-for="j in jobs" :key="j.id" :job="j" @set-state="onSetState" />
    </div>

    <div class="pager" v-if="totalPages > 1">
      <button class="btn" :disabled="page <= 1" @click="go(page - 1)">‹ Prev</button>
      <span>Page {{ page }} / {{ totalPages }}</span>
      <button class="btn" :disabled="page >= totalPages" @click="go(page + 1)">Next ›</button>
    </div>
  </div>
</template>

<script>
import JobCard from '../components/JobCard.vue'
import api from '../api'

export default {
  name: 'JobsView',
  components: { JobCard },
  data() {
    return {
      jobs: [],
      total: 0,
      page: 1,
      pageSize: 25,
      loading: false,
      filters: { status: 'matched', site: '', sort: 'date', q: '', include_dismissed: false },
    }
  },
  computed: {
    stats() {
      return this.$store.state.stats
    },
    totalPages() {
      return Math.max(1, Math.ceil(this.total / this.pageSize))
    },
    runJustFinished() {
      return this.$store.state.runJustFinished
    },
  },
  watch: {
    // Refresh the list automatically when a run completes.
    runJustFinished() {
      this.fetchJobs()
    },
  },
  mounted() {
    this.fetchJobs()
  },
  methods: {
    async fetchJobs() {
      this.loading = true
      try {
        const params = {
          status: this.filters.status,
          sort: this.filters.sort,
          page: this.page,
          page_size: this.pageSize,
          include_dismissed: this.filters.include_dismissed,
        }
        if (this.filters.site) params.site = this.filters.site
        if (this.filters.q) params.q = this.filters.q
        const data = await api.getJobs(params)
        this.jobs = data.items
        this.total = data.total
      } catch (e) {
        console.error('failed to load jobs', e)
      } finally {
        this.loading = false
      }
    },
    reload() {
      this.page = 1
      this.fetchJobs()
    },
    go(p) {
      this.page = p
      this.fetchJobs()
    },
    async onSetState({ id, user_state }) {
      try {
        await api.setJobState(id, user_state)
        await this.fetchJobs()
        this.$store.dispatch('fetchStats')
      } catch (e) {
        alert('Could not update job: ' + e.message)
      }
    },
  },
}
</script>
