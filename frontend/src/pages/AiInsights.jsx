// AI insights, ported from the canvas mock's second screen against
// GET /api/triage, which returns the whole analytics output in one call.
//
// Two things the mock showed are absent by design: a per-card confidence score
// and an "avoidable spend" figure. Nothing in the system produces either, so
// each card carries its evidence counts and its live/decayed state instead —
// which is the signal docs/05 actually argues for, since a cluster someone
// remediated in March should not top the admin's list in September.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Chip, EmptyState, ErrorState, Pills, Segmented, Spinner } from '../components/ui'
import { relativeDate } from '../lib/format'
import { INSIGHT_KIND } from '../lib/tokens'

const KIND_FILTERS = ['All', 'systemic', 'predictive', 'pre-emptive']
const kindToken = (kind) => INSIGHT_KIND[kind] || { c: '#5b6472', bg: '#f1f4f8', label: kind }

/** Deep link to the dashboard, pre-filtered to this finding's issues.
 *  The server states the filter (`insight.filter`) because it is the side that
 *  knows the group — a systemic insight's id is a cluster UUID, which cannot be
 *  reconstructed into a location. */
const linkFor = (insight) => {
  if (!insight.filter?.search) return '/'
  const params = new URLSearchParams({ open: '1', q: insight.filter.search })
  if (insight.filter.category) params.set('category', insight.filter.category)
  return `/?${params}`
}

export default function AiInsights() {
  const [insights, setInsights] = useState(null)
  const [total, setTotal] = useState(0)
  const [error, setError] = useState(null)
  const [kind, setKind] = useState('All')
  const [view, setView] = useState('cards')

  // One call for the page. The endpoint serves findings rather than raw
  // metrics, so the hero's worst-MTBF figure comes off the cards themselves
  // instead of a second request that no longer exists.
  const load = useCallback(() => {
    setError(null)
    api.triageOverview()
      .then((data) => { setInsights(data.insights); setTotal(data.insight_count) })
      .catch((err) => { setInsights([]); setError(err) })
  }, [])

  useEffect(load, [load])

  const shown = useMemo(
    () => (insights || []).filter((i) => kind === 'All' || i.kind === kind),
    [insights, kind],
  )

  const active = (insights || []).filter((i) => i.active)
  const linkedTotal = active.reduce((sum, i) => sum + i.linked_count, 0)
  // Cards arrive ranked worst-first and an mtbf card scores on how far below
  // the threshold it sits, so the first one is the worst asset. It already
  // carries the number that raised it.
  const worstMtbf = (insights || [])
    .filter((i) => i.source === 'mtbf')
    .map((i) => i.evidence.find((e) => e.label === 'MTBF')?.value)
    .find(Boolean)

  return (
    <div className="stack">
      <div className="insights-hero">
        <div style={{ maxWidth: 620 }}>
          <div
            style={{
              fontSize: 11.5, fontWeight: 600, letterSpacing: '0.08em',
              textTransform: 'uppercase', opacity: 0.85,
            }}
          >
            CPS Agent
          </div>
          <div
            style={{
              fontSize: 19, fontWeight: 600, letterSpacing: '-0.3px',
              marginTop: 7, lineHeight: 1.35,
            }}
          >
            {insights === null
              ? 'Reading the analytics snapshot…'
              : active.length === 0
                ? 'No live patterns to act on right now'
                : `${active.length} pattern${active.length === 1 ? '' : 's'} worth acting on before they generate more tickets`}
          </div>
          {total > (insights || []).length && (
            <div style={{ fontSize: 12, marginTop: 6, opacity: 0.75 }}>
              Showing the {(insights || []).length} highest-ranked of {total} findings.
            </div>
          )}
          <div style={{ fontSize: 12.5, lineHeight: 1.55, marginTop: 8, opacity: 0.9 }}>
            Drawn from repeat-report clustering, MTBF by asset, 30-day location
            trends and vendor proof history. Every number links back to the
            issues behind it.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 18, flex: '0 0 auto' }}>
          <HeroStat value={active.length} label="Live signals" />
          <HeroStat value={linkedTotal} label="Linked defects" />
          <HeroStat value={worstMtbf || '—'} label="Worst MTBF" />
        </div>
      </div>

      <div
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, flexWrap: 'wrap',
        }}
      >
        <Pills
          options={KIND_FILTERS}
          value={kind}
          onChange={setKind}
          labelOf={(v) => (v === 'All' ? 'All' : kindToken(v).label)}
        />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11.5, color: 'var(--muted-2)' }}>Surface as</span>
          <Segmented
            onSurface
            value={view}
            onChange={setView}
            options={[
              { value: 'cards', label: 'Cards' },
              { value: 'feed', label: 'Briefing feed' },
            ]}
          />
        </div>
      </div>

      {insights === null && <div className="card"><Spinner label="Assembling insights…" /></div>}
      {error && <div className="card"><ErrorState error={error} onRetry={load} /></div>}
      {insights !== null && !error && shown.length === 0 && (
        <div className="card">
          <EmptyState
            title={
              insights.length === 0
                ? 'Nothing has crossed a threshold yet'
                : 'No insights of that kind'
            }
            hint={
              insights.length === 0
                ? 'A finding appears once a location clusters three issues inside the window, an asset drops below a 60-day MTBF, a location trends up by half, or an assignee’s proofs keep being rejected.'
                : 'Try another kind, or All.'
            }
          />
        </div>
      )}

      {shown.length > 0 && view === 'cards' && (
        <div className="insight-grid">
          {shown.map((insight) => (
            <Card key={insight.id} insight={insight} />
          ))}
        </div>
      )}

      {shown.length > 0 && view === 'feed' && (
        <div className="table-card">
          {shown.map((insight) => (
            <FeedRow key={insight.id} insight={insight} />
          ))}
        </div>
      )}
    </div>
  )
}

