import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import ComplaintModal from '../components/ComplaintModal'
import { Alert, Donut, Pager, PriorityBadge, STATUS_COLOR, STATUS_LABEL, Spinner, StatusBadge, fmt } from '../components/ui'
import { useAuth } from '../store'

const CATEGORIES = ['electrical', 'civil', 'networking', 'sanitation', 'laboratory', 'general']
const STATUSES = ['registered', 'assigned', 'in_progress', 'resolved', 'closed']
const PRIORITIES = ['critical', 'high', 'medium', 'low']
const PAGE_SIZE = 10

export default function Complaints() {
  const { user } = useAuth()
  const [filters, setFilters] = useState({ status: '', category: '', priority: '', q: '', sort: 'newest' })
  const [page, setPage] = useState(1)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)
  const [overview, setOverview] = useState(null)

  const load = useCallback(() => {
    const params = { page, page_size: PAGE_SIZE, sort: filters.sort }
    for (const k of ['status', 'category', 'priority', 'q']) if (filters[k]) params[k] = filters[k]
    api.get('/complaints', { params }).then((r) => { setData(r.data); setError('') }).catch((e) => setError(errorMessage(e)))
  }, [filters, page])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (user.role === 'admin') return
    api.get('/complaints', { params: { page_size: 100 } }).then((r) => setOverview(r.data.items)).catch(() => {})
  }, [user.role, data])

  const set = (k) => (e) => { setPage(1); setFilters({ ...filters, [k]: e.target.value }) }
  return (
    <section>
      <h1>{user.role === 'admin' ? 'All complaints' : 'My complaints'}</h1>
      <p className="sub">{user.role === 'admin' ? 'Search, filter and open any complaint.' : 'Everything you have reported and where it stands.'}</p>
      {overview && overview.length > 0 && (
        <div className="charts" style={{ marginBottom: '1.25rem' }}>
          <figure>
            <figcaption>Your complaints by status</figcaption>
            <Donut height={170} data={STATUSES.map((st) => ({ name: STATUS_LABEL[st], value: overview.filter((c) => c.status === st).length, color: STATUS_COLOR[st] }))} />
          </figure>
          <div className="stats" style={{ gridTemplateColumns: '1fr 1fr', alignSelf: 'stretch', margin: 0 }}>
            <div className="stat"><span className="muted">Open</span><strong>{overview.filter((c) => !['resolved', 'closed'].includes(c.status)).length}</strong></div>
            <div className="stat"><span className="muted">Waiting for your confirmation</span><strong>{overview.filter((c) => c.status === 'resolved').length}</strong></div>
            <div className="stat"><span className="muted">Closed</span><strong>{overview.filter((c) => c.status === 'closed').length}</strong></div>
            <div className="stat"><span className="muted">Critical or high</span><strong>{overview.filter((c) => ['critical', 'high'].includes(c.priority) && !['resolved', 'closed'].includes(c.status)).length}</strong></div>
          </div>
        </div>
      )}
      <div className="filters" role="search">
        <input placeholder="Search text or CN-number" value={filters.q} onChange={set('q')} aria-label="Search" />
        <select value={filters.status} onChange={set('status')} aria-label="Status"><option value="">Any status</option>{STATUSES.map((s) => <option key={s}>{s}</option>)}</select>
        <select value={filters.category} onChange={set('category')} aria-label="Category"><option value="">Any category</option>{CATEGORIES.map((s) => <option key={s}>{s}</option>)}</select>
        <select value={filters.priority} onChange={set('priority')} aria-label="Priority"><option value="">Any priority</option>{PRIORITIES.map((s) => <option key={s}>{s}</option>)}</select>
        <select value={filters.sort} onChange={set('sort')} aria-label="Sort"><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="due">Due soonest</option></select>
      </div>
      <Alert>{error}</Alert>
      {!data ? <Spinner /> : data.items.length === 0 ? <p className="muted">No complaints match.</p> : (
        <table>
          <thead><tr><th>No.</th><th>Problem</th><th>Place</th><th>Priority</th><th>Status</th><th>Filed</th></tr></thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.id} tabIndex={0} onClick={() => setOpenId(c.id)} onKeyDown={(e) => e.key === 'Enter' && setOpenId(c.id)}>
                <td>{c.complaint_number}</td><td>{c.title}</td><td>{c.location}</td>
                <td><PriorityBadge p={c.priority} /></td><td><StatusBadge s={c.status} /></td><td>{fmt(c.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {data && <Pager page={page} pageSize={PAGE_SIZE} total={data.total} onPage={setPage} />}
      {openId && <ComplaintModal id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </section>
  )
}