import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { Alert, Spinner, fmt } from '../components/ui'
import { firebaseConfigured, pushToken } from '../firebase'

function Preferences() {
  const [prefs, setPrefs] = useState(null)
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')
  useEffect(() => { api.get('/auth/me/notification-preferences').then((r) => setPrefs(r.data)).catch((e) => setError(errorMessage(e))) }, [])
  const save = async (next) => {
    setError(''); setMsg('')
    try { const r = await api.put('/auth/me/notification-preferences', next); setPrefs(r.data); setMsg('Saved') } catch (e) { setError(errorMessage(e)) }
  }
  const enablePush = async () => {
    setError(''); setMsg('')
    try { await save({ ...prefs, push: true, fcm_token: await pushToken() }); setMsg('Push notifications enabled on this device') } catch (e) { setError(e.message) }
  }
  if (!prefs) return null
  return (
    <div className="card" aria-label="Notification preferences">
      <h2>My notification settings</h2>
      <div className="row gap wrap">
        <label className="row gap"><input type="checkbox" checked={prefs.email} onChange={(e) => save({ ...prefs, email: e.target.checked })} /> E-mail</label>
        <label className="row gap"><input type="checkbox" checked={prefs.push} onChange={(e) => save({ ...prefs, push: e.target.checked })} /> Push</label>
        <span className="muted">In-app notifications are always on.</span>
      </div>
      {firebaseConfigured() && <p><button className="btn-ghost" onClick={enablePush}>{prefs.fcm_token ? 'Re-register this device for push' : 'Enable push on this device'}</button></p>}
      <Alert>{error}</Alert><Alert kind="ok">{msg}</Alert>
    </div>
  )
}

export default function Notifications() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api.get('/notifications', { params: { limit: 100 } }).then((r) => setItems(r.data)).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load() }, [load])
  const read = (n) => api.post(`/notifications/${n.id}/read`).then(load).catch((e) => setError(errorMessage(e)))
  const readAll = () => api.post('/notifications/read-all').then(load).catch((e) => setError(errorMessage(e)))
  return (
    <section>
      <div className="row between"><h1>Notifications</h1><button className="btn-ghost" onClick={readAll}>Mark all read</button></div>
      <Preferences />
      <Alert>{error}</Alert>
      {!items ? <Spinner /> : items.length === 0 ? <p className="muted">Nothing yet.</p> : (
        <ul className="notes">
          {items.map((n) => (
            <li key={n.id} className={n.is_read ? 'read' : 'unread'}>
              <div><strong>{n.title}</strong> <span className="muted">· {fmt(n.created_at)}</span></div>
              <p>{n.message}</p>
              {!n.is_read && <button className="btn-ghost" onClick={() => read(n)}>Mark read</button>}
            </li>))}
        </ul>
      )}
    </section>
  )
}
