import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api'
import { Alert, Spinner } from '../components/ui'

/** Admin: which department handles each category. Changes apply to complaints filed from now on. */
export default function Routing() {
  const [rules, setRules] = useState(null)
  const [depts, setDepts] = useState([])
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const load = useCallback(() => Promise.all([api.get('/routing-rules'), api.get('/departments')])
    .then(([r, d]) => { setRules(r.data); setDepts(d.data) }).catch((e) => setError(errorMessage(e))), [])
  useEffect(() => { load() }, [load])

  const save = async (rule, patch) => {
    setError(''); setSaved('')
    try {
      await api.put(`/routing-rules/${rule.category}`, { department_id: rule.department_id, is_active: rule.is_active, ...patch })
      setSaved(`Saved ${rule.category}`); load()
    } catch (e) { setError(errorMessage(e)) }
  }
  if (!rules) return error ? <Alert>{error}</Alert> : <Spinner />
  return (
    <section>
      <h1>Routing rules</h1>
      <p className="sub">Decides which department is responsible for each category, and so which maintenance workers get the job. “Reporter’s own department” is used when no department is set or the rule is switched off.</p>
      <Alert>{error}</Alert>
      <Alert kind="ok">{saved}</Alert>
      <table>
        <thead><tr><th>Category</th><th>Responsible department</th><th>Active</th></tr></thead>
        <tbody>{rules.map((r) => (
          <tr key={r.id} style={{ cursor: 'default' }}>
            <td style={{ textTransform: 'capitalize' }}>{r.category}</td>
            <td>
              <select aria-label={`Department for ${r.category}`} value={r.department_id ?? ''}
                onChange={(e) => save(r, { department_id: e.target.value ? Number(e.target.value) : null })}>
                <option value="">Reporter’s own department</option>
                {depts.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </td>
            <td><input type="checkbox" aria-label={`Active ${r.category}`} checked={r.is_active} onChange={(e) => save(r, { is_active: e.target.checked })} /></td>
          </tr>))}
        </tbody>
      </table>
    </section>
  )
}