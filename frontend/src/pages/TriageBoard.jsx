import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function TriageBoard() {
  const [issues, setIssues] = useState([])
  const [systemic, setSystemic] = useState([])
  const [metrics, setMetrics] = useState(null)
  const [groupBy, setGroupBy] = useState('category')

  const refresh = () => {
    api.listIssues({ status: 'reported' }).then((reported) =>
      api.listIssues({ status: 'triaged' }).then((triaged) =>
        setIssues([...reported, ...triaged])))
    api.systemic().then(setSystemic).catch(() => {})
  }
  useEffect(refresh, [])
  useEffect(() => { api.metrics(groupBy).then(setMetrics).catch(() => {}) }, [groupBy])

  const rerun = async (id) => { await api.runTriage(id); refresh() }
  const confirm = async (id) => { await api.confirmTriage(id, {}); refresh() }

  return (
    <>
      <div className="card">
        <h2>Triage queue</h2>
        <table>
          <thead>
            <tr><th>Ref</th><th>Title</th><th>Severity</th><th>Urgency</th>
                <th>Dupes</th><th></th></tr>
          </thead>
          <tbody>
            {issues.map((issue) => (
              <tr key={issue.id}>
                <td><Link to={`/issues/${issue.id}`}>{issue.reference_no}</Link></td>
                <td>{issue.title}</td>
                <td>{issue.severity ? <span className={`badge ${issue.severity}`}>{issue.severity}</span> : '—'}</td>
                <td>{issue.urgency || '—'}</td>
                <td>{issue.duplicate_count > 1 ? issue.duplicate_count : ''}</td>
                <td>
                  <button className="secondary" onClick={() => rerun(issue.id)}>Re-run AI</button>{' '}
                  <button onClick={() => confirm(issue.id)}>Confirm</button>
                </td>
              </tr>
            ))}
            {issues.length === 0 && <tr><td colSpan={6} className="hint">Queue is empty.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h3>Systemic findings (macro level)</h3>
        {systemic.length === 0 && <p className="hint">No systemic clusters flagged yet.</p>}
        {systemic.map((cluster) => (
          <div key={cluster.id} className="suggestion">
            <strong>{cluster.cluster_key.replaceAll('|', ' · ')}</strong> — {cluster.issue_count} issues
            <br />
            <span className="hint">{cluster.recommendation || 'Generating recommendation…'}</span>
          </div>
        ))}
      </div>

      <div className="card">
        <h3>Metrics</h3>
        <label>Group by </label>
        <select style={{ width: 160 }} value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
          <option value="category">category</option>
          <option value="building">building</option>
          <option value="floor">floor</option>
          <option value="equipment">equipment</option>
        </select>
        {metrics && (
          <table>
            <thead><tr><th>Group</th><th>MTBF (days)</th><th>MTTR (days)</th></tr></thead>
            <tbody>
              {[...new Set([...metrics.mtbf, ...metrics.mttr].map((r) => r.group))].map((group) => {
                const mtbfRow = metrics.mtbf.find((r) => r.group === group)
                const mttrRow = metrics.mttr.find((r) => r.group === group)
                return (
                  <tr key={group}>
                    <td>{group}</td>
                    <td>{mtbfRow?.mtbf_days ?? '—'}</td>
                    <td>{mttrRow?.mttr_days ?? '—'}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
