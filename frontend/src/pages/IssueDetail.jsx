import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, getIdentity } from '../api'

export default function IssueDetail() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  const refresh = useCallback(
    () => api.getIssue(id).then(setData).catch((e) => setError(e.message)),
    [id],
  )
  useEffect(() => { refresh() }, [refresh])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="hint">Loading…</p>
  const { issue, timeline } = data
  const { role } = getIdentity()
  const canConfirmClose = issue.status === 'verified'

  const confirmClose = async () => {
    await api.closeIssue(issue.id, { closed_by: role === 'admin' ? 'admin' : 'reporter' })
    refresh()
  }

  return (
    <>
      <div className="card">
        <h2>{issue.reference_no} — {issue.title}</h2>
        <p>
          <span className={`badge ${issue.status}`}>{issue.status.replace('_', ' ')}</span>{' '}
          {issue.severity && <span className={`badge ${issue.severity}`}>{issue.severity}</span>}{' '}
          {issue.urgency && <span className={`badge ${issue.urgency}`}>{issue.urgency}</span>}{' '}
          {issue.duplicate_count > 1 && (
            <span className="badge">reported by {issue.duplicate_count} users</span>
          )}
        </p>
        <p>{issue.description}</p>
        <p className="hint">
          {issue.category.replace('_', ' ')} · {issue.building} / {issue.floor}
          {issue.room ? ` / ${issue.room}` : ''} · reported by {issue.reporter_name}
          {issue.equipment_name ? ` · equipment: ${issue.equipment_name}` : ''}
        </p>
        {issue.estimated_resolution_days && issue.status !== 'closed' && (
          <p><strong>Estimated resolution: ~{issue.estimated_resolution_days} days.</strong>{' '}
            <span className="hint">{issue.estimate_basis}</span></p>
        )}
        {canConfirmClose && (
          <button onClick={confirmClose}>Confirm resolved — close issue</button>
        )}
      </div>
      <div className="card">
        <h3>Timeline</h3>
        <table>
          <tbody>
            {timeline.map((ev) => (
              <tr key={ev.id}>
                <td className="hint">{new Date(ev.created_at).toLocaleString()}</td>
                <td>{ev.event_type}</td>
                <td className="hint">{ev.actor}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
