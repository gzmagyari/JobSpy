<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">🎯 Job Matcher</div>
      <nav class="nav">
        <router-link to="/jobs">Jobs</router-link>
        <router-link to="/config">Config</router-link>
      </nav>
    </header>
    <RunStatusBar />
    <main class="content">
      <router-view />
    </main>
  </div>
</template>

<script>
import RunStatusBar from './components/RunStatusBar.vue'

export default {
  name: 'App',
  components: { RunStatusBar },
  mounted() {
    this.$store.dispatch('startPolling')
  },
}
</script>
