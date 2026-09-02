import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'

export default function TriageBoard() {
  const [issues, setIssues] = useState([])
  const [overview, setOverview] = useState(null)
  const [groupBy, setGroupBy] = useState('location')

  const refresh = () => {
    api.listIssues({ status: 'reported' }).then((reported) =>
      api.listIssues({ status: 'triaged' }).then((triaged) =>
        setIssues([...reported, ...triaged])))
  }
  useEffect(refresh, [])
  // One call for both panels below: the analytics output is a single GET, and
  // `by` is the only thing that changes when the grouping does.
  useEffect(() => {
    api.triageOverview(groupBy).then(setOverview).catch(() => setOverview(null))
  }, [groupBy])

  const systemic = overview?.systemic || []
  const profiles = overview?.profiles || []

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
            <strong>{cluster.cluster_key.replaceAll('|', ' · ')}</strong>
            {' — '}{cluster.issue_count_live} issues in the window
            {!cluster.active && <span className="hint"> · no longer accruing</span>}
            <br />
            <span className="hint">{cluster.recommendation || 'Generating recommendation…'}</span>
          </div>
        ))}
      </div>

      {/* Profiles, not MTBF/MTTR: raw metrics are generated elsewhere and the
          endpoint serves the backlog shape plus the findings over it (docs/05).
          Every rate here is labelled with the window it is taken over, because
          `total` and `recent` answer different questions. */}
      <div className="card">
        <h3>Location profiles</h3>
        <label>Group by </label>
        <select style={{ width: 160 }} value={groupBy} onChange={(e) => setGroupBy(e.target.value)}>
          <option value="location">location</option>
          <option value="category">category</option>
          <option value="equipment">equipment</option>
        </select>
        {profiles.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Group</th><th>Issues</th><th>Open</th>
                <th>Last {profiles[0].window_days}d</th><th>Trend</th><th>Repeats</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((row) => (
                <tr key={row.group}>
                  <td>{row.group.replaceAll('|', ' · ')}</td>
                  <td>{row.total}</td>
                  <td>{row.open}</td>
                  <td>{row.recent}</td>
                  {/* null is "no prior window to compare against", not 0% */}
                  <td>{row.trend_pct === null ? '—' : `${row.trend_pct > 0 ? '+' : ''}${row.trend_pct}%`}</td>
                  <td>{row.repeat_rate === null ? '—' : `${Math.round(row.repeat_rate * 100)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {overview && profiles.length === 0 && <p className="hint">No issues in the snapshot yet.</p>}
      </div>
    </>
  )
}
