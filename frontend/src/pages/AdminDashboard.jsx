import { useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import ComplaintModal from '../components/ComplaintModal'
import { Alert, Donut, HBars, PRIORITY_COLOR, PriorityBadge, STATUS_COLOR, STATUS_LABEL, Spinner, StatusBadge } from '../components/ui'

const Stat = ({ label, value, tone }) => (
  <div className={`stat ${tone || ''}`}><span className="muted">{label}</span><strong>{value ?? '—'}</strong></div>
)

export default function AdminDashboard() {
  const [dash, setDash] = useState(null)
  const [emerg, setEmerg] = useState(null)
  const [ai, setAi] = useState(null)
  const [error, setError] = useState('')
  const [openId, setOpenId] = useState(null)

  const load = () => {
    Promise.all([api.get('/dashboard/admin'), api.get('/dashboard/emergencies'), api.get('/dashboard/ai-performance')])
      .then(([d, e, a]) => { setDash(d.data); setEmerg(e.data); setAi(a.data); setError('') })
      .catch((e) => setError(errorMessage(e)))
  }
  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t) }, [])

  if (error) return <Alert>{error}</Alert>
  if (!dash) return <Spinner />
  return (
    <section>
      <h1>Dashboard</h1>
      <p className="sub">Live overview of campus complaints. Refreshes every 30 seconds.</p>
      <div className="stats">
        <Stat label="Open" value={dash.open_complaints} />
        <Stat label="Critical open" value={dash.critical_open} tone={dash.critical_open ? 'bad' : ''} />
        <Stat label="Overdue" value={dash.overdue_complaints} tone={dash.overdue_complaints ? 'bad' : ''} />
        <Stat label="Escalated" value={dash.escalated_open} tone={dash.escalated_open ? 'warn' : ''} />
        <Stat label="Unassigned" value={dash.unassigned_open} />
        <Stat label="AI reviews waiting" value={dash.pending_ai_reviews} tone={dash.pending_ai_reviews ? 'warn' : ''} />
        <Stat label="Avg. resolution (h)" value={dash.avg_resolution_hours?.toFixed(1)} />
      </div>

      <div className="charts">
        <figure>
          <figcaption>Complaints by priority</figcaption>
          <Donut data={dash.by_priority.map((p) => ({ name: p.priority, value: p.count, color: PRIORITY_COLOR[p.priority] }))} />
        </figure>
        <figure>
          <figcaption>Complaints by status</figcaption>
          <Donut data={dash.by_status.map((p) => ({ name: STATUS_LABEL[p.status] || p.status, value: p.count, color: STATUS_COLOR[p.status] }))} />
        </figure>
        <figure>
          <figcaption>Complaints by category</figcaption>
          <HBars data={dash.by_category.map((c) => ({ name: c.category, value: c.count }))} />
        </figure>
      </div>

      <h2>Emergencies</h2>
      {!emerg?.length ? <p className="muted">No open critical or safety-risk complaints.</p> : (
        <table className="emergency">
          <thead><tr><th>No.</th><th>Problem</th><th>Where</th><th>Priority</th><th>Status</th><th>Deadline</th><th>Escalation</th></tr></thead>
          <tbody>{emerg.map((e) => (
            <tr key={e.complaint_id} className={e.safety_risk ? "safety" : ""} onClick={() => setOpenId(e.complaint_id)}>
              <td>#{e.complaint_id}</td><td>{e.title}</td><td>{e.location}</td><td><PriorityBadge p={e.priority} /></td>
              <td><StatusBadge s={e.status} /></td><td className={e.is_overdue ? 'overdue' : ''}>{e.hours_to_deadline == null ? '—' : e.is_overdue ? `${Math.abs(e.hours_to_deadline).toFixed(1)}h overdue` : `${e.hours_to_deadline.toFixed(1)}h left`}</td><td>{e.escalation_level || '—'}</td>
            </tr>))}</tbody>
        </table>
      )}

      {ai && (
        <>
          <h2>AI performance</h2>
          <div className="stats">
            <Stat label="Predictions" value={ai.total_predictions} />
            <Stat label="Flagged for review" value={ai.flagged_for_review} />
            <Stat label="Admin agreement" value={ai.agreement_rate_pct == null ? '—' : `${ai.agreement_rate_pct}%`} />
            <Stat label="Overridden" value={ai.overridden} />
            <Stat label="Avg. confidence" value={ai.avg_priority_confidence == null ? '—' : `${Math.round(ai.avg_priority_confidence * 100)}%`} />
          </div>
          <p className="muted">Agreement is judged only on predictions the AI flagged and an admin reviewed; it is not a measure of overall accuracy.</p>
        </>
      )}
      {openId && <ComplaintModal id={openId} onClose={() => setOpenId(null)} onChanged={load} />}
    </section>
  )
}
