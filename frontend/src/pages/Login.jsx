import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { api, errorMessage, login } from '../api'
import { firebaseConfigured, googleIdToken } from '../firebase'
import { Alert } from '../components/ui'
import { roleHome, useAuth } from '../store'

export default function Login() {
  const { user, setSession } = useAuth()
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to={roleHome(user.role)} replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const data = await login(email.trim(), password)
      setSession(data)
      nav(roleHome(data.user.role), { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally { setBusy(false) }
  }
  const google = async () => {
    setBusy(true); setError('')
    try {
      const idToken = await googleIdToken()
      const { data } = await api.post('/auth/firebase', { id_token: idToken })
      setSession(data)
      nav(roleHome(data.user.role), { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally { setBusy(false) }
  }
  return (
    <div className="login">
      <div className="hero" aria-hidden="true">
        <div className="brand"><i />CampusNova</div>
        <h2>Report it. Assign it. Fix it.</h2>
        <p>Every campus complaint is classified, routed to the right team and tracked until it is closed.</p>
      </div>
      <div className="panel">
      <form onSubmit={submit} aria-label="Sign in">
        <h1>Sign in</h1>
        <p className="muted">Use your campus account.</p>
        <label>Email<input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <label>Password<input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        <Alert>{error}</Alert>
        <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
        {firebaseConfigured() && <button type="button" className="btn-ghost" disabled={busy} onClick={google}>Sign in with Google</button>}
      </form>
      </div>
    </div>
  )
}