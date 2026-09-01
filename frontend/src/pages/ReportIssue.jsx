import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const BUILDINGS = ['A', 'B', 'Annex']

const CATEGORIES = [
  ['air_conditioning', 'Air-Conditioning',
    <><rect x="2.5" y="4" width="19" height="8.5" rx="2.5" /><path d="M6 8.2h12" /><path d="M7 16.5v2.6" /><path d="M12 16.5v3.6" /><path d="M17 16.5v2.6" /></>],
  ['lighting', 'Lighting',
    <><circle cx="12" cy="9.5" r="5.5" /><path d="M9.5 18h5" /><path d="M10.5 21h3" /></>],
  ['cleanliness', 'Cleaning',
    <><path d="M4 20h16" /><rect x="7.5" y="12" width="9" height="5" rx="1.6" /><path d="M12 12V3.5" /></>],
  ['toilet', 'Toilet',
    <><path d="M4 4v7.5a5.5 5.5 0 0 0 5.5 5.5h3A5.5 5.5 0 0 0 18 11.5" /><path d="M4 11.5h16" /><path d="M9 20.5h6" /></>],
  ['physical_security', 'Physical Security',
    <><path d="M12 3l7.5 3v5.5c0 4.4-3.1 8.2-7.5 9.5-4.4-1.3-7.5-5.1-7.5-9.5V6z" /><circle cx="12" cy="11" r="2" /></>],
  ['others', 'Others',
    <><circle cx="5.5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="18.5" cy="12" r="1.6" /></>],
]
const LABELS = Object.fromEntries(CATEGORIES.map(([v, l]) => [v, l]))

const ISSUE_TYPES = {
  air_conditioning: ['Faulty', 'Leaking', 'Not cold', 'Weird noise'],
  lighting: ['Faulty', 'Flickering', 'Too dim'],
  cleanliness: ['Algae / cobweb / pests', 'Cleaning required', 'Dirty floor / window', 'Dry leaves'],
  toilet: ['Choked / clogged', 'Dirty', 'Faulty / broken', 'Wet floor'],
  physical_security: ['Door / gate faulty', 'Lock broken', 'Card reader faulty', 'CCTV faulty'],
  others: ['Furniture', 'Signage', 'Lift', 'Water leak', 'Something else'],
}

export default function ReportIssue() {
  const navigate = useNavigate()
  const [step, setStep] = useState(1)
  const [category, setCategory] = useState(null)
  const [issueType, setIssueType] = useState('')
  const [mobile, setMobile] = useState('')
  const [building, setBuilding] = useState('')
  const [floor, setFloor] = useState('')
  const [room, setRoom] = useState('')
  const [description, setDescription] = useState('')
  const [descTouched, setDescTouched] = useState(false)
  const [descSuggestion, setDescSuggestion] = useState(null)
  const [ack, setAck] = useState(false)
  const [photos, setPhotos] = useState([])
  const [created, setCreated] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const suggestionRequestId = useRef(0)

  // AI description autocomplete: after 2s of no typing, suggest a draft/continuation.
  useEffect(() => {
    if (!descTouched || !issueType) return
    setDescSuggestion(null)
    const requestId = ++suggestionRequestId.current
    const timer = setTimeout(() => {
      api
        .suggestDescription({
          title: `${LABELS[category]} — ${issueType}`,
          category,
          building: building || null,
          floor: floor || null,
          existing_text: description || null,
        })
        .then((res) => {
          if (requestId !== suggestionRequestId.current) return // stale, superseded by newer typing
          if (res.description && res.description !== description) setDescSuggestion(res.description)
        })
        .catch(() => {})
    }, 2000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [description, descTouched, issueType, category, building, floor])

  const acceptSuggestedDraft = () => {
    setDescription(descSuggestion)
    setDescSuggestion(null)
  }

  const pickCategory = (cat) => {
    setCategory(cat)
    setIssueType('')
    setStep(2)
  }

  const onPickPhotos = (e) => {
    setPhotos([...photos, ...Array.from(e.target.files)])
    e.target.value = ''
  }
  const removePhoto = (i) => setPhotos(photos.filter((_, idx) => idx !== i))

  const ready = mobile.length >= 8 && building && floor && issueType && ack

  const submit = async (e) => {
    e.preventDefault()
    if (!ready) return
    setBusy(true)
    setError('')
    try {
      let issue = await api.createIssue({
        category,
        title: `${LABELS[category]} — ${issueType}`,
        description,
        building,
        floor,
        room: room || null,
        mobile_number: `+65 ${mobile}`,
        ack_confirmed: true,
      })
      for (const file of photos) {
        const result = await api.uploadIssuePhoto(issue.id, file)
        issue = result.issue
      }
      setCreated(issue)
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const acceptCategory = async () => setCreated(await api.acceptSuggestedCategory(created.id))
  const acceptTitle = async () => setCreated(await api.acceptSuggestedTitle(created.id))
  const acceptDescription = async () => setCreated(await api.acceptSuggestedDescription(created.id))

  if (step === 3 && created) {
    const suggestsCategory =
      created.ai_suggested_category &&
      created.ai_suggested_category !== created.category &&
      created.category_source === 'user'
    return (
      <div className="card report-mobile">
        <h2>Issue {created.reference_no} submitted ✔</h2>
        {suggestsCategory && (
          <div className="suggestion">
            Based on your description this looks like{' '}
            <strong>{created.ai_suggested_category.replace('_', ' ')}</strong> rather than{' '}
            <strong>{created.category.replace('_', ' ')}</strong>.{' '}
            <button onClick={acceptCategory}>Recategorize</button>{' '}
            <button className="secondary" onClick={() => setCreated({ ...created, ai_suggested_category: null })}>
              Keep my category
            </button>
          </div>
        )}
        {created.ai_suggested_title && (
          <div className="suggestion">
            Your photo suggests a different title: <strong>{created.ai_suggested_title}</strong>.{' '}
            <button onClick={acceptTitle}>Use this title</button>{' '}
            <button className="secondary" onClick={() => setCreated({ ...created, ai_suggested_title: null })}>
              Keep mine
            </button>
          </div>
        )}
        {created.ai_suggested_description && (
          <div className="suggestion">
            Your photo suggests a different description: <em>{created.ai_suggested_description}</em>{' '}
            <button onClick={acceptDescription}>Use this description</button>{' '}
            <button className="secondary" onClick={() => setCreated({ ...created, ai_suggested_description: null })}>
              Keep mine
            </button>
          </div>
        )}
        {created.photo_note && <p className="hint">{created.photo_note}</p>}
        <button onClick={() => navigate(`/issues/${created.id}`)}>Track this issue</button>
      </div>
    )
  }

  if (step === 1) {
    return (
      <div className="card report-mobile">
        <h2>What needs attention?</h2>
        <p className="hint">Pick a category to get started. You can change it later.</p>
        <div className="cat-grid">
          {CATEGORIES.map(([v, l, icon]) => (
            <button key={v} className="cat-card" onClick={() => pickCategory(v)}>
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   strokeWidth="1.6" strokeLinecap="round">{icon}</svg>
              <span>{l}</span>
            </button>
          ))}
        </div>
        <div className="info-card">
          For fire, flooding or anyone in danger, call the 24h hotline <strong>6555 0000</strong> instead
          of filing a report.
        </div>
      </div>
    )
  }

  return (
    <div className="card report-mobile">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <button type="button" className="secondary" onClick={() => setStep(1)}>←</button>
        <span className="cat-pill">{LABELS[category]}</span>
      </div>
      <form onSubmit={submit}>
        <label>Mobile number</label>
        <div className="mobile-input">
          <span>+65</span>
          <input required value={mobile}
                 onChange={(e) => setMobile(e.target.value.replace(/[^0-9 ]/g, '').slice(0, 9))}
                 placeholder="9123 4567" inputMode="numeric" />
        </div>
        <div style={{ display: 'flex', gap: 10 }}>
          <div style={{ flex: 1 }}>
            <label>Building</label>
            <select required value={building} onChange={(e) => setBuilding(e.target.value)}>
              <option value="" disabled>Select</option>
              {BUILDINGS.map((b) => (
                <option key={b} value={b}>{b}</option>
              ))}
            </select>
          </div>
          <div style={{ flex: 1 }}>
            <label>Floor</label>
            <input required value={floor} onChange={(e) => setFloor(e.target.value)} placeholder="Level 3" />
          </div>
        </div>
        <label>Room or area (optional)</label>
        <input value={room} onChange={(e) => setRoom(e.target.value)} placeholder="03-12" />
        <label>What's the issue?</label>
        <div className="chip-row">
          {ISSUE_TYPES[category].map((t) => (
            <button type="button" key={t} className={`chip${issueType === t ? ' active' : ''}`}
                    onClick={() => setIssueType(t)}>{t}</button>
          ))}
        </div>
        <label>Describe more (optional)</label>
        <textarea rows={4} value={description}
                  onChange={(e) => { setDescription(e.target.value); setDescTouched(true) }}
                  placeholder="Help us find it, or tell us more." />
        {descSuggestion && (
          <div className="suggestion">
            AI suggestion: <em>{descSuggestion}</em>{' '}
            <button type="button" onClick={acceptSuggestedDraft}>Use this</button>{' '}
            <button type="button" className="secondary" onClick={() => setDescSuggestion(null)}>Dismiss</button>
          </div>
        )}
        <label>Photo (optional)</label>
        <input type="file" multiple accept="image/*" capture="environment" onChange={onPickPhotos} />
        {photos.length > 0 && (
          <div className="photo-preview-row">
            {photos.map((file, i) => (
              <div key={i} className="photo-preview">
                <img src={URL.createObjectURL(file)} alt="" />
                <button type="button" className="secondary" onClick={() => removePhoto(i)}>✕</button>
              </div>
            ))}
          </div>
        )}
        <label className="ack-row" style={{ marginTop: 12 }}>
          <input type="checkbox" style={{ width: 'auto', margin: 0 }} checked={ack}
                 onChange={(e) => setAck(e.target.checked)} />
          I acknowledge that my name will be recorded along with this report.
        </label>
        {error && <p className="error">{error}</p>}
        <button className="submit-btn" disabled={!ready || busy} style={{ marginTop: 14 }}>
          {busy ? 'Submitting…' : ready ? 'Submit report' : 'Complete the form to submit'}
        </button>
      </form>
    </div>
  )
}
