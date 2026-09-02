import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'

const BUILDINGS = ['MSCP', 'DTTA', 'BLK B', 'Annex']
const FLOORS = ['L01', 'L02', 'L03', 'L04', 'L05', 'L06', 'L07', 'L08', 'L09', 'L10', 'L11', 'Rooftop']

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
  // { description, suggestedTitle } — either half independently nullable/actionable.
  const [descSuggestion, setDescSuggestion] = useState(null)
  // Set by accepting a suggested title (from either source below) so a
  // freeform AI title isn't silently overridden by the fixed chip labels —
  // see buildTitleAndDescription().
  const [titleOverride, setTitleOverride] = useState(null)
  // { description, title, reason } from the photo pre-check, independent of descSuggestion.
  const [photoSuggestion, setPhotoSuggestion] = useState(null)
  const [ack, setAck] = useState(false)
  const [photos, setPhotos] = useState([])
  const [created, setCreated] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const suggestionRequestId = useRef(0)
  // Photos already sent for a pre-submit AI check — never re-check the same
  // photo twice, even after its suggestion is dismissed.
  const checkedPhotoKeys = useRef(new Set())

  const currentTitle = () =>
    titleOverride || (issueType ? `${LABELS[category]} — ${issueType}` : LABELS[category])

  // AI description autocomplete: after 2s of no typing, suggest a draft/continuation
  // AND check whether the typed text suggests the title itself should change.
  useEffect(() => {
    if (!descTouched) return
    setDescSuggestion(null)
    const requestId = ++suggestionRequestId.current
    const timer = setTimeout(() => {
      api
        .suggestDescription({
          title: currentTitle(),
          building: building || null,
          floor: floor || null,
          existing_text: description || null,
        })
        .then((res) => {
          if (requestId !== suggestionRequestId.current) return // stale, superseded by newer typing
          const suggestedDescription = res.description && res.description !== description ? res.description : null
          const suggestedTitle = res.suggested_title && res.suggested_title !== currentTitle() ? res.suggested_title : null
          if (suggestedDescription || suggestedTitle) {
            setDescSuggestion({ description: suggestedDescription, suggestedTitle })
          }
        })
        .catch(() => {})
    }, 2000)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [description, descTouched, issueType, category, building, floor, titleOverride])

  const acceptSuggestedDraft = () => {
    setDescription(descSuggestion.description)
    setDescTouched(true)
    setDescSuggestion((s) => (s ? { ...s, description: null } : null))
  }
  const dismissSuggestedDraft = () => setDescSuggestion((s) => (s ? { ...s, description: null } : null))

  const acceptDescSuggestedTitle = () => {
    setTitleOverride(descSuggestion.suggestedTitle)
    setIssueType('') // the freeform title no longer matches any fixed chip
    setDescSuggestion((s) => (s ? { ...s, suggestedTitle: null } : null))
  }
  const dismissDescSuggestedTitle = () => setDescSuggestion((s) => (s ? { ...s, suggestedTitle: null } : null))

  const pickCategory = (cat) => {
    setCategory(cat)
    setIssueType('')
    setTitleOverride(null)
    setStep(2)
  }

  const pickIssueType = (t) => {
    setIssueType(t)
    setTitleOverride(null) // an explicit chip pick always wins over a prior AI title
  }

  const photoKey = (file) => `${file.name}_${file.size}_${file.lastModified}`

  const onPickPhotos = (e) => {
    const newFiles = Array.from(e.target.files)
    setPhotos([...photos, ...newFiles])
    e.target.value = ''
    // Straight away, not debounced: only makes sense once there's something
    // to compare the photo against.
    if (!issueType && !description.trim() && !titleOverride) return
    for (const file of newFiles) {
      const key = photoKey(file)
      if (checkedPhotoKeys.current.has(key)) continue
      checkedPhotoKeys.current.add(key)
      api
        .previewPhotoCheck(file, { category, title: currentTitle(), description })
        .then((res) => {
          if (res.verdict !== 'misaligned') return
          if (!res.suggested_title && !res.suggested_description) return
          setPhotoSuggestion({
            title: res.suggested_title || null,
            description: res.suggested_description || null,
            reason: res.reason,
          })
        })
        .catch(() => {})
    }
  }
  const removePhoto = (i) => setPhotos(photos.filter((_, idx) => idx !== i))

  const acceptPhotoTitle = () => {
    setTitleOverride(photoSuggestion.title)
    setIssueType('')
    setPhotoSuggestion((s) => (s ? { ...s, title: null } : null))
  }
  const dismissPhotoTitle = () => setPhotoSuggestion((s) => (s ? { ...s, title: null } : null))
  const acceptPhotoDescription = () => {
    setDescription(photoSuggestion.description)
    setDescTouched(true)
    setPhotoSuggestion((s) => (s ? { ...s, description: null } : null))
  }
  const dismissPhotoDescription = () => setPhotoSuggestion((s) => (s ? { ...s, description: null } : null))

  const ready = mobile.length >= 8 && building && floor && (issueType || description.trim() || titleOverride) && ack

  // Chip and description are either/or: whichever one the reporter skips,
  // the other fills in for it so title/description are never left empty.
  // A titleOverride (accepted AI suggestion) always wins over the chip.
  const buildTitleAndDescription = () => {
    const label = LABELS[category]
    const typed = description.trim()
    if (titleOverride) {
      return { title: titleOverride, description: typed || `${titleOverride}.` }
    }
    if (issueType) {
      return {
        title: `${label} — ${issueType}`,
        description: typed || `${issueType} (${label.toLowerCase()}).`,
      }
    }
    const snippet = typed.length > 60 ? `${typed.slice(0, 57)}...` : typed
    return { title: `${label} — ${snippet}`, description: typed }
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!ready) return
    setBusy(true)
    setError('')
    try {
      const { title, description: finalDescription } = buildTitleAndDescription()
      let issue = await api.createIssue({
        category,
        title,
        description: finalDescription,
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
        {titleOverride && <span className="cat-pill">Title: {titleOverride}</span>}
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
            <select required value={floor} onChange={(e) => setFloor(e.target.value)}>
              <option value="" disabled>Select</option>
              {FLOORS.map((f) => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>
        </div>
        <label>Room or area (optional)</label>
        <input value={room} onChange={(e) => setRoom(e.target.value)} placeholder="03-12" />
        <label>What's the issue?</label>
        {titleOverride && (
          <p className="hint">Using a suggested title above — pick a chip to use one of these instead.</p>
        )}
        <div className="chip-row">
          {ISSUE_TYPES[category].map((t) => (
            <button type="button" key={t} className={`chip${issueType === t ? ' active' : ''}`}
                    onClick={() => pickIssueType(t)}>{t}</button>
          ))}
        </div>
        <label>Describe more (optional)</label>
        <textarea rows={4} value={description}
                  onChange={(e) => { setDescription(e.target.value); setDescTouched(true) }}
                  placeholder="Help us find it, or tell us more." />
        {descSuggestion && (descSuggestion.description || descSuggestion.suggestedTitle) && (
          <div className="suggestion">
            {descSuggestion.description && (
              <p>
                AI suggestion: <em>{descSuggestion.description}</em>{' '}
                <button type="button" onClick={acceptSuggestedDraft}>Use this</button>{' '}
                <button type="button" className="secondary" onClick={dismissSuggestedDraft}>Dismiss</button>
              </p>
            )}
            {descSuggestion.suggestedTitle && (
              <p>
                Based on what you typed, this might really be:{' '}
                <strong>{descSuggestion.suggestedTitle}</strong>{' '}
                <button type="button" onClick={acceptDescSuggestedTitle}>Update title</button>{' '}
                <button type="button" className="secondary" onClick={dismissDescSuggestedTitle}>Dismiss</button>
              </p>
            )}
          </div>
        )}
        {photoSuggestion && (photoSuggestion.title || photoSuggestion.description) && (
          <div className="suggestion">
            <p className="hint">Your photo doesn't quite match what you've written: {photoSuggestion.reason}</p>
            {photoSuggestion.title && (
              <p>
                Suggested title: <strong>{photoSuggestion.title}</strong>{' '}
                <button type="button" onClick={acceptPhotoTitle}>Use this title</button>{' '}
                <button type="button" className="secondary" onClick={dismissPhotoTitle}>Dismiss</button>
              </p>
            )}
            {photoSuggestion.description && (
              <p>
                Suggested description: <em>{photoSuggestion.description}</em>{' '}
                <button type="button" onClick={acceptPhotoDescription}>Use this description</button>{' '}
                <button type="button" className="secondary" onClick={dismissPhotoDescription}>Dismiss</button>
              </p>
            )}
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
