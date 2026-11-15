import axios from 'axios'
import { useAuth } from './store'

export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
export const api = axios.create({ baseURL: API_URL, timeout: 20000 })

api.interceptors.request.use((config) => {
  const { access } = useAuth.getState()
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

let refreshing = null

/** One refresh at a time; every request that failed with 401 waits for the same refresh. */
async function refreshTokens() {
  const { refresh, setSession, clear } = useAuth.getState()
  if (!refresh) throw new Error('no refresh token')
  try {
    const { data } = await axios.post(`${API_URL}/auth/refresh`, { refresh_token: refresh })
    setSession(data)
    return data.access_token
  } catch (e) {
    clear()
    throw e
  }
}

api.interceptors.response.use(
  (r) => r,
  async (error) => {
    const original = error.config
    const is401 = error.response?.status === 401
    const isAuthCall = original?.url?.startsWith('/auth/')
    if (is401 && !original._retried && !isAuthCall && useAuth.getState().refresh) {
      original._retried = true
      refreshing = refreshing || refreshTokens().finally(() => { refreshing = null })
      try {
        const token = await refreshing
        original.headers.Authorization = `Bearer ${token}`
        return api(original)
      } catch {
        /* fall through: the user is signed out by refreshTokens() */
      }
    }
    return Promise.reject(error)
  },
)

/** The server always answers errors as {error: {code, message, details}}. */
export function errorMessage(e) {
  const err = e?.response?.data?.error
  if (err?.details?.length) return `${err.message} ${err.details.map((d) => `${d.field}: ${d.message}`).join('; ')}`
  if (err?.message) return err.message
  if (e?.code === 'ERR_NETWORK') return 'Cannot reach the server. Check your connection.'
  return e?.message || 'Something went wrong.'
}

export const login = (email, password) => api.post('/auth/login', { email, password }).then((r) => r.data)
export const logout = (refresh_token) => api.post('/auth/logout', { refresh_token }).catch(() => {})
