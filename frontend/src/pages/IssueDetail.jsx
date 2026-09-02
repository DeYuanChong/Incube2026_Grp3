// Defect detail, ported from the CPS Defects Portal v2 canvas mock's DETAIL
// screen: a header card with a stat strip, then Submission / Triage / Fix &
// verify down the left and the timeline rail down the right.
//
// The mock's MTBF, MTTR and Repeats/90d tiles are deliberately absent. They are
// per-asset numbers, and `equipment_name` is blank on 2,173 of the 2,182 rows
// in raw_data/ — exactly one asset in fourteen months clears MTBF's two-failure
// bar. docs/05-triage-analytics.md:78 records the same finding. The mock's
// "Remind vendor" and "Estimated fix" are absent for the same reason: nothing
// produces them. Every control on this page maps to a live endpoint.
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, getIdentity } from '../api'
import { Chip, EmptyState, ErrorState, SeverityChip, Spinner } from '../components/ui'
import {
  SLA_BREACH_DAYS,
  ageLabel,
  locationLabel,
  relativeDate,
  slaLabel,
} from '../lib/format'
import {
  EVENT_DOT,
  STATUS_COLOR,
  categoryLabel,
  eventLabel,
  eventTone,
  statusLabel,
  workOrderLabel,
} from '../lib/tokens'

// Mirrors services/triage/app/config.py. Only used to word the badge — the
// server decides the bump; this side just explains one that already happened.
const DUPLICATE_BUMP_THRESHOLD = 3
const DUPLICATE_WINDOW_DAYS = 14

const TIMELINE_COLLAPSED = 3
const SLA_TONE = { danger: 'var(--danger)', warn: 'var(--warn)', muted: 'var(--muted-2)' }

