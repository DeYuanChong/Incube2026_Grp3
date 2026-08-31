import { useEffect, useState } from 'react'
import { api, getIdentity } from '../api'

function WorkOrderCard({ wo, onChanged }) {
  const [detail, setDetail] = useState(null)
  const [recommendation, setRecommendation] = useState(null)
  const [file, setFile] = useState(null)
  const [note, setNote] = useState('')
  const [rejection, setRejection] = useState('')
  const { user, role } = getIdentity()

  const refresh = () => api.getWorkOrder(wo.id).then(setDetail)
  useEffect(() => { refresh() }, [wo.id])

  const start = async () => { await api.startWorkOrder(wo.id, user); onChanged() }

  const loadRecommendation = () =>
    api.evidenceRecommendation(wo.id).then(setRecommendation)

  const upload = async () => {
    setRejection('')
    try {
      await api.uploadProof(wo.id, file, note)
      onChanged()
      refresh()
    } catch (err) {
      // 422 = AI judged the proof unrelated to the issue; show reason, ask re-upload
      setRejection(err.detail?.ai_reason || err.message)
    }
  }

  const verify = async (proofId, approved) => {
    const notes = approved ? '' : prompt('Reason for rejection?') || ''
    await api.humanVerify(proofId, approved, notes)
    onChanged()
    refresh()
  }

  return (
    <div className="card">
      <h3>{wo.issue_reference_no} — {wo.issue_title}</h3>
      <p className="hint">{wo.issue_description}</p>
      <p><span className={`badge ${wo.status}`}>{wo.status.replaceAll('_', ' ')}</span>
        {wo.assignee && <span className="hint"> · assignee: {wo.assignee}</span>}</p>

      {wo.status === 'open' && role !== 'admin' && <button onClick={start}>Start work</button>}

      {(wo.status === 'in_progress' || wo.status === 'awaiting_proof') && role !== 'admin' && (
        <>
          <button className="secondary" onClick={loadRecommendation}>
            What proof should I upload?
          </button>
          {recommendation && (
            <div className="suggestion">
              {recommendation.recommended.map((r, i) => (
                <div key={i}>📎 <strong>{r.what}</strong> ({r.media_type}) — <span className="hint">{r.why}</span></div>
              ))}
              <span className="hint">{recommendation.rationale} (Recommendation only — upload what you have.)</span>
            </div>
          )}
          <label>Proof of work</label>
          <input type="file" onChange={(e) => setFile(e.target.files[0])} />
          <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <button disabled={!file} onClick={upload}>Upload proof</button>
          {rejection && <p className="error">❌ Rejected: {rejection} Please upload a different proof.</p>}
        </>
      )}

      {detail?.proofs?.length > 0 && (
        <table>
          <thead><tr><th>Proof</th><th>AI check</th><th>Human verdict</th><th></th></tr></thead>
          <tbody>
            {detail.proofs.map((proof) => (
              <tr key={proof.id}>
                <td><a href={`${import.meta.env.VITE_GATEWAY_URL || 'http://localhost:8000'}/api/fixverify/proofs/${proof.id}/file`}
                       target="_blank" rel="noreferrer">view file</a>
                  <span className="hint"> by {proof.uploaded_by}</span></td>
                <td>{proof.ai_verdict} <span className="hint">{proof.ai_reason}</span></td>
                <td>{proof.human_verdict || '—'}</td>
                <td>
                  {role === 'admin' && !proof.human_verdict && proof.ai_verdict !== 'irrelevant' && (
                    <>
                      <button onClick={() => verify(proof.id, true)}>Approve</button>{' '}
                      <button className="secondary" onClick={() => verify(proof.id, false)}>Reject</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function FixVerify() {
  const [workOrders, setWorkOrders] = useState([])
  const refresh = () => api.listWorkOrders().then(setWorkOrders).catch(() => {})
  useEffect(() => { refresh() }, [])

  return (
    <>
      <h2>Fix & Verify</h2>
      {workOrders.length === 0 && <p className="hint">No work orders yet — they are created automatically when an issue is triaged.</p>}
      {workOrders.map((wo) => <WorkOrderCard key={wo.id} wo={wo} onChanged={refresh} />)}
    </>
  )
}
