import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function Notifications() {
  const [items, setItems] = useState([])
  const refresh = () => api.notifications().then(setItems).catch(() => {})
  useEffect(() => { refresh() }, [])

  const markRead = async (id) => { await api.markRead(id); refresh() }
  const markAll = async () => { await api.markAllRead(); refresh() }

  return (
    <div className="card">
      <h2 style={{ display: 'inline-block', marginRight: 16 }}>Notifications</h2>
      <button className="secondary" onClick={markAll}>Mark all read</button>
      {items.length === 0 && <p className="hint">Nothing here yet.</p>}
      {items.map((n) => (
        <div key={n.id} className={`card ${n.is_read ? '' : 'notif-unread'}`}>
          <strong>{n.title}</strong>
          <p style={{ margin: '0.3rem 0' }}>{n.body}</p>
          <span className="hint">{new Date(n.created_at).toLocaleString()}</span>{' '}
          {n.issue_id && <Link to={`/issues/${n.issue_id}`}>open issue</Link>}{' '}
          {!n.is_read && <button className="secondary" onClick={() => markRead(n.id)}>mark read</button>}
        </div>
      ))}
    </div>
  )
}