export default function IssueDetail() {
  const { id } = useParams()
  const { user, role } = getIdentity()

  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [triage, setTriage] = useState(null)
  const [workOrder, setWorkOrder] = useState(null)
  const [proofs, setProofs] = useState([])
  const [recommendation, setRecommendation] = useState(null)
  const [dismissed, setDismissed] = useState({})
  const [timelineOpen, setTimelineOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')

  // Three independent loads. Only the issue is fatal — a dead triage or
  // fixverify service empties its own card and leaves the rest of the page
  // standing, the same way Dashboard treats its two fetches.
  const loadIssue = useCallback(
    () => api.getIssue(id).then((d) => { setData(d); setError(null) }).catch(setError),
    [id],
  )
  const loadTriage = useCallback(
    () => api.triageResult(id).then(setTriage).catch(() => setTriage(null)),
    [id],
  )
  const loadWork = useCallback(
    () =>
      api.listWorkOrders({ issue_id: id })
        .then((list) => {
          const wo = list[0] || null
          setWorkOrder(wo)
          if (!wo) { setProofs([]); setRecommendation(null); return }
          api.getWorkOrder(wo.id).then((d) => setProofs(d.proofs || [])).catch(() => setProofs([]))
          api.evidenceRecommendation(wo.id).then(setRecommendation).catch(() => setRecommendation(null))
        })
        .catch(() => setWorkOrder(null)),
    [id],
  )

  const refresh = useCallback(() => {
    loadIssue(); loadTriage(); loadWork()
  }, [loadIssue, loadTriage, loadWork])

  useEffect(() => { refresh() }, [refresh])

  /** Every mutating control goes through here, so a 409 from the state machine
   *  surfaces as a message instead of a silent no-op. */
  const run = async (fn) => {
    setBusy(true)
    setActionError('')
    try {
      await fn()
      refresh()
    } catch (err) {
      setActionError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (error) return <div className="detail-card"><ErrorState error={error} onRetry={refresh} /></div>
  if (!data) return <Spinner label="Loading defect…" />

  const { issue, timeline, photos } = data
  const sla = slaLabel(issue)
  const repeats = issue.duplicate_count > 1 ? issue.duplicate_count : 0
  const bumped = issue.duplicate_count >= DUPLICATE_BUMP_THRESHOLD

  // Closing is offered only while it is still an open question. Once the issue
  // is closed or cancelled there is no transition left (models.py:TRANSITIONS
  // gives both an empty set), so the control disappears rather than sitting
  // there disabled explaining a wait that will never end.
  const settledForGood = ['closed', 'cancelled'].includes(issue.status)
  const canClose = issue.status === 'verified'
  const showClose = role !== 'maintenance' && !settledForGood
  const canStart = workOrder && ['open', 'rejected'].includes(workOrder.status)

  return (
    <div className="stack">
      <Link to="/" className="back-link">← All defects</Link>

      <div className="detail-card">
        <div className="detail-head">
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
              <span style={{ fontFamily: 'var(--mono)', fontSize: 12.5, color: 'var(--muted)' }}>
                {issue.reference_no}
              </span>
              <SeverityChip value={issue.severity} />
              {bumped && (
                <span
                  style={{
                    fontSize: 11, fontWeight: 600, color: 'var(--accent)',
                    background: 'var(--accent-soft)', borderRadius: 6, padding: '3px 7px',
                  }}
                >
                  ▲ severity bumped · {issue.duplicate_count} reporters in{' '}
                  {DUPLICATE_WINDOW_DAYS} days
                </span>
              )}
            </div>

            <h2 className="detail-title">{issue.title}</h2>
            {/* ageLabel, not relativeDate: the stat strip below and the
                Dashboard's Age column both floor the age, and rounding here
                would state the same fact as a different number. */}
            <div className="detail-meta">
              {categoryLabel(issue.category)} · {locationLabel(issue)} · reported{' '}
              {ageLabel(issue)} ago by {issue.reporter_name}
            </div>
          </div>

          <div className="detail-actions">
            {role === 'admin' && (
              <button className="ghost" disabled={busy} onClick={() => run(() => api.runTriage(issue.id))}>
                {triage ? 'Re-run AI triage' : 'Run AI triage'}
              </button>
            )}
            {role === 'admin' && triage && !triage.admin_confirmed && (
              <button className="secondary" disabled={busy} onClick={() => run(() => api.confirmTriage(issue.id, {}))}>
                Confirm triage
              </button>
            )}
            {role === 'maintenance' && canStart && (
              <button disabled={busy} onClick={() => run(() => api.startWorkOrder(workOrder.id, user))}>
                Start work
              </button>
            )}
            {showClose && (
              <button
                className="gradient"
                disabled={!canClose || busy}
                title={canClose ? undefined : 'Only a verified defect can be closed'}
                onClick={() => run(() => api.closeIssue(issue.id, { closed_by: role === 'admin' ? 'admin' : 'reporter' }))}
              >
                Close issue
              </button>
            )}
          </div>
        </div>

        {/* Why the close button is dark, stated rather than left to the tooltip */}
        {showClose && !canClose && (
          <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 8, textAlign: 'right' }}>
            Closing unlocks once the fix is verified — currently{' '}
            {statusLabel(issue.status).toLowerCase()}.
          </div>
        )}
        {actionError && (
          <p className="error" style={{ marginTop: 10 }}>{actionError}</p>
        )}

        <div className="stat-strip">
          <Stat
            label="Status"
            value={statusLabel(issue.status)}
            valueColor={STATUS_COLOR[issue.status]}
            note={workOrder?.assignee || (workOrder ? 'unassigned' : 'no work order yet')}
          />
          <Stat
            label="SLA"
            mono
            value={sla.text}
            valueColor={SLA_TONE[sla.tone]}
            note={`${SLA_BREACH_DAYS}-day target`}
          />
          <Stat
            label="Urgency"
            value={issue.urgency ? issue.urgency.replace('_', ' ') : '—'}
            note={issue.urgency ? 'set by triage' : 'not triaged yet'}
          />
          <Stat
            label="Reported"
            mono
            value={ageLabel(issue)}
            note={repeats > 1 ? `${repeats} reports of this defect` : 'single report'}
          />
        </div>
      </div>

      <div className="detail-grid">
        <div className="detail-col">
          <Submission
            issue={issue}
            photos={photos}
            dismissed={dismissed}
            onDismiss={(field) => setDismissed({ ...dismissed, [field]: true })}
            onAccept={(fn) => run(fn)}
            busy={busy}
          />
          <Triage issue={issue} triage={triage} />
          <FixVerify
            workOrder={workOrder}
            proofs={proofs}
            recommendation={recommendation}
            role={role}
            busy={busy}
            onVerify={(proofId, approved, notes) => run(() => api.humanVerify(proofId, approved, notes))}
          />
        </div>

        <div className="detail-col">
          <Timeline events={timeline} open={timelineOpen} onToggle={() => setTimelineOpen((v) => !v)} />
        </div>
      </div>
    </div>
  )
}

function Stat({ label, value, note, valueColor, mono }) {
  return (
    <div>
      <div className="stat-label">{label}</div>
      <div className={`stat-value${mono ? ' mono' : ''}`} style={{ color: valueColor }}>{value}</div>
      <div className="stat-note">{note}</div>
    </div>
  )
}

function Field({ label, value }) {
  return (
    <div>
      <div className="field-label">{label}</div>
      <div className="field-box">{value || '—'}</div>
    </div>
  )
}

/** An AI-derived value: the mock's gradient hairline around it, the "AI" mark
 *  on the label, and the model's reasoning underneath. */
function AiField({ label, value, meta, hint }) {
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 5 }}>
        <span className="field-label" style={{ marginBottom: 0 }}>{label}</span>
        <span className="ai-text" style={{ fontSize: 9.5, letterSpacing: '0.06em' }}>AI</span>
      </div>
      <div className="ai-value">
        <div>
          <span className="ai-value-text">{value}</span>
          {meta && <span className="ai-value-meta">{meta}</span>}
        </div>
      </div>
      {hint && <div className="field-hint">{hint}</div>}
    </div>
  )
}

