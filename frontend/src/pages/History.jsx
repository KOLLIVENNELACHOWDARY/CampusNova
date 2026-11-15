import { useEffect, useMemo, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, errorMessage } from '../api'
import ComplaintModal from '../components/ComplaintModal'
import { Alert, BRAND, HBars, PriorityBadge, Spinner, StatusBadge, fmt } from '../components/ui'
import { useAuth } from '../store'

const utc = (iso) => (iso ? new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z') : null)
const doneAt = (c) => utc(c.closed_at || c.resolved_at)
const hours = (c) => { const d = doneAt(c), s = utc(c.created_at); return d && s ? (d - s) / 36e5 : null }
const nice = (h) => (h == null ? '—' : h < 1 ? `${Math.round(h * 60)} min` : h < 48 ? `${h.toFixed(1)} h` : `${(h / 24).toFixed(1)} days`)

/** Finished work: what a worker has fixed, what a reporter has had fixed, or everything for admins. */
export default function History() {
  const { user } = useAuth()
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [q, setQ] = useState('')
  const [openId, setOpenId] = useState(null)

  const load = () => Promise.all(['resolved', 'closed'].map((status) => api.get('/complaints', { params: { status, page_size: 100, sort: 'newest' } })))
    .then(([a, b]) => setItems([...a.data.items, ...b.data.items].sort((x, y) => doneAt(y) - doneAt(x))))
    .catch((e) => setError(errorMessage(e)))
  useEffect(() => { load() }, [])

  const shown = useMemo(() => (items || []).filter((c) => !q || `${c.complaint_number} ${c.title} ${c.location} ${c.category}`.toLowerCase().includes(q.toLowerCase())), [items, q])
  const stats = useMemo(() => {
    const all = items || []
    const week = Date.now() - 7 * 864e5
    const times = all.map(hours).filter((h) => h != null)
    const withDue = all.filter((c) => c.sla_due_at && doneAt(c))
    const onTime = withDue.filter((c) => doneAt(c) <= utc(c.sla_due_at)).length
    return {
      total: all.length,
      week: all.filter((c) => doneAt(c) && doneAt(c).getTime() >= week).length,
      avg: times.length ? times.reduce((a, b) => a + b, 0) / times.length : null,
      onTime: withDue.length ? Math.round((onTime / withDue.length) * 100) : null,
    }
  }, [items])
  const perDay = useMemo(() => {
    const days = []
    for (let i = 13; i >= 0; i--) { const d = new Date(); d.setHours(0, 0, 0, 0); d.setDate(d.getDate() - i); days.push({ key: d.toDateString(), name: d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }), value: 0 }) }
    for (const c of items || []) { const d = doneAt(c); const row = d && days.find((x) => x.key === d.toDateString()); if (row) row.value += 1 }
    return days
  }, [items])
  const byCategory = useMemo(() => {
    const m = {}
    for (const c of items || []) m[c.category] = (m[c.category] || 0) + 1
    return Object.entries(m).map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value)
  }, [items])

  const mine = user.role === 'maintenance'
  return (
    <section>
      <h1>{mine ? 'My work history' : 'History'}</h1>
      <p className="sub">{mine ? 'Jobs you have finished.' : user.role === 'admin' ? 'Every complaint that has been resolved or closed.' : 'Complaints that have been fixed.'}</p>
      <Alert>{error}</Alert>
      {!items && !error ? <Spinner /> : items && (
        <>
          <div className="stats" aria-label="History numbers">
            <div className="stat"><span className="muted">Completed</span><strong>{stats.total}</strong></div>
            <div className="stat"><span className="muted">Last 7 days</span><strong>{stats.week}</strong></div>
            <div className="stat"><span className="muted">Average time to fix</span><strong>{nice(stats.avg)}</strong></div>
            <div className="stat"><span className="muted">Done within deadline</span><strong>{stats.onTime == null ? '—' : `${stats.onTime}%`}</strong></div>
          </div>
          {items.length > 0 && (
            <div className="charts" style={{ marginBottom: '1.25rem' }}>
              <figure>
                <figcaption>Completed per day (last 14 days)</figcaption>
                <ResponsiveContainer width="100%" height={200}>
                  <BarChart data={perDay} margin={{ left: -20, right: 8 }}>
                    <CartesianGrid vertical={false} strokeDasharray="3 3" />
                    <XAxis dataKey="name" axisLine={false} tickLine={false} interval={1} />
                    <YAxis allowDecimals={false} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: 'rgba(14,138,133,.08)' }} />
                    <Bar dataKey="value" name="Completed" fill={BRAND} radius={[6, 6, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </figure>
              <figure>
                <figcaption>By category</figcaption>
                <HBars data={byCategory} height={200} />
              </figure>
            </div>
          )}
          <div className="filters" style={{ gridTemplateColumns: '1fr' }}>
            <input placeholder="Search finished work" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search history" />
          </div>
          {shown.length === 0 ? <p className="muted">{items.length ? 'No finished work matches.' : 'Nothing finished yet. Completed jobs will show up here.'}</p> : (
            <table>
              <thead><tr><th>No.</th><th>Problem</th><th>Place</th><th>Priority</th><th>Status</th><th>Completed</th><th>Time taken</th></tr></thead>
              <tbody>{shown.map((c) => (
                <tr key={c.id} tabIndex={0} onClick={() => setOpenId(c.id)} onKeyDown={(e) => e.key === 'Enter' && setOpenId(c.id)}>
                  <td>{c.complaint_number}</td><td>{c.title}</td><td>{c.location}</td><td><PriorityBadge p={c.priority} /></td>
                  <td><StatusBadge s={c.status} /></td><td>{fmt(c.closed_at || c.resolved_at)}</td><td>{nice(hours(c))}</td>
                </tr>))}
              </tbody>
            </table>
          )}
        </>
      )}
      {openId && <ComplaintModal id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </section>
  )
}