import { useEffect } from 'react'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

export const PRIORITY_COLOR = { critical: '#c2362b', high: '#d9730d', medium: '#c9a227', low: '#2f8a64' }
export const STATUS_COLOR = { registered: '#8b98a1', assigned: '#2b6fb0', in_progress: '#7a55c0', resolved: '#2f8a64', closed: '#5d6b74' }
export const BRAND = '#0e8a85'
export const STATUS_LABEL = { registered: 'Registered', assigned: 'Assigned', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed' }

export function Badge({ kind, children }) {
  return <span className={`badge badge-${kind}`}>{children}</span>
}
export const PriorityBadge = ({ p }) => (p ? <Badge kind={`p-${p}`}>{p}</Badge> : null)
export const StatusBadge = ({ s }) => <Badge kind={`s-${s}`}>{STATUS_LABEL[s] || s}</Badge>

export function Alert({ kind = 'error', children }) {
  if (!children) return null
  return <div role={kind === 'error' ? 'alert' : 'status'} className={`alert alert-${kind}`}>{children}</div>
}

export function Spinner({ label = 'Loading…' }) {
  return <p className="muted" aria-busy="true">{label}</p>
}

export function Modal({ title, onClose, children }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header><h2>{title}</h2><button className="btn-ghost" onClick={onClose} aria-label="Close">✕</button></header>
        {children}
      </div>
    </div>
  )
}

export const fmt = (iso) => (iso ? new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z').toLocaleString() : '—')

export function Pager({ page, pageSize, total, onPage }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div className="pager">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</button>
      <span>Page {page} of {pages} · {total} total</span>
      <button disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  )
}

/** Donut with the total in the middle and a legend underneath. data: [{name, value, color}] */
export function Donut({ data, height = 210 }) {
  const rows = data.filter((d) => d.value > 0)
  const total = rows.reduce((a, d) => a + d.value, 0)
  if (!total) return <p className="muted" style={{ padding: '3rem 0', textAlign: 'center' }}>No data yet.</p>
  return (
    <div>
      <div style={{ position: 'relative' }}>
        <ResponsiveContainer width="100%" height={height}>
          <PieChart>
            <Pie data={rows} dataKey="value" nameKey="name" innerRadius="62%" outerRadius="88%" paddingAngle={rows.length > 1 ? 2 : 0} stroke="none">
              {rows.map((d) => <Cell key={d.name} fill={d.color} />)}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}>
          <div style={{ textAlign: 'center' }}><strong style={{ fontSize: '1.8rem', fontWeight: 800 }}>{total}</strong><br /><span className="muted" style={{ fontSize: '.78rem' }}>total</span></div>
        </div>
      </div>
      <ul style={{ listStyle: 'none', display: 'flex', flexWrap: 'wrap', gap: '.4rem 1rem', justifyContent: 'center', padding: 0, margin: '.25rem 0 .6rem', fontSize: '.82rem' }}>
        {rows.map((d) => <li key={d.name}><span style={{ display: 'inline-block', width: 9, height: 9, borderRadius: 3, background: d.color, marginRight: 6 }} />{d.name} <strong>{d.value}</strong></li>)}
      </ul>
    </div>
  )
}

/** Horizontal bars. data: [{name, value}] */
export function HBars({ data, color = BRAND, height }) {
  if (!data.length) return <p className="muted" style={{ padding: '3rem 0', textAlign: 'center' }}>No data yet.</p>
  return (
    <ResponsiveContainer width="100%" height={height || Math.max(150, data.length * 34 + 20)}>
      <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
        <CartesianGrid horizontal={false} strokeDasharray="3 3" />
        <XAxis type="number" allowDecimals={false} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="name" width={90} axisLine={false} tickLine={false} />
        <Tooltip cursor={{ fill: 'rgba(14,138,133,.08)' }} />
        <Bar dataKey="value" fill={color} radius={[0, 6, 6, 0]} barSize={16} />
      </BarChart>
    </ResponsiveContainer>
  )
}