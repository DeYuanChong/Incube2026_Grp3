import { useCallback, useEffect, useState } from 'react'
import { api, getIdentity } from '../api'
import { Chip, EmptyState, ErrorState, Spinner } from '../components/ui'
import { proofState, workOrderLabel } from '../lib/tokens'

function WorkOrderCard({ wo, onChanged }) {
  const [detail, setDetail] = useState(null)
  const [recommendation, setRecommendation] = useState(null)
  const [file, setFile] = useState(null)
  const [note, setNote] = useState('')
  // The draft proof awaiting the uploader's confirm/cancel, if any. A draft
  // left behind (tab closed before confirming) is picked back up on load.
  const [pendingProof, setPendingProof] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState('')
  const { user, role } = getIdentity()

  const refresh = useCallback(
    () =>
      api.getWorkOrder(wo.id)
        .then((d) => {
          setDetail(d)
          setPendingProof((d.proofs || []).find((p) => !p.submitted) || null)
        })
        .catch(() => {}),
    [wo.id],
  )
  useEffect(() => { refresh() }, [refresh])

  /** Every mutating control goes through here, so a 409 from the state machine
   *  surfaces as a message instead of a silent no-op. */
  const run = async (fn) => {
    setBusy(true)
    setActionError('')
    try {
      await fn()
      onChanged()
      await refresh()
    } catch (err) {
      setActionError(err.detail?.message || err.message)
    } finally {
      setBusy(false)
    }
  }

  const start = () => run(() => api.startWorkOrder(wo.id, user))

  const loadRecommendation = () =>
    api.evidenceRecommendation(wo.id).then(setRecommendation).catch(() => {})

  // Upload only runs the AI check and stores a draft; refresh() surfaces it as
  // pendingProof for confirm/cancel.
  const upload = () =>
    run(async () => {
      await api.uploadProof(wo.id, file, note)
      setFile(null)
      setNote('')
    })

  const submit = (override) => run(() => api.submitProof(pendingProof.id, override))
  const cancelUpload = () => run(() => api.cancelProof(pendingProof.id))

  const verify = (proofId, approved) => {
    const notes = approved ? '' : window.prompt('Reason for rejection?') || ''
    return run(() => api.humanVerify(proofId, approved, notes))
  }

  // Drafts are shown in the confirm panel, not the history list.
  const proofs = (detail?.proofs || []).filter((p) => p.submitted)
  // A rejected order can be restarted; matches IssueDetail's canStart.
  const canStart = ['open', 'rejected'].includes(wo.status) && role !== 'admin'
  const canUpload =
    ['in_progress', 'awaiting_proof'].includes(wo.status) && role !== 'admin' && !pendingProof

  return (
    <div className="detail-card">
      <h3 style={{ marginBottom: 4 }}>{wo.issue_reference_no} — {wo.issue_title}</h3>
      {wo.issue_description && (
        <div className="field-hint" style={{ marginBottom: 13 }}>{wo.issue_description}</div>
      )}

      <div className="verify-row" style={{ marginBottom: 12 }}>
        <span className="verify-icon" style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}>
          ⚑
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 12.5, fontWeight: 500 }}>{workOrderLabel(wo.status)}</div>
          <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 2 }}>
            {wo.assignee ? `Assigned to ${wo.assignee}` : 'Unassigned'}
            {wo.is_temporary_fix && ' · temporary fix'}
          </div>
        </div>
        {wo.requires_human_verification && (
          <Chip color="var(--accent)" background="var(--accent-soft)">Sign-off required</Chip>
        )}
      </div>

      {actionError && <p className="error">{actionError}</p>}

      {canStart && (
        <>
          <button disabled={busy} onClick={start} style={{ marginBottom: 6 }}>Start work</button>
          <div className="field-hint" style={{ marginBottom: 12 }}>
            Start work before uploading proof.
          </div>
        </>
      )}

      {/* Step 2: review the AI check on the just-uploaded draft, then confirm or cancel. */}
      {pendingProof && role !== 'admin' && (
        <ConfirmPanel
          proof={pendingProof}
          busy={busy}
          onConfirm={() => submit(false)}
          onOverride={() => submit(true)}
          onCancel={cancelUpload}
        />
      )}

      {/* Step 1: pick a file and upload for the AI check. */}
      {canUpload && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 4 }}>
          <div>
            <button className="secondary" disabled={busy} onClick={loadRecommendation}>
              What proof should I upload?
            </button>
          </div>
          {recommendation?.recommended?.length > 0 && (
            <div className="ai-frame">
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
                      {recommendation.rationale} (Recommendation only — upload what you have.)
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          <div>
            <label>Proof of work</label>
            <input type="file" onChange={(e) => setFile(e.target.files[0])} />
            <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button disabled={!file || busy} onClick={upload}>Upload for AI check</button>
          </div>
        </div>
      )}

      {proofs.length === 0 ? (
        !pendingProof && (
          <div className="field-hint" style={{ marginTop: 10 }}>No proof submitted yet.</div>
        )
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 12 }}>
          {proofs.map((proof) => {
            const state = proofState(proof)
            // Any submitted proof still awaiting a verdict is the admin's to
            // judge — including one the AI flagged irrelevant that maintenance
            // overrode into the queue.
            const canJudge = role === 'admin' && !proof.human_verdict
            return (
              <div key={proof.id} className="verify-row">
                <span className="verify-icon" style={{ background: state.bg, color: state.c }}>
                  {state.icon}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, fontWeight: 500 }}>
                    <a href={api.proofFileUrl(proof.id)} target="_blank" rel="noreferrer">
                      {proof.note || `${proof.media_type} proof`}
                    </a>
                    {proof.ai_overridden && (
                      <Chip color="#b07a0c" background="#fdf6e3">AI overridden</Chip>
                    )}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--muted-2)', marginTop: 2 }}>
                    by {proof.uploaded_by}
                    {proof.ai_reason && ` · ${proof.ai_reason}`}
                    {proof.human_notes && ` · ${proof.human_notes}`}
                  </div>
                </div>
                {canJudge ? (
                  <div style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
                    <button disabled={busy} onClick={() => verify(proof.id, true)}>Approve</button>
                    <button className="ghost" disabled={busy} onClick={() => verify(proof.id, false)}>
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
    </div>
  )
}

/** Step 2 of upload: the AI verdict on a draft proof, with confirm/cancel — and,
 *  when the AI judged it unrelated, an override that sends it to human sign-off
 *  anyway. */
function ConfirmPanel({ proof, busy, onConfirm, onOverride, onCancel }) {
  const state = proofState(proof)
  const flagged = proof.ai_verdict === 'irrelevant'
  return (
    <div className="ai-frame" style={{ marginBottom: 12 }}>
      <div style={{ padding: '12px 13px' }}>
        <div className="ai-text" style={{ fontSize: 11.5, marginBottom: 8 }}>AI relevance check</div>
        <div className="verify-row" style={{ marginBottom: 10 }}>
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
              {state.label}{proof.ai_reason && ` · ${proof.ai_reason}`}
            </div>
          </div>
        </div>

        {flagged && (
          <p className="error" style={{ marginTop: 0 }}>
            The AI judged this proof unrelated to the issue. Override to send it for
            human sign-off, or cancel and upload a different proof.
          </p>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
          {flagged ? (
            <button disabled={busy} onClick={onOverride}>Override &amp; submit</button>
          ) : (
            <button disabled={busy} onClick={onConfirm}>Confirm submission</button>
          )}
          <button className="ghost" disabled={busy} onClick={onCancel}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

export default function FixVerify() {
  const [workOrders, setWorkOrders] = useState(null)
  const [error, setError] = useState(null)

  const refresh = useCallback(() => {
    api.listWorkOrders()
      .then((list) => { setWorkOrders(list); setError(null) })
      .catch(setError)
  }, [])
  useEffect(() => { refresh() }, [refresh])

  return (
    <>
      <h2>Fix &amp; Verify</h2>
      {error ? (
        <ErrorState error={error} onRetry={refresh} />
      ) : workOrders === null ? (
        <Spinner label="Loading work orders…" />
      ) : workOrders.length === 0 ? (
        <EmptyState
          title="No work orders yet"
          hint="They are created automatically when an issue is triaged."
        />
      ) : (
        workOrders.map((wo) => <WorkOrderCard key={wo.id} wo={wo} onChanged={refresh} />)
      )}
    </>
  )
}
