// The defect workspace: Defects Management and Fix & Verify collapsed into one
// screen for the roles that actually do the work. Maintenance used to land here
// from the queue and find nothing actionable — every button lived on the
// separate /fix-verify card list, which meant re-finding the same defect in an
// unfiltered list to act on it. That page is gone; this is the one place a
// defect is read and worked.
//
// Two services back this screen and they fail independently: reporting owns the
// defect (header, photos, timeline), fixverify owns the work order and proofs.
// A dead fixverify must still leave the defect readable, so the work-order card
// carries its own error state rather than blanking the page.
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import {
  Chip,
  EmptyState,
  ErrorState,
  InfoHint,
  LifecycleRail,
  SeverityChip,
  Spinner,
  StatusCell,
} from '../components/ui'
import { ageLabel, locationLabel, relativeDate, slaLabel, slaState } from '../lib/format'
import {
  categoryLabel,
  statusLabel,
  urgency as urgencyToken,
  verdict as verdictToken,
  woStatusColor,
  woStatusLabel,
} from '../lib/tokens'

const SLA_TONE = { danger: 'var(--danger)', warn: 'var(--warn)', muted: 'var(--muted-2)' }

// Mirrors the server's 409 guard in fixverify/app/main.py: these are the only
// work-order statuses that accept a proof.
const ACCEPTS_PROOF = ['open', 'in_progress', 'awaiting_proof']

export default function DefectWorkspace({ identity }) {
  const { id } = useParams()
  const [bundle, setBundle] = useState(null)
  const [issueError, setIssueError] = useState(null)
  // undefined = still loading, null = this defect has no work order yet
  const [work, setWork] = useState(undefined)
  const [workError, setWorkError] = useState(null)

  const loadIssue = useCallback(() => {
    setIssueError(null)
    api.getIssue(id).then(setBundle).catch((err) => { setBundle(null); setIssueError(err) })
  }, [id])

  const loadWork = useCallback(() => {
    setWorkError(null)
    api.workOrderForIssue(id)
      .then((row) => (row ? api.getWorkOrder(row.id) : null))
      .then(setWork)
      .catch((err) => { setWork(null); setWorkError(err) })
  }, [id])

  useEffect(() => { loadIssue() }, [loadIssue])
  useEffect(() => { loadWork() }, [loadWork])

  // Work-order actions move the issue's status server-side, so both halves have
  // to be refetched — the header would otherwise keep showing the old status.
  const refreshAll = () => { loadIssue(); loadWork() }

  if (issueError) {
    return <div className="card"><ErrorState error={issueError} onRetry={loadIssue} /></div>
  }
  if (!bundle) return <Spinner label="Loading defect…" />

  const { issue, timeline, photos } = bundle

  return (
    <div className="stack">
      <DefectHeader issue={issue} work={work} />

      <WorkOrderCard
        issue={issue}
        work={work}
        error={workError}
        identity={identity}
        onRetry={loadWork}
        onChanged={refreshAll}
      />

      {work?.proofs?.length > 0 && (
        <ProofHistory
          proofs={work.proofs}
          identity={identity}
          onChanged={refreshAll}
        />
      )}

      {photos.length > 0 && (
        <div className="card">
          <div className="card-eyebrow">Reported photos</div>
          <div className="photo-gallery" style={{ marginTop: 10 }}>
            {photos.map((photo) => (
              <a
                key={photo.id}
                href={api.issuePhotoUrl(issue.id, photo.id)}
                target="_blank"
                rel="noreferrer"
              >
                <img src={api.issuePhotoUrl(issue.id, photo.id)} alt="" />
              </a>
            ))}
          </div>
        </div>
      )}

      <Timeline events={timeline} />
    </div>
  )
}

