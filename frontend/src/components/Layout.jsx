import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { api, logout } from '../api'
import { useAuth } from '../store'

const NAV = {
  admin: [['/admin', 'Dashboard'], ['/complaints', 'All complaints'], ['/history', 'History'], ['/reviews', 'AI review'], ['/routing', 'Routing rules'], ['/users', 'Users'], ['/notifications', 'Notifications']],
  maintenance: [['/work', 'My work'], ['/pool', 'Open jobs'], ['/history', 'My history'], ['/notifications', 'Notifications']],
  default: [['/complaints', 'My complaints'], ['/new', 'Report a problem'], ['/history', 'History'], ['/notifications', 'Notifications']],
}

export default function Layout() {
  const { user, refresh, clear } = useAuth()
  const nav = useNavigate()
  const [unread, setUnread] = useState(0)

  useEffect(() => {
    let live = true
    const load = () => api.get('/notifications/unread-count').then((r) => live && setUnread(r.data.unread)).catch(() => {})
    load()
    const t = setInterval(load, 30000)
    return () => { live = false; clearInterval(t) }
  }, [])

  const links = NAV[user.role] || NAV.default
  const out = async () => { await logout(refresh); clear(); nav('/login') }
  return (
    <div className="shell">
      <aside>
        <div className="brand"><i aria-hidden="true" />CampusNova</div>
        <nav aria-label="Main">
          {links.map(([to, label]) => (
            <NavLink key={to} to={to}>{label}{to === '/notifications' && unread > 0 && <span className="dot">{unread}</span>}</NavLink>
          ))}
        </nav>
        <div className="me">
          <span className="av" aria-hidden="true">{(user.full_name || '?').trim().charAt(0).toUpperCase()}</span>
          <strong>{user.full_name}</strong>
          <span className="muted">{user.role.replace('_', ' ')}</span>
          <button className="btn-ghost" onClick={out}>Sign out</button>
        </div>
      </aside>
      <main><Outlet /></main>
    </div>
  )
}