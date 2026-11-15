import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { Alert, Spinner } from '../components/ui'
import { useAuth } from '../store'

const ROLES = ['admin', 'floor_incharge', 'maintenance', 'faculty', 'staff']

export default function Users() {
  const me = useAuth((s) => s.user)
  const [users, setUsers] = useState(null)
  const [depts, setDepts] = useState([])
  const [error, setError] = useState('')
  const [f, setF] = useState({ full_name: '', email: '', staff_id: '', role: 'maintenance', department_id: '', password: '' })
  const load = useCallback(() => api.get('/users').then((r) => setUsers(r.data)).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load(); api.get('/departments').then((r) => setDepts(r.data)).catch(() => {}) }, [load])
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const create = async (e) => {
    e.preventDefault(); setError('')
    try { await api.post('/users', { ...f, department_id: f.department_id ? Number(f.department_id) : null, password: f.password || null }); setF({ ...f, full_name: '', email: '', staff_id: '', password: '' }); load() } catch (err) { setError(errorMessage(err)) }
  }
  const toggle = (u) => api.patch(`/users/${u.id}`, { is_active: !u.is_active }).then(load).catch((e) => setError(errorMessage(e)))
  return (
    <section>
      <h1>Users</h1>
      <Alert>{error}</Alert>
      <form className="row gap wrap card" onSubmit={create} aria-label="Add user">
        <label>Name<input required value={f.full_name} onChange={set('full_name')} /></label>
        <label>Email<input type="email" required value={f.email} onChange={set('email')} /></label>
        <label>Staff id<input required value={f.staff_id} onChange={set('staff_id')} /></label>
        <label>Role<select value={f.role} onChange={set('role')}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></label>
        <label>Department<select value={f.department_id} onChange={set('department_id')}><option value="">—</option>{depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label>
        <label>Password<input type="password" autoComplete="new-password" value={f.password} onChange={set('password')} placeholder="8+ chars, letter + digit" /></label>
        <button>Add user</button>
      </form>
      {!users ? <Spinner /> : (
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Dept</th><th>Active</th><th /></tr></thead>
          <tbody>{users.map((u) => (
            <tr key={u.id}><td>{u.full_name}</td><td>{u.email}</td><td>{u.role}</td><td>{depts.find((d) => d.id === u.department_id)?.name || '—'}</td><td>{u.is_active ? 'yes' : 'no'}</td>
              <td>{u.id !== me.id && <button className="btn-ghost" onClick={() => toggle(u)}>{u.is_active ? 'Disable' : 'Enable'}</button>}</td></tr>))}
          </tbody>
        </table>
      )}
    </section>
  )
}
