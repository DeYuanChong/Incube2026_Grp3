import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, getIdentity } from '../api'

export default function IssueDetail() {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [dismissed, setDismissed] = useState({})

  const refresh = useCallback(
    () => api.getIssue(id).then(setData).catch((e) => setError(e.message)),
    [id],
  )
  useEffect(() => { refresh() }, [refresh])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="hint">Loading…</p>
  const { issue, timeline, photos } = data
  const { role } = getIdentity()
  const canConfirmClose = issue.status === 'verified'

  const confirmClose = async () => {
    await api.closeIssue(issue.id, { closed_by: role === 'admin' ? 'admin' : 'reporter' })
    refresh()
  }
  const acceptCategory = async () => { await api.acceptSuggestedCategory(issue.id); refresh() }
  const acceptTitle = async () => { await api.acceptSuggestedTitle(issue.id); refresh() }
  const acceptDescription = async () => { await api.acceptSuggestedDescription(issue.id); refresh() }
  const dismiss = (field) => setDismissed({ ...dismissed, [field]: true })

  const suggestsCategory = issue.ai_suggested_category &&
    issue.ai_suggested_category !== issue.category && issue.category_source === 'user'

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
        {suggestsCategory && !dismissed.category && (
          <div className="suggestion">
            Based on your description this looks like <strong>{issue.ai_suggested_category.replace('_', ' ')}</strong>{' '}
            rather than <strong>{issue.category.replace('_', ' ')}</strong>.{' '}
            <button onClick={acceptCategory}>Recategorize</button>{' '}
            <button className="secondary" onClick={() => dismiss('category')}>Keep my category</button>
          </div>
        )}
        {issue.ai_suggested_title && !dismissed.title && (
          <div className="suggestion">
            Your photo suggests a different title: <strong>{issue.ai_suggested_title}</strong>.{' '}
            <button onClick={acceptTitle}>Use this title</button>{' '}
            <button className="secondary" onClick={() => dismiss('title')}>Keep mine</button>
          </div>
        )}
        {issue.ai_suggested_description && !dismissed.description && (
          <div className="suggestion">
            Your photo suggests a different description: <em>{issue.ai_suggested_description}</em>{' '}
            <button onClick={acceptDescription}>Use this description</button>{' '}
            <button className="secondary" onClick={() => dismiss('description')}>Keep mine</button>
          </div>
        )}
        {issue.photo_note && <p className="hint">{issue.photo_note}</p>}
        {canConfirmClose && (
          <button onClick={confirmClose}>Confirm resolved — close issue</button>
        )}
      </div>
      {photos.length > 0 && (
        <div className="card">
          <h3>Photos</h3>
          <div className="photo-gallery">
            {photos.map((p) => (
              <a key={p.id} href={api.issuePhotoUrl(issue.id, p.id)} target="_blank" rel="noreferrer">
                <img src={api.issuePhotoUrl(issue.id, p.id)} alt="" />
              </a>
            ))}
          </div>
        </div>
      )}
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
