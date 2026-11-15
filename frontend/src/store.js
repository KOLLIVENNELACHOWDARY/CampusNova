import { create } from 'zustand'

const KEY = 'campusnova.session'

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {}
  } catch {
    return {}
  }
}

/** Auth state. Tokens live in localStorage so a reload keeps you signed in. */
export const useAuth = create((set, get) => ({
  user: load().user || null,
  access: load().access || null,
  refresh: load().refresh || null,
  setSession: ({ user, access_token, refresh_token }) => {
    const next = { user: user ?? get().user, access: access_token, refresh: refresh_token }
    try { localStorage.setItem(KEY, JSON.stringify(next)) } catch { /* private mode */ }
    set(next)
  },
  clear: () => {
    try { localStorage.removeItem(KEY) } catch { /* ignore */ }
    set({ user: null, access: null, refresh: null })
  },
}))

export const roleHome = (role) =>
  role === 'admin' ? '/admin' : role === 'maintenance' ? '/work' : '/complaints'