function HeroStat({ value, label }) {
  return (
    <div className="hero-stat">
      <div className="hero-stat-value">{value}</div>
      <div className="hero-stat-label">{label}</div>
    </div>
  )
}

function KindHeader({ insight }) {
  const token = kindToken(insight.kind)
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <Chip color={token.c} background={token.bg}>{token.label}</Chip>
        <span style={{ fontSize: 11, color: 'var(--muted-2)', whiteSpace: 'nowrap' }}>
          last {insight.window_days} days
        </span>
      </div>
      {!insight.active && (
        <Chip color="var(--muted)" background="var(--border-soft)">no longer accruing</Chip>
      )}
    </div>
  )
}

function Evidence({ insight }) {
  return (
    <div className="evidence-strip">
      {insight.evidence.map((item) => (
        <div key={item.label}>
          <div className="evidence-label">{item.label}</div>
          <div className="evidence-value">{item.value}</div>
        </div>
      ))}
    </div>
  )
}

function Card({ insight }) {
  return (
    <div className={`insight-card${insight.active ? '' : ' decayed'}`}>
      <div className="insight-inner">
        <KindHeader insight={insight} />
        <div style={{ fontSize: 15, fontWeight: 600, letterSpacing: '-0.2px', marginTop: 11, lineHeight: 1.35 }}>
          {insight.title}
        </div>
        <div style={{ fontSize: 12.5, lineHeight: 1.6, color: 'var(--muted)', marginTop: 8 }}>
          {insight.body}
        </div>
        <Evidence insight={insight} />
        <div className="section-label" style={{ marginTop: 12 }}>Recommended action</div>
        <div style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--text-2)', marginTop: 5 }}>
          {insight.action}
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 'auto', paddingTop: 13, flexWrap: 'wrap' }}>
          {insight.linked_count > 0 && insight.filter?.search && (
            <Link to={linkFor(insight)}>
              <button className="ghost" type="button">
                See {insight.linked_count} defect{insight.linked_count === 1 ? '' : 's'}
              </button>
            </Link>
          )}
          {insight.linked.slice(0, 1).map((issue) => (
            <Link key={issue.issue_id} to={`/issues/${issue.issue_id}`}>
              <button className="ghost" type="button">Open {issue.reference_no}</button>
            </Link>
          ))}
        </div>
      </div>
    </div>
  )
}

function FeedRow({ insight }) {
  return (
    <div className="feed-row">
      <div className={`feed-rule${insight.active ? '' : ' decayed'}`} />
      <div style={{ padding: '16px 18px', minWidth: 0 }}>
        <KindHeader insight={insight} />
        <div style={{ fontSize: 14.5, fontWeight: 600, marginTop: 9, letterSpacing: '-0.2px' }}>
          {insight.title}
        </div>
        <div
          style={{
            fontSize: 12.5, lineHeight: 1.6, color: 'var(--muted)',
            marginTop: 6, maxWidth: 760,
          }}
        >
          {insight.body}
        </div>
        <div style={{ display: 'flex', gap: 22, marginTop: 12, flexWrap: 'wrap' }}>
          {insight.evidence.map((item) => (
            <div key={item.label} style={{ display: 'flex', alignItems: 'baseline', gap: 7 }}>
              <span style={{ fontSize: 13.5, fontWeight: 600, fontFamily: 'var(--mono)' }}>
                {item.value}
              </span>
              <span style={{ fontSize: 11, color: 'var(--muted-2)' }}>{item.label}</span>
            </div>
          ))}
        </div>
        {insight.linked.length > 0 && (
          <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {insight.linked.slice(0, 6).map((issue) => (
              <Link
                key={issue.issue_id}
                to={`/issues/${issue.issue_id}`}
                style={{ fontSize: 11, fontFamily: 'var(--mono)' }}
                title={`${issue.title} · ${relativeDate(issue.created_at)}`}
              >
                {issue.reference_no}
              </Link>
            ))}
            {insight.linked_count > 6 && (
              <span style={{ fontSize: 11, color: 'var(--muted-2)' }}>
                +{insight.linked_count - 6} more
              </span>
            )}
          </div>
        )}
      </div>
      <div className="feed-action">
        <div className="section-label">Action</div>
        <div style={{ fontSize: 12, lineHeight: 1.5, color: 'var(--text-2)', marginTop: 6 }}>
          {insight.action}
        </div>
        {insight.linked_count > 0 && insight.filter?.search && (
          <Link to={linkFor(insight)}>
            <button className="gradient" type="button" style={{ marginTop: 11, fontSize: 11.5 }}>
              See {insight.linked_count} defect{insight.linked_count === 1 ? '' : 's'}
            </button>
          </Link>
        )}
      </div>
    </div>
  )
}
