import { createStore } from 'vuex'
import api from '../api'

let pollTimer = null

export default createStore({
  state() {
    return {
      config: null,
      stats: { total: 0, matched: 0, rejected: 0, pending: 0, error: 0, applied: 0, dismissed: 0 },
      runStatus: { is_running: false },
      // Incremented whenever a run transitions running -> finished, so views
      // can refresh their job lists.
      runJustFinished: 0,
    }
  },
  mutations: {
    setConfig(state, c) {
      state.config = c
    },
    setStats(state, s) {
      state.stats = s
    },
    setRunStatus(state, rs) {
      const was = state.runStatus.is_running
      state.runStatus = rs
      if (was && !rs.is_running) state.runJustFinished++
    },
  },
  actions: {
    async fetchConfig({ commit }) {
      commit('setConfig', await api.getConfig())
    },
    async saveConfig({ commit }, data) {
      const c = await api.updateConfig(data)
      commit('setConfig', c)
      return c
    },
    async fetchStats({ commit }) {
      commit('setStats', await api.getStats())
    },
    async fetchRunStatus({ commit }) {
      commit('setRunStatus', await api.getRunStatus())
    },
    async startRun({ dispatch }) {
      await api.startRun()
      await dispatch('fetchRunStatus')
    },
    async rematch({ dispatch }, scope) {
      await api.rematch(scope)
      await dispatch('fetchRunStatus')
    },
    startPolling({ dispatch }) {
      if (pollTimer) return
      const tick = async () => {
        try {
          await dispatch('fetchRunStatus')
          await dispatch('fetchStats')
        } catch (e) {
          /* backend not up yet — ignore */
        }
      }
      tick()
      pollTimer = setInterval(tick, 3000)
    },
  },
})
