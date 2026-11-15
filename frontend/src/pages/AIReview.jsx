import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { Alert, PriorityBadge, Spinner } from '../components/ui'

const CATEGORIES = ['electrical', 'civil', 'networking', 'sanitation', 'laboratory', 'general']
const PRIORITIES = ['critical', 'high', 'medium', 'low']

function Item({ item, onDone }) {
  const [cat, setCat] = useState(item.predicted_category)
  const [pri, setPri] = useState(item.predicted_priority)
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const changed = cat !== item.predicted_category || pri !== item.predicted_priority
  const run = async (path, body) => {
    setBusy(true); setError('')
    try { await api.post(`/ai/predictions/${item.prediction_id}/${path}`, body); onDone() } catch (e) { setError(errorMessage(e)) } finally { setBusy(false) }
  }
  return (
    <article className="card">
      <h3>{item.title} <span className="muted">#{item.complaint_id}</span></h3>
      <p className="muted">{item.input_text}</p>
      <p>AI says <strong>{item.predicted_category}</strong> / <PriorityBadge p={item.predicted_priority} /> — confidence {Math.round(item.category_confidence * 100)}% / {Math.round(item.priority_confidence * 100)}%</p>
      {item.reasons.length > 0 && <ul className="reasons">{item.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}
      <div className="row gap wrap">
        <label>Category<select value={cat} onChange={(e) => setCat(e.target.value)}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label>Priority<select value={pri} onChange={(e) => setPri(e.target.value)}>{PRIORITIES.map((c) => <option key={c}>{c}</option>)}</select></label>
        <label className="grow">Note<input value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} /></label>
      </div>
      <Alert>{error}</Alert>
      <div className="row gap">
        {!changed && <button disabled={busy} onClick={() => run('confirm', { notes })}>Confirm AI result</button>}
        {changed && <button disabled={busy} onClick={() => run('override', { category: cat, priority: pri, notes })}>Override with my choice</button>}
      </div>
    </article>
  )
}

export default function AIReview() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api.get('/ai/reviews').then((r) => setItems(r.data)).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load() }, [load])
  return (
    <section>
      <h1>AI review</h1>
      <p className="sub">Complaints the AI was unsure about. Nothing is assigned until you confirm or correct it (safety risks are assigned immediately).</p>
      <Alert>{error}</Alert>
      {!items ? <Spinner /> : items.length === 0 ? <p>All clear — nothing waiting for review.</p> : items.map((i) => <Item key={i.prediction_id} item={i} onDone={load} />)}
    </section>
  )
}