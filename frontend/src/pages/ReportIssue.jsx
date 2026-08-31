import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const CATEGORIES = [
  ['air_conditioning', 'Air-Conditioning'],
  ['lighting', 'Lighting'],
  ['cleanliness', 'Cleanliness'],
  ['toilet', 'Toilet'],
  ['physical_security', 'Physical Security'],
  ['others', 'Others'],
]

export default function ReportIssue() {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    category: 'others', title: '', description: '', building: '', floor: '', room: '',
  })
  const [created, setCreated] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const issue = await api.createIssue({ ...form, room: form.room || null })
      setCreated(issue)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const acceptSuggestion = async () => {
    const updated = await api.acceptSuggestedCategory(created.id)
    setCreated(updated)
  }

  if (created) {
    const suggestsDifferent =
      created.ai_suggested_category &&
      created.ai_suggested_category !== created.category &&
      created.category_source === 'user'
    return (
      <div className="card">
        <h2>Issue {created.reference_no} submitted ✔</h2>
        <p>
          <strong>Estimated resolution: ~{created.estimated_resolution_days} days.</strong>
          <br />
          <span className="hint">{created.estimate_basis} If this is something you could
          fix yourself faster, self-resolving may be quicker.</span>
        </p>
        {suggestsDifferent && (
          <div className="suggestion">
            Based on your description this looks like{' '}
            <strong>{created.ai_suggested_category.replace('_', ' ')}</strong> rather than{' '}
            <strong>{created.category.replace('_', ' ')}</strong>.{' '}
            <button onClick={acceptSuggestion}>Recategorize</button>{' '}
            <button className="secondary" onClick={() => setCreated({ ...created, ai_suggested_category: null })}>
              Keep my category
            </button>
          </div>
        )}
        <button onClick={() => navigate(`/issues/${created.id}`)}>Track this issue</button>
      </div>
    )
  }

  return (
    <div className="card">
      <h2>Report a defect</h2>
      <form onSubmit={submit}>
        <label>Category</label>
        <select value={form.category} onChange={set('category')}>
          {CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <label>Title</label>
        <input required minLength={3} value={form.title} onChange={set('title')}
               placeholder="e.g. Aircon not cold in meeting room" />
        <label>Description (be specific — this drives smart categorization & triage)</label>
        <textarea required minLength={10} rows={4} value={form.description}
                  onChange={set('description')}
                  placeholder="What is wrong, since when, how it affects you…" />
        <label>Building</label>
        <input required value={form.building} onChange={set('building')} placeholder="Block A" />
        <label>Floor</label>
        <input required value={form.floor} onChange={set('floor')} placeholder="Level 3" />
        <label>Room (optional)</label>
        <input value={form.room} onChange={set('room')} placeholder="03-12" />
        {error && <p className="error">{error}</p>}
        <button disabled={busy}>{busy ? 'Submitting…' : 'Submit report'}</button>
      </form>
    </div>
  )
}