function DefectHeader({ issue, work }) {
  const sla = slaLabel(issue)
  const { breached, daysOver } = slaState(issue)
  const urg = urgencyToken(issue.urgency)
  const repeats = issue.duplicate_count > 1 ? issue.duplicate_count : 0

  return (
    <div className="card">
      <Link to="/" style={{ fontSize: 12, color: 'var(--muted)' }}>← Defects Management</Link>

      <div
        style={{
          display: 'flex', justifyContent: 'space-between', gap: 16,
          alignItems: 'flex-start', marginTop: 10,
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div className="cell-mono">{issue.reference_no}</div>
          <h2 style={{ margin: '3px 0 0', fontSize: 18 }}>{issue.title}</h2>
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 12,
              marginTop: 10, flexWrap: 'wrap',
            }}
          >
            <StatusCell value={issue.status} />
            <SeverityChip value={issue.severity} />
            {urg && <Chip color={urg.c} background={urg.bg}>{urg.label}</Chip>}
            {/* duplicate_count >= 3 is what actually bumps severity (docs/05) */}
            {repeats > 1 && (
              <Chip color="var(--accent)" background="var(--accent-soft)">
                {repeats} reports
              </Chip>
            )}
          </div>
        </div>

        <div style={{ textAlign: 'right', flex: '0 0 auto' }}>
          <div
            style={{
              fontSize: 15, fontWeight: 600, fontFamily: 'var(--mono)', color: 'var(--text-2)',
            }}
          >
            {ageLabel(issue)}
          </div>
          <div style={{ fontSize: 11, marginTop: 3, fontWeight: 600, color: SLA_TONE[sla.tone] }}>
            {sla.text}
          </div>
        </div>
      </div>

      <p style={{ fontSize: 13.5, color: 'var(--text-2)', lineHeight: 1.55, margin: '13px 0 0' }}>
        {issue.description}
      </p>

      <p style={{ fontSize: 11.5, color: 'var(--muted-2)', margin: '9px 0 0' }}>
        {categoryLabel(issue.category)} · {locationLabel(issue)} · reported by {issue.reporter_name}
        {issue.equipment_name && ` · ${issue.equipment_name}`}
      </p>

      {/* Where this defect is in its life. Renders from the issue alone, so a
          dead fixverify costs the caption, not the rail. */}
      <div style={{ marginTop: 16, paddingTop: 15, borderTop: '1px solid var(--border-soft)' }}>
        <LifecycleRail issue={issue} work={work} />
      </div>

      {breached && (
        <div className="ai-frame" style={{ marginTop: 13 }}>
          <div style={{ padding: '9px 11px', display: 'flex', alignItems: 'center', gap: 9 }}>
            <span className="ai-dot" />
            <span style={{ fontSize: 11.5, lineHeight: 1.45, color: 'var(--muted)' }}>
              Day {Math.floor(daysOver) + 30} of a 30-day SLA, still{' '}
              {statusLabel(issue.status).toLowerCase()}.
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

function WorkOrderCard({ issue, work, error, identity, onRetry, onChanged }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  // idle | loading | ready | error — the AI suggestion, fetched only when asked
  const [rec, setRec] = useState({ status: 'idle' })
  // The proof under review: picked → checking → checked (awaiting the user's
  // call) → submitted. Nothing reaches the record until they say so.
  const [pending, setPending] = useState({ status: 'idle' })
  // Remounts the file input so it clears its filename after a submit or a
  // discard — and so re-picking the same file still fires onChange.
  const [fileKey, setFileKey] = useState(0)

  const wo = work?.work_order
  const isAdmin = identity.role === 'admin'
  // Proof is attributed to the assignee, so a work order nobody has claimed
  // cannot receive one — you acknowledge the defect first.
  const claimed = Boolean(wo?.assignee)

  // Fixverify caches the answer per work order, so a repeat ask is cheap — but
  // the first one is a live LLM call, which is why nothing fetches on hover.
  useEffect(() => { setRec({ status: 'idle' }) }, [wo?.id])

  const suggest = () => {
    setRec({ status: 'loading' })
    api.evidenceRecommendation(wo.id)
      .then((data) => setRec({ status: 'ready', data }))
      // This endpoint calls reporting synchronously, so it 500s when reporting
      // is down. Say so rather than leaving the button looking inert.
      .catch(() => setRec({ status: 'error' }))
  }

  const start = async () => {
    setBusy(true)
    try { await api.startWorkOrder(wo.id, identity.user); onChanged() } finally { setBusy(false) }
  }

  // Picking a file runs the AI check straight away, but only stages the proof —
  // the work order and the issue do not move until the user submits it.
  const check = async (picked) => {
    if (!picked) return
    // Replacing a file mid-review: the previous staged proof is now orphaned.
    if (pending.proof) api.discardProof(pending.proof.id).catch(() => {})
    setPending({ status: 'checking', name: picked.name })
    try {
      const proof = await api.stageProof(wo.id, picked, note)
      setPending({ status: 'checked', proof, name: picked.name })
    } catch (err) {
      setPending({ status: 'error', error: err, name: picked.name })
    }
  }

  const submit = async () => {
    setBusy(true)
    try {
      await api.submitProof(pending.proof.id, note)
      setPending({ status: 'idle' })
      setNote('')
      setFileKey((k) => k + 1)
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    const staged = pending.proof
    setPending({ status: 'idle' })
    setFileKey((k) => k + 1)
    if (staged) await api.discardProof(staged.id).catch(() => {})
  }

  return (
    <div className="card">
      <div className="card-eyebrow">Work order</div>

      {error && <ErrorState error={error} onRetry={onRetry} />}
      {!error && work === undefined && <Spinner label="Loading the work order…" />}
      {!error && work === null && (
        <EmptyState
          title="No work order yet"
          hint={
            issue.status === 'cancelled'
              ? 'This defect was cancelled before it reached maintenance.'
              : 'One is created automatically when the defect is triaged.'
          }
        />
      )}

      {wo && (
        <>
          <div
            style={{
              display: 'flex', alignItems: 'center', gap: 12,
              flexWrap: 'wrap', margin: '11px 0 0',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
              <span className="status-dot" style={{ background: woStatusColor(wo.status) }} />
              <span style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
                {woStatusLabel(wo.status)}
              </span>
            </div>
            <span style={{ fontSize: 11.5, color: 'var(--muted-2)' }}>
              {wo.assignee ? `assigned to ${wo.assignee}` : 'unassigned'}
              {wo.started_at && ` · started ${relativeDate(wo.started_at)}`}
              {wo.completed_at && ` · signed off ${relativeDate(wo.completed_at)}`}
            </span>
            {wo.resolved_on_arrival && (
              <Chip color="var(--ok)" background="var(--ok-soft)">Resolved on arrival</Chip>
            )}
          </div>

          {isAdmin && (
            <p className="hint" style={{ marginTop: 12 }}>
              Maintenance starts the work and uploads proof. Your sign-off is on the
              proofs below.
            </p>
          )}

          {!isAdmin && ACCEPTS_PROOF.includes(wo.status) && !claimed && (
            <>
              <div style={{ marginTop: 13 }}>
                <button disabled={busy} onClick={start}>Start work</button>
              </div>
              <p className="hint" style={{ marginTop: 9 }}>
                Acknowledge this defect before uploading anything — proof of work is
                attributed to whoever the work order is assigned to. If it was already
                resolved when you arrived, start work and upload proof of the resolved
                state.
              </p>
            </>
          )}

          {!isAdmin && ACCEPTS_PROOF.includes(wo.status) && claimed && (
            <>
              {wo.status === 'awaiting_proof' && (
                <p className="hint" style={{ marginTop: 11 }}>
                  The last proof was not accepted. Upload a replacement below.
                </p>
              )}

              <div
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  justifyContent: 'space-between', margin: '15px 0 0',
                }}
              >
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <label style={{ margin: 0 }} htmlFor="proof-file">Proof of work</label>
                  <InfoHint label="What counts as proof of work?">
                    <span style={{ display: 'block', fontSize: 12, lineHeight: 1.5 }}>
                      Upload whatever shows the defect is fixed — a photo of the repair,
                      a replaced part, a meter reading, a voice note.
                    </span>
                    <span
                      style={{
                        display: 'block', fontSize: 12, lineHeight: 1.5,
                        marginTop: 8, color: 'var(--muted)',
                      }}
                    >
                      Not sure for this defect? Use <strong>Suggest what to upload</strong>{' '}
                      and an AI will propose what to capture. It is only ever a
                      suggestion — upload what you have.
                    </span>
                  </InfoHint>
                </span>
                <button className="linkish" disabled={rec.status === 'loading'} onClick={suggest}>
                  {rec.status === 'loading' ? 'Asking…' : 'Suggest what to upload'}
                </button>
              </div>

              {rec.status === 'error' && (
                <p className="hint" style={{ marginTop: 8 }}>
                  Could not fetch a suggestion. Upload what you have — it was only ever
                  advisory.
                </p>
              )}

              {rec.status === 'ready' && (
                <div className="ai-frame" style={{ margin: '10px 0 4px' }}>
                  <div style={{ padding: '11px 13px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span className="ai-dot" />
                      <span className="card-eyebrow">Suggested evidence</span>
                    </div>
                    {rec.data.recommended?.map((item, i) => (
                      <div key={i} style={{ fontSize: 12.5, marginTop: 8, lineHeight: 1.5 }}>
                        <strong>{item.what}</strong>{' '}
                        <span style={{ color: 'var(--muted-2)' }}>({item.media_type})</span>
                        <div style={{ fontSize: 11.5, color: 'var(--muted-2)' }}>{item.why}</div>
                      </div>
                    ))}
                    <div style={{ fontSize: 11.5, color: 'var(--muted-2)', marginTop: 9 }}>
                      {rec.data.rationale} A suggestion only — upload what you have.
                    </div>
                  </div>
                </div>
              )}

              {/* The note goes above the file because picking a file runs the
                  check immediately, and the model is given the note as context. */}
              <input
                placeholder="Note (optional) — what are we looking at?"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <input
                key={fileKey}
                id="proof-file"
                type="file"
                accept="image/*,audio/*,video/*"
                onChange={(e) => check(e.target.files[0] || null)}
              />

              {pending.status === 'checking' && (
                <p className="hint" style={{ marginTop: 10 }}>
                  <span
                    className="spinner"
                    style={{ width: 12, height: 12, marginRight: 7, verticalAlign: 'middle' }}
                  />
                  Checking {pending.name} against this defect…
                </p>
              )}

              {pending.status === 'error' && (
                <p className="hint" style={{ marginTop: 10 }}>
                  Could not check {pending.name} ({pending.error.message}). Pick the file
                  again to retry.
                </p>
              )}

              {pending.status === 'checked' && (
                <ProofReview proof={pending.proof} busy={busy} onUse={submit} onDiscard={discard} />
              )}
            </>
          )}

          {!isAdmin && !ACCEPTS_PROOF.includes(wo.status) && (
            <p className="hint" style={{ marginTop: 12 }}>
              {wo.status === 'pending_human_verification'
                ? 'Proof uploaded — waiting on admin sign-off. Nothing to do here.'
                : 'This work order is closed out.'}
            </p>
          )}
        </>
      )}
    </div>
  )
}

/** How loudly to warn on an `irrelevant` verdict. Mirrors nothing server-side —
 *  the AI no longer blocks, so this only picks the wording. */
const CONFIDENT = 0.8

/**
 * The AI's read on a staged proof, and the two buttons that make it the
 * uploader's decision rather than the model's. `irrelevant` is a warning, not
 * a wall: they can still submit, and admin sign-off is the real gate.
 */
function ProofReview({ proof, busy, onUse, onDiscard }) {
  const token = verdictToken(proof.ai_verdict)
  const unrelated = proof.ai_verdict === 'irrelevant'
  const confident = unrelated && (proof.ai_confidence ?? 0) >= CONFIDENT

  return (
    <div className="ai-frame" style={{ margin: '11px 0 4px' }}>
      <div style={{ padding: '12px 14px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <span className="ai-dot" />
          <span className="card-eyebrow">AI relevance check</span>
          <Chip color={token.c} background={token.bg}>{token.label}</Chip>
          {proof.ai_confidence > 0 && (
            <span style={{ fontSize: 11, color: 'var(--muted-2)' }}>
              {Math.round(proof.ai_confidence * 100)}% confident
            </span>
          )}
        </div>

        {proof.ai_reason && (
          <p style={{ fontSize: 12.5, lineHeight: 1.5, margin: '9px 0 0', color: 'var(--text-2)' }}>
            {proof.ai_reason}
          </p>
        )}

        <p style={{ fontSize: 11.5, lineHeight: 1.5, margin: '9px 0 0', color: 'var(--muted-2)' }}>
          {confident
            ? 'This looks unrelated to the defect. You can still submit it — an admin makes the final call.'
            : unrelated
              ? 'The model was unsure and leaned unrelated. Your call.'
              : 'Nothing is recorded until you submit it.'}
        </p>

        <div style={{ display: 'flex', gap: 8, marginTop: 13, flexWrap: 'wrap' }}>
          <button disabled={busy} onClick={onUse}>
            {busy ? 'Submitting…' : unrelated ? 'Submit anyway' : 'Use this proof'}
          </button>
          <button className="ghost" disabled={busy} onClick={onDiscard}>
            Choose another file
          </button>
        </div>
      </div>
    </div>
  )
}

function ProofHistory({ proofs, identity, onChanged }) {
  const [rejecting, setRejecting] = useState(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const isAdmin = identity.role === 'admin'

  const verify = async (proofId, approved, notes = '') => {
    setBusy(true)
    try {
      await api.humanVerify(proofId, approved, notes)
      setRejecting(null)
      setReason('')
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="table-card">
      <div className="table-head">
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>Proof of work</div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          {proofs.length} upload{proofs.length === 1 ? '' : 's'}
        </div>
      </div>

      <div className="table-scroll">
        <div className="grid-row grid-header proof-grid">
          <div>File</div><div>Note</div><div>AI check</div><div>Sign-off</div><div />
        </div>

        {proofs.map((proof) => {
          const ai = verdictToken(proof.ai_verdict)
          const human = proof.human_verdict ? verdictToken(proof.human_verdict) : null
          // Every submitted proof is judgeable, including one the uploader put
          // forward over an `irrelevant` verdict — that override is exactly the
          // case admin sign-off exists to catch. Excluding it here would strand
          // the work order at pending_human_verification with no way out.
          const canVerify = isAdmin && !proof.human_verdict

          return (
            <div key={proof.id}>
              <div className="grid-row grid-body proof-grid">
                <div style={{ minWidth: 0 }}>
                  <a href={api.proofFileUrl(proof.id)} target="_blank" rel="noreferrer">
                    View {proof.media_type}
                  </a>
                  <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 3 }}>
                    {proof.uploaded_by} · {relativeDate(proof.created_at)}
                  </div>
                </div>

                <div style={{ fontSize: 12, color: 'var(--muted)', minWidth: 0 }}>
                  {proof.note || '—'}
                </div>

                <div style={{ minWidth: 0 }}>
                  <Chip color={ai.c} background={ai.bg}>{ai.label}</Chip>
                  {proof.ai_reason && (
                    <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 4 }}>
                      {proof.ai_reason}
                    </div>
                  )}
                </div>

                <div style={{ minWidth: 0 }}>
                  {human ? (
                    <>
                      <Chip color={human.c} background={human.bg}>{human.label}</Chip>
                      {proof.human_verifier && (
                        <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 4 }}>
                          by {proof.human_verifier}
                        </div>
                      )}
                      {proof.human_notes && (
                        <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 2 }}>
                          {proof.human_notes}
                        </div>
                      )}
                    </>
                  ) : (
                    <span style={{ fontSize: 12, color: 'var(--muted-2)' }}>—</span>
                  )}
                </div>

                <div>
                  {canVerify && (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button disabled={busy} onClick={() => verify(proof.id, true)}>
                        Approve
                      </button>
                      <button
                        className="secondary"
                        disabled={busy}
                        onClick={() => { setRejecting(proof.id); setReason('') }}
                      >
                        Reject
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {rejecting === proof.id && (
                <div
                  style={{
                    padding: '12px 17px', background: 'var(--row-hover)',
                    borderBottom: '1px solid var(--border-soft)',
                  }}
                >
                  <label>Why is this proof not acceptable?</label>
                  <textarea
                    rows={2}
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="The maintenance user sees this and re-uploads."
                  />
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button disabled={busy} onClick={() => verify(proof.id, false, reason)}>
                      Reject proof
                    </button>
                    <button className="ghost" disabled={busy} onClick={() => setRejecting(null)}>
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/** `IssueEvent.detail` is a JSON string, and status rows carry their enum in
 *  the event type — both need unpacking before they read as prose. */
function eventLabel(event) {
  if (event.event_type.startsWith('status:')) {
    return `Status → ${statusLabel(event.event_type.slice(7))}`
  }
  return event.event_type.replaceAll('_', ' ')
}

function eventDetail(event) {
  if (!event.detail) return ''
  try {
    const parsed = JSON.parse(event.detail)
    return typeof parsed === 'string' ? parsed : parsed.detail || ''
  } catch {
    return event.detail
  }
}

function Timeline({ events }) {
  return (
    <div className="table-card">
      <div className="table-head">
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>History</div>
      </div>
      <div className="table-scroll">
        <div className="grid-row grid-header timeline-grid">
          <div>When</div><div>Event</div><div>Detail</div><div>Actor</div>
        </div>
        {events.length === 0 && <EmptyState title="Nothing recorded yet" />}
        {events.map((event) => (
          <div key={event.id} className="grid-row grid-body timeline-grid">
            <div style={{ fontSize: 11.5, color: 'var(--muted-2)' }}>
              {relativeDate(event.created_at)}
            </div>
            <div style={{ fontSize: 12.5, color: 'var(--text-2)' }}>{eventLabel(event)}</div>
            <div style={{ fontSize: 12, color: 'var(--muted)', minWidth: 0 }}>
              {eventDetail(event) || '—'}
            </div>
            <div className="cell-truncate" style={{ fontSize: 11.5, color: 'var(--muted-2)' }}>
              {event.actor}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
