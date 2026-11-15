import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import ComplaintModal from '../components/ComplaintModal'
import { useAuth } from '../store'
import { Alert, Donut, PRIORITY_COLOR, PriorityBadge, Spinner, StatusBadge, fmt } from '../components/ui'

function List({ items, onOpen, action }) {
  if (!items) return <Spinner />
  if (!items.length) return <p className="muted">Nothing here.</p>
  return (
    <table>
      <thead><tr><th>No.</th><th>Problem</th><th>Place</th><th>Priority</th><th>Status</th><th>Due</th>{action && <th />}</tr></thead>
      <tbody>{items.map((c) => (
        <tr key={c.id} onClick={() => onOpen(c.id)}>
          <td>{c.complaint_number}</td><td>{c.title}</td><td>{c.location}</td><td><PriorityBadge p={c.priority} /></td>
          <td><StatusBadge s={c.status} /></td><td>{fmt(c.sla_due_at)}</td>
          {action && <td onClick={(e) => e.stopPropagation()}>{action(c)}</td>}
        </tr>))}
      </tbody>
    </table>
  )
}

/** Worker queue: jobs assigned to me. */
export function MyWork() {
  const me = useAuth((s) => s.user)
  const [stats, setStats] = useState(null)
  const [items, setItems] = useState(null)
  const [openId, setOpenId] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api.get('/complaints', { params: { open_only: true, sort: 'due', page_size: 100 } })
    .then((r) => setItems(r.data.items)).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load() }, [load])
  useEffect(() => { api.get(`/dashboard/maintenance/${me.id}`).then((r) => setStats(r.data)).catch(() => {}) }, [me.id, items])
  return (
    <section>
      <h1>My work</h1>
      <p className="sub">Jobs assigned to you, soonest deadline first. Open one to start, finish or hand it back.</p>
      {stats && (
        <div className="stats" aria-label="My numbers">
          <div className="stat"><span className="muted">Assigned</span><strong>{stats.assigned}</strong></div>
          <div className="stat"><span className="muted">In progress</span><strong>{stats.in_progress}</strong></div>
          <div className="stat"><span className="muted">Resolved today</span><strong>{stats.resolved_today}</strong></div>
        </div>
      )}
      <Alert>{error}</Alert>
      {items && items.length > 0 && (
        <div className="charts" style={{ marginBottom: '1.25rem' }}>
          <figure>
            <figcaption>My open jobs by priority</figcaption>
            <Donut height={170} data={['critical', 'high', 'medium', 'low'].map((p) => ({ name: p, value: items.filter((c) => c.priority === p).length, color: PRIORITY_COLOR[p] }))} />
          </figure>
        </div>
      )}
      <List items={items} onOpen={setOpenId} />
      {openId && <ComplaintModal id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </section>
  )
}

/** Open pool: take a job yourself, no admin needed. */
export function Pool() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)
  const load = useCallback(() => api.get('/complaints/pool').then((r) => setItems(r.data)).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t) }, [load])
  const claim = (id) => api.post(`/complaints/${id}/claim`).then(load).catch((e) => { setError(errorMessage(e)); load() })
  return (
    <section>
      <h1>Open jobs</h1>
      <p className="sub">Unassigned jobs, your department first, most urgent next. Take one and it is yours. Jobs nobody takes are assigned automatically after a few minutes.</p>
      <Alert>{error}</Alert>
      <List items={items} onOpen={setOpenId} action={(c) => <button onClick={() => claim(c.id)}>Take this job</button>} />
      {openId && <ComplaintModal id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </section>
  )
}