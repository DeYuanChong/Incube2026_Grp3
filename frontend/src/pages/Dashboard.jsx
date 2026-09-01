import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, getIdentity } from '../api'

export default function Dashboard() {
  const [issues, setIssues] = useState([])
  const [load, setLoad] = useState(null)
  const [mineOnly, setMineOnly] = useState(getIdentity().role === 'reporter')

  useEffect(() => {
    const params = mineOnly ? { reporter: getIdentity().user } : {}
    api.listIssues(params).then(setIssues).catch(() => setIssues([]))
    api.statsLoad().then(setLoad).catch(() => {})
  }, [mineOnly])

  return (
    <>
      {load && (
        <div className="card">
          <strong>{load.open_count}</strong> issues currently open
          {Object.entries(load.open_by_severity).map(([sev, n]) => (
            <span key={sev} style={{ marginLeft: 12 }}>
              <span className={`badge ${sev}`}>{sev}</span> {n}
            </span>
          ))}
        </div>
      )}
      <div className="card">
        <h2 style={{ display: 'inline-block', marginRight: 16 }}>Issues</h2>
        <label style={{ fontWeight: 400 }}>
          <input type="checkbox" style={{ width: 'auto', marginRight: 6 }}
                 checked={mineOnly} onChange={(e) => setMineOnly(e.target.checked)} />
          only my reports
        </label>
        <table>
          <thead>
            <tr><th>Ref</th><th>Title</th><th>Category</th><th>Location</th>
                <th>Severity</th><th>Status</th></tr>
          </thead>
          <tbody>
            {issues.map((issue) => (
              <tr key={issue.id}>
                <td><Link to={`/issues/${issue.id}`}>{issue.reference_no}</Link></td>
                <td>{issue.title}</td>
                <td>{issue.category.replace('_', ' ')}</td>
                <td>{issue.building} / {issue.floor}{issue.room ? ` / ${issue.room}` : ''}</td>
                <td>{issue.severity ? <span className={`badge ${issue.severity}`}>{issue.severity}</span> : '—'}</td>
                <td><span className={`badge ${issue.status}`}>{issue.status.replace('_', ' ')}</span></td>
              </tr>
            ))}
            {issues.length === 0 && <tr><td colSpan={6} className="hint">No issues yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  )
}