function Submission({ issue, photos, dismissed, onDismiss, onAccept, busy }) {
  // A suggestion is live only while it still disagrees with what is stored and
  // the reporter has not already taken it.
  const suggestsCategory =
    issue.ai_suggested_category &&
    issue.ai_suggested_category !== issue.category &&
    issue.category_source === 'user'

  return (
    <div className="detail-card">
      <h3>Submission</h3>

      <div className="field-grid">
        <Field label="Category" value={categoryLabel(issue.category)} />
        <Field label="Mobile number" value={issue.mobile_number} />
        <Field label="Location" value={`${issue.building} / ${issue.floor}`} />
        <Field label="Room" value={issue.room} />
      </div>

      <div className="field-label" style={{ margin: '14px 0 5px' }}>Describe more</div>
      <div className="field-box tall">{issue.description}</div>

      {suggestsCategory && !dismissed.category && (
        <Suggestion
          busy={busy}
          onAccept={() => onAccept(() => api.acceptSuggestedCategory(issue.id))}
          onDismiss={() => onDismiss('category')}
          acceptLabel="Recategorise"
          dismissLabel="Keep my category"
        >
          Based on the photo this looks like{' '}
          <strong>{categoryLabel(issue.ai_suggested_category)}</strong> rather than{' '}
          <strong>{categoryLabel(issue.category)}</strong>.
        </Suggestion>
      )}
      {issue.ai_suggested_title && !dismissed.title && (
        <Suggestion
          busy={busy}
          onAccept={() => onAccept(() => api.acceptSuggestedTitle(issue.id))}
          onDismiss={() => onDismiss('title')}
          acceptLabel="Use this title"
          dismissLabel="Keep mine"
        >
          The photo suggests a different title: <strong>{issue.ai_suggested_title}</strong>
        </Suggestion>
      )}
      {issue.ai_suggested_description && !dismissed.description && (
        <Suggestion
          busy={busy}
          onAccept={() => onAccept(() => api.acceptSuggestedDescription(issue.id))}
          onDismiss={() => onDismiss('description')}
          acceptLabel="Use this description"
          dismissLabel="Keep mine"
        >
          The photo suggests a different description: <em>{issue.ai_suggested_description}</em>
        </Suggestion>
      )}
      {issue.photo_note && <div className="field-hint" style={{ marginTop: 10 }}>{issue.photo_note}</div>}

      {photos.length > 0 && (
        <div className="photo-tiles">
          {photos.map((p) => (
            <a
              key={p.id}
              className="photo-tile"
              href={api.issuePhotoUrl(issue.id, p.id)}
              target="_blank"
              rel="noreferrer"
              title={p.ai_reason || undefined}
            >
              <img src={api.issuePhotoUrl(issue.id, p.id)} alt="" />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function Suggestion({ children, onAccept, onDismiss, acceptLabel, dismissLabel, busy }) {
  return (
    <div className="ai-frame" style={{ marginTop: 12 }}>
      <div style={{ padding: '12px 13px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span className="ai-dot" />
          <span className="ai-text" style={{ fontSize: 11.5 }}>Suggested from the photo</span>
        </div>
        <div style={{ fontSize: 12, lineHeight: 1.55, color: 'var(--text-2)' }}>{children}</div>
        <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
          <button disabled={busy} onClick={onAccept}>{acceptLabel}</button>
          <button className="ghost" disabled={busy} onClick={onDismiss}>{dismissLabel}</button>
        </div>
      </div>
    </div>
  )
}

function Triage({ issue, triage }) {
  if (!triage) {
    return (
      <div className="detail-card">
        <h3>Triage</h3>
        <EmptyState
          title="Not triaged yet"
          hint="Triage runs automatically when the issue is reported. An admin can start it from the button above."
        />
      </div>
    )
  }

  const systemic = triage.systemic_payload
  const overridden = triage.admin_override_severity && triage.admin_override_severity !== triage.suggested_severity

  return (
    <div className="detail-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 13 }}>
        <h3 style={{ margin: 0 }}>Triage</h3>
        <div style={{ fontSize: 11, color: 'var(--muted-2)' }}>
          {triage.admin_confirmed ? 'Confirmed by an admin' : 'AI suggestion — not yet confirmed'}
        </div>
      </div>

      <div className="field-grid">
        <AiField
          label="Severity"
          value={triage.suggested_severity}
          meta={overridden ? `admin set ${triage.admin_override_severity}` : undefined}
          hint={triage.severity_rationale}
        />
        <AiField
          label="Urgency"
          value={triage.suggested_urgency}
          meta={triage.admin_override_urgency ? `admin set ${triage.admin_override_urgency}` : undefined}
          hint="Derived from the category, the description and any emergency keywords."
        />
        <AiField
          label="Equipment"
          value={triage.equipment_extracted || 'none identified'}
          hint="Extracted from the description. Blank where the report names no specific asset."
        />
        <AiField
          label="Duplicate of"
          value={
            triage.duplicate_of_issue_id
              ? <Link to={`/issues/${triage.duplicate_of_issue_id}`}>View the original report</Link>
              : 'No earlier match'
          }
          meta={
            triage.duplicate_confidence
              ? `${Math.round(triage.duplicate_confidence * 100)}% confident`
              : undefined
          }
          hint={`Matched against open reports from the last ${DUPLICATE_WINDOW_DAYS} days.`}
        />
      </div>

      {systemic && (
        <div className="ai-frame" style={{ marginTop: 14 }}>
          <div style={{ padding: '12px 13px' }}>
            <div className="ai-text" style={{ fontSize: 11.5, marginBottom: 5 }}>
              Systemic fault — {systemic.issue_count} issues in {systemic.window_days} days
            </div>
            <div style={{ fontSize: 12, lineHeight: 1.55, color: 'var(--text-2)' }}>
              {systemic.recommendation}
            </div>
            {systemic.issues?.length > 0 && (
              <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {systemic.issues.map((member) => (
                  <Link
                    key={member.issue_id}
                    to={`/issues/${member.issue_id}`}
                    className="chip"
                    style={{
                      background: 'var(--accent-soft)',
                      color: member.issue_id === issue.id ? 'var(--accent-deep)' : 'var(--accent)',
                      fontWeight: member.issue_id === issue.id ? 700 : 600,
                    }}
                  >
                    {member.reference_no}
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

/** Icon, colour and wording for one proof. The human verdict wins where it
 *  exists — an admin's decision supersedes the model's. */
function proofState(proof) {
  if (proof.human_verdict === 'approved') {
    return { icon: '✓', label: 'Approved', c: 'var(--ok)', bg: 'var(--ok-soft)' }
  }
  if (proof.human_verdict === 'rejected') {
    return { icon: '✕', label: 'Rejected', c: 'var(--danger)', bg: 'var(--danger-soft)' }
  }
  if (proof.ai_verdict === 'irrelevant') {
    return { icon: '✕', label: 'AI: irrelevant', c: 'var(--danger)', bg: 'var(--danger-soft)' }
  }
  if (proof.ai_verdict === 'relevant') {
    return { icon: '◎', label: 'Awaiting sign-off', c: 'var(--accent)', bg: 'var(--accent-soft)' }
  }
  return { icon: '◎', label: 'Inconclusive', c: '#b07a0c', bg: '#fdf6e3' }
}

function FixVerify({ workOrder, proofs, recommendation, role, busy, onVerify }) {
  return (
    <div className="detail-card">
      <h3 style={{ marginBottom: 4 }}>Fix &amp; verify</h3>
      <div style={{ fontSize: 11.5, color: 'var(--muted-2)', marginBottom: 13 }}>
        First-cut verification from the vendor's proof, then CPS sign-off.
      </div>

      {!workOrder ? (
        <EmptyState
          title="No work order yet"
          hint="One is created automatically when the issue is triaged."
        />
      ) : (
        <>
          <div className="verify-row" style={{ marginBottom: 10 }}>
            <span
              className="verify-icon"
              style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
            >
              ⚑
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 12.5, fontWeight: 500 }}>
                {workOrderLabel(workOrder.status)}
              </div>
              <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 2 }}>
                {workOrder.assignee ? `Assigned to ${workOrder.assignee}` : 'Unassigned'}
                {workOrder.resolved_on_arrival && ' · resolved on arrival'}
                {workOrder.is_temporary_fix && ' · temporary fix'}
              </div>
            </div>
            {workOrder.requires_human_verification && (
              <Chip color="var(--accent)" background="var(--accent-soft)">Sign-off required</Chip>
            )}
          </div>

          {proofs.length === 0 ? (
            <div className="field-hint">
              No proof uploaded yet. Maintenance uploads it from Fix &amp; Verify.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {proofs.map((proof) => {
                const state = proofState(proof)
                const canJudge =
                  role === 'admin' && !proof.human_verdict && proof.ai_verdict !== 'irrelevant'
                return (
                  <div key={proof.id} className="verify-row">
                    <span className="verify-icon" style={{ background: state.bg, color: state.c }}>
                      {state.icon}
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 12.5, fontWeight: 500 }}>
                        <a href={api.proofFileUrl(proof.id)} target="_blank" rel="noreferrer">
                          {proof.note || `${proof.media_type} proof`}
                        </a>
                      </div>
                      <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 2 }}>
                        by {proof.uploaded_by}
                        {proof.ai_reason && ` · ${proof.ai_reason}`}
                        {proof.human_notes && ` · ${proof.human_notes}`}
                      </div>
                    </div>
                    {canJudge ? (
                      <div style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
                        <button disabled={busy} onClick={() => onVerify(proof.id, true, '')}>
                          Approve
                        </button>
                        <button
                          className="ghost"
                          disabled={busy}
                          onClick={() => {
                            const notes = window.prompt('Reason for rejection?') || ''
                            onVerify(proof.id, false, notes)
                          }}
                        >
                          Reject
                        </button>
                      </div>
                    ) : (
                      <Chip color={state.c} background={state.bg}>{state.label}</Chip>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          {recommendation?.recommended?.length > 0 && (
            <div className="ai-frame" style={{ marginTop: 13 }}>
              <div style={{ padding: '12px 13px' }}>
                <div className="ai-text" style={{ fontSize: 11.5, marginBottom: 5 }}>
                  Proof recommendation
                </div>
                <div style={{ fontSize: 12, lineHeight: 1.55, color: 'var(--text-2)' }}>
                  {recommendation.recommended.map((r, i) => (
                    <div key={i} style={{ marginBottom: 4 }}>
                      <strong>{r.what}</strong> ({r.media_type}) —{' '}
                      <span style={{ color: 'var(--muted-2)' }}>{r.why}</span>
                    </div>
                  ))}
                  {recommendation.rationale && (
                    <div style={{ color: 'var(--muted-2)', marginTop: 6 }}>
                      {recommendation.rationale}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

// An unrecognised event's blob is summarised, not dumped: the import writes
// twelve raw CSV columns into `detail`, and rendering all of them puts source
// column names and the requestor's name into the UI.
const MAX_GENERIC_DETAIL_PAIRS = 3

/** The `detail` column is a JSON blob whose keys differ per event type. Named
 *  cases get prose; anything else degrades to `key: value` rather than being
 *  dropped, so an event added server-side still says something here. */
function eventNote(event) {
  let detail
  try {
    detail = JSON.parse(event.detail || '{}')
  } catch {
    return ''
  }
  if (!detail || typeof detail !== 'object') return ''

  switch (event.event_type) {
    case 'created':
      return detail.category ? `Reported as ${categoryLabel(detail.category)}` : ''
    case 'triaged':
      return [detail.severity, detail.urgency].filter(Boolean).join(' · ')
    case 'closed':
      return detail.closed_by ? `Closed by ${detail.closed_by}` : ''
    case 'cancelled':
      return detail.reason || ''
    case 'photo_uploaded':
      return detail.verdict ? `Photo check: ${detail.verdict}` : ''
    case 'category_accepted':
      return detail.category ? `Now ${categoryLabel(detail.category)}` : ''
    case 'imported':
      // The source reference is the one field worth surfacing — it traces the
      // row back to ITeFM. The rest of the blob is raw export columns.
      return detail.source_reference_no ? `Source ref ${detail.source_reference_no}` : ''
    default:
      break
  }
  if (event.event_type.startsWith('status:')) return detail.detail || ''
  return Object.entries(detail)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .slice(0, MAX_GENERIC_DETAIL_PAIRS)
    .map(([k, v]) => `${k.replaceAll('_', ' ')}: ${v}`)
    .join(' · ')
}

function Timeline({ events, open, onToggle }) {
  // The server returns oldest-first. Collapsed shows the most recent few, and
  // the rail always reads newest at the top.
  const shown = (open ? events : events.slice(-TIMELINE_COLLAPSED)).slice().reverse()
  const hidden = events.length - shown.length

  return (
    <div className="detail-card">
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 10, marginBottom: 13 }}>
        <h3 style={{ margin: 0 }}>Timeline</h3>
        {(hidden > 0 || open) && (
          <button className="linkish" onClick={onToggle}>
            {open ? 'Show less' : `View ${hidden} earlier update${hidden === 1 ? '' : 's'}`}
          </button>
        )}
      </div>

      {events.length === 0 ? (
        <EmptyState title="Nothing recorded yet" />
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {shown.map((event, i) => {
            const tone = eventTone(event.event_type)
            const note = eventNote(event)
            return (
              <div key={event.id} className="timeline-row">
                <div className="timeline-gutter">
                  <span className="timeline-dot" style={{ background: EVENT_DOT[tone] }} />
                  <span
                    className="timeline-line"
                    style={{ background: i === shown.length - 1 ? 'transparent' : 'var(--border)' }}
                  />
                </div>
                <div className="timeline-body">
                  <div className="timeline-label">{eventLabel(event.event_type)}</div>
                  <div className="timeline-when">
                    {relativeDate(event.created_at)} · {event.actor}
                  </div>
                  {note && (
                    <div
                      className="timeline-note"
                      style={{ color: tone === 'ai' ? 'var(--accent)' : 'var(--muted)' }}
                    >
                      {note}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
