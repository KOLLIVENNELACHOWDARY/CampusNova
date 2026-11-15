import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api'
import { Alert, PriorityBadge } from '../components/ui'
import { shrinkImage } from '../imageTools'

const MAX_MB = 25 // before shrinking; the server limit (4 MB) applies to the shrunk copy
const OK_TYPES = ['image/jpeg', 'image/png', 'image/webp']

export default function NewComplaint() {
  const nav = useNavigate()
  const [f, setF] = useState({ block: '', floor: '', room_number: '', title: '', description: '' })
  const [files, setFiles] = useState([])
  const [error, setError] = useState('')
  const [done, setDone] = useState(null)
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })

  const pick = (e) => {
    const picked = [...e.target.files]
    const bad = picked.find((p) => !OK_TYPES.includes(p.type) || p.size > MAX_MB * 1024 * 1024)
    if (bad) { setError(`${bad.name}: only JPEG/PNG/WebP photos up to ${MAX_MB} MB.`); return }
    if (picked.length > 5) { setError('At most 5 photos.'); return }
    setError('')
    Promise.all(picked.map((p) => shrinkImage(p))).then(setFiles).catch((err) => setError(err.message))
  }

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError('')
    try {
      const body = { ...f, room_number: f.room_number || null, title: f.title || null }
      const { data } = await api.post('/complaints', body)
      const failed = []
      for (const file of files) {
        const fd = new FormData(); fd.append('file', file)
        try { await api.post(`/complaints/${data.id}/images`, fd) } catch (err) { failed.push(`${file.name}: ${errorMessage(err)}`) }
      }
      setDone({ ...data, failed })
    } catch (err) { setError(errorMessage(err)) } finally { setBusy(false) }
  }

  if (done) return (
    <section>
      <h1>Complaint registered</h1>
      <p><strong>{done.complaint_number}</strong> — {done.category}, <PriorityBadge p={done.priority} /> priority. Target: within {done.sla_hours} hours.</p>
      {done.status === 'assigned' && <p>A technician has already been assigned automatically.</p>}
      {done.needs_manual_review && <p>The AI was not fully sure, so an admin will double-check the category.</p>}
      {done.failed.length > 0 && <Alert>Some photos were not uploaded: {done.failed.join('; ')}</Alert>}
      <button onClick={() => nav('/complaints')}>See my complaints</button>
    </section>
  )
  return (
    <section>
      <h1>Report a problem</h1>
      <form onSubmit={submit} className="stack" aria-label="New complaint">
        <div className="grid3">
          <label>Block<input required maxLength={100} value={f.block} onChange={set('block')} placeholder="Block A" /></label>
          <label>Floor<input required maxLength={50} value={f.floor} onChange={set('floor')} placeholder="2" /></label>
          <label>Room <span className="muted">(optional)</span><input maxLength={30} value={f.room_number} onChange={set('room_number')} placeholder="A-204" /></label>
        </div>
        <label>Short title <span className="muted">(optional)</span><input maxLength={200} value={f.title} onChange={set('title')} /></label>
        <label>What is wrong?<textarea required rows={5} maxLength={2000} value={f.description} onChange={set('description')} placeholder="Describe the problem. The AI sets the category and priority for you." /></label>
        <label>Photos <span className="muted">(optional, up to 5)</span><input type="file" accept="image/jpeg,image/png,image/webp" multiple onChange={pick} /></label>
        {files.length > 0 && <div className="row gap wrap">{files.map((p) => <img key={p.name} className="thumb" src={URL.createObjectURL(p)} alt={p.name} />)}</div>}
        <Alert>{error}</Alert>
        <button disabled={busy}>{busy ? 'Submitting…' : 'Submit complaint'}</button>
      </form>
    </section>
  )
}
