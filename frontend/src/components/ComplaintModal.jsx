import { useCallback, useEffect, useState } from 'react'
import { API_URL, api, errorMessage } from '../api'
import { useAuth } from '../store'
import { shrinkImage } from '../imageTools'
import { Alert, Modal, PriorityBadge, Spinner, StatusBadge, fmt } from './ui'

function Photo({ img }) {
  const [src, setSrc] = useState(null)
  const [big, setBig] = useState(null)
  useEffect(() => {
    let url
    api.get(`/complaints/images/${img.id}/file`, { params: { thumbnail: true }, responseType: 'blob' })
      .then((r) => { url = URL.createObjectURL(r.data); setSrc(url) }).catch(() => {})
    return () => url && URL.revokeObjectURL(url)
  }, [img.id])
  useEffect(() => () => big && URL.revokeObjectURL(big), [big])
  const open = () => api.get(`/complaints/images/${img.id}/file`, { responseType: 'blob' })
    .then((r) => setBig(URL.createObjectURL(r.data))).catch(() => {})
  const close = () => setBig(null)
  if (!src) return <span className="thumb skeleton" />
  return (
    <>
      <img className="thumb zoomable" src={src} alt={img.original_name || 'complaint photo'} onClick={open} title="Click to enlarge" />
      {big && (
        <div className="lightbox" role="dialog" aria-label="Photo" onMouseDown={(e) => { e.stopPropagation(); close() }}>
          <img src={big} alt={img.original_name || 'complaint photo'} />
          <button className="btn-ghost" onClick={close} aria-label="Close photo">✕</button>
        </div>
      )}
    </>
  )
}

/** Detail view with the timeline and every action the signed-in user is allowed to take. */
export default function ComplaintModal({ id, onClose, onChanged }) {
  const { user } = useAuth()
  const [c, setC] = useState(null)
  const [workers, setWorkers] = useState([])
  const [error, setError] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api.get(`/complaints/${id}`).then((r) => setC(r.data)).catch((e) => setError(errorMessage(e))), [id])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (user.role === 'admin') api.get('/users/workers').then((r) => setWorkers(r.data)).catch(() => {})
  }, [user.role])

  const act = async (fn) => {
    setBusy(true); setError('')
    try { await fn(); setNote(''); await load(); onChanged?.() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  const post = (path, body) => act(() => api.post(`/complaints/${id}${path}`, body))

  if (!c) return <Modal title="Complaint" onClose={onClose}>{error ? <Alert>{error}</Alert> : <Spinner />}</Modal>
  const mine = c.reported_by === user.id
  const isWorker = user.role === 'maintenance' && c.assigned_to === user.id
  const upload = (file) => act(async () => {
    const fd = new FormData(); fd.append('file', await shrinkImage(file))
    await api.post(`/complaints/${id}/images`, fd)
  })

  return (
    <Modal title={`${c.complaint_number} · ${c.title || ''}`} onClose={onClose}>
      <div className="row gap">
        <StatusBadge s={c.status} /> <PriorityBadge p={c.priority} />
        {c.safety_risk && <span className="badge badge-p-critical">safety risk</span>}
        {c.needs_manual_review && <span className="badge badge-s-registered">awaiting AI review</span>}
        {c.escalation_level > 0 && <span className="badge badge-p-critical">escalated L{c.escalation_level}</span>}
      </div>
      <p>{c.description}</p>
      <dl className="facts">
        <dt>Where</dt><dd>{c.location}</dd>
        <dt>Category</dt><dd>{c.category}</dd>
        <dt>Due</dt><dd>{fmt(c.sla_due_at)} ({c.sla_hours}h target)</dd>
        <dt>Filed</dt><dd>{fmt(c.created_at)}</dd>
      </dl>
      {c.images.length > 0 && <div className="row gap wrap">{c.images.map((i) => <Photo key={i.id} img={i} />)}</div>}
      <Alert>{error}</Alert>

      <div className="actions">
        {user.role === 'admin' && ['registered', 'assigned', 'in_progress'].includes(c.status) && (
          <label>Assign to
            <select disabled={busy} value={c.assigned_to || ''} onChange={(e) => e.target.value && post('/assign', { assignee_id: Number(e.target.value) })}>
              <option value="">— choose —</option>
              {workers.map((w) => <option key={w.id} value={w.id}>{w.full_name}</option>)}
            </select>
          </label>
        )}
        {isWorker && c.status === 'assigned' && <>
          <button disabled={busy} onClick={() => post('/status', { status: 'in_progress', note: '' })}>Start work</button>
          <button disabled={busy} className="btn-ghost" onClick={() => post('/release', { reason: note })}>Hand back</button>
        </>}
        {(isWorker || user.role === 'admin') && c.status === 'in_progress' && (
          <button disabled={busy || !note.trim()} title={note.trim() ? '' : 'Write what was done first'} onClick={() => post('/status', { status: 'resolved', note })}>Mark resolved</button>
        )}
        {(mine || user.role === 'admin') && c.status === 'resolved' && <>
          <button disabled={busy} onClick={() => post('/sign-off')}>Confirm fixed &amp; close</button>
          <button disabled={busy || !note.trim()} className="btn-ghost" onClick={() => post('/reopen', { text: note })}>Not fixed — reopen</button>
        </>}
        {(mine || user.role === 'admin') && c.images.length < 5 && c.status !== 'closed' && (
          <label className="file">Add photo <input type="file" accept="image/jpeg,image/png,image/webp" onChange={(e) => e.target.files[0] && upload(e.target.files[0])} /></label>
        )}
      </div>
      <label className="block">Note / remark
        <textarea rows={2} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What was done, or a message for the others" />
      </label>
      <button disabled={busy || !note.trim()} className="btn-ghost" onClick={() => post('/remarks', { text: note })}>Post as remark</button>

      <h3>Timeline</h3>
      <ol className="timeline">
        {c.history.map((h) => (
          <li key={h.id}>
            <strong>{h.old_status === h.new_status ? 'Remark' : STATUS(h.new_status)}</strong>
            <span className="muted"> · {fmt(h.created_at)}</span>
            {h.remarks && <p>{h.remarks}</p>}
          </li>
        ))}
      </ol>
      <a className="muted" href={`${API_URL}/docs`} hidden>api</a>
    </Modal>
  )
}
const STATUS = (s) => ({ registered: 'Registered', assigned: 'Assigned', in_progress: 'Work started', resolved: 'Resolved', closed: 'Closed' }[s] || s)