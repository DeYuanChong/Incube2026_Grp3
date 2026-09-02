// The small pieces every page was hand-rolling: KPI tiles, filter pills, the
// segmented toggle, chips, and loading/empty/error states.
import { STATUS_COLOR, chipStyle, sev as sevToken, statusLabel } from '../lib/tokens'

export function Chip({ color, background, children, style }) {
  return (
    <span className="chip" style={{ ...chipStyle(color, background), ...style }}>
      {children}
    </span>
  )
}

export function SeverityChip({ value }) {
  const token = sevToken(value)
  return (
    <Chip color={token.c} background={token.bg}>
      {token.label}
    </Chip>
  )
}

/** The mock's alternative severity read: rank as four filled ticks. */
export function SeverityBars({ value, note }) {
  const token = sevToken(value)
  return (
    <div>
      <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        {['low', 'medium', 'high', 'critical'].map((level) => (
          <span
            key={level}
            className="sev-tick"
            style={{
              background: sevToken(level).rank <= token.rank ? token.c : '#edf0f5',
            }}
          />
        ))}
        <span style={{ fontSize: 11, color: 'var(--muted)', marginLeft: 5, fontWeight: 500 }}>
          {token.label}
        </span>
      </div>
      {note && (
        <div style={{ fontSize: 10.5, color: 'var(--muted-2)', marginTop: 4 }}>{note}</div>
      )}
    </div>
  )
}

export function StatusCell({ value }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 7, minWidth: 0 }}>
      <span
        className="status-dot"
        style={{ background: STATUS_COLOR[value] || 'var(--muted-2)' }}
      />
      <span className="cell-truncate" style={{ fontSize: 12.5, color: 'var(--text-2)' }}>
        {statusLabel(value)}
      </span>
    </div>
  )
}

const DELTA_TONE = {
  danger: 'var(--danger)',
  warn: 'var(--warn)',
  ok: 'var(--ok)',
  accent: 'var(--accent)',
  muted: 'var(--muted-2)',
}

export function KpiCard({ label, value, delta, deltaTone = 'muted', note, onClick, active }) {
  const Tag = onClick ? 'button' : 'div'
  return (
    <Tag
      type={onClick ? 'button' : undefined}
      onClick={onClick}
      className={`kpi${onClick ? ' clickable' : ''}${active ? ' active' : ''}`}
    >
      <div className="kpi-label">{label}</div>
      <div className="kpi-row">
        <div className="kpi-value">{value}</div>
        {delta && (
          <div className="kpi-delta" style={{ color: DELTA_TONE[deltaTone] }}>
            {delta}
          </div>
        )}
      </div>
      {note && <div className="kpi-note">{note}</div>}
    </Tag>
  )
}

/** The mock's `pills(list, active, key)` helper. */
export function Pills({ legend, options, value, onChange, labelOf = (v) => v, titleOf }) {
  return (
    <div className="filter-row">
      {legend && <span className="filter-legend">{legend}</span>}
      {options.map((option) => (
        <button
          type="button"
          key={option}
          className={`pill${option === value ? ' on' : ''}`}
          title={titleOf ? titleOf(option) : undefined}
          onClick={() => onChange(option)}
        >
          {labelOf(option)}
        </button>
      ))}
    </div>
  )
}

/** The mock's `toggle(...)` helper: a two-or-more-way segmented control. */
export function Segmented({ options, value, onChange, onSurface }) {
  return (
    <div className={`segmented${onSurface ? ' on-surface' : ''}`}>
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          className={option.value === value ? 'on' : ''}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

export function Spinner({ label }) {
  return (
    <div className="empty">
      <span className="spinner" />
      {label && <div style={{ marginTop: 10 }}>{label}</div>}
    </div>
  )
}

export function EmptyState({ title, hint }) {
  return (
    <div className="empty">
      <div style={{ fontWeight: 600, color: 'var(--muted)' }}>{title}</div>
      {hint && <div style={{ marginTop: 6, maxWidth: 460, margin: '6px auto 0' }}>{hint}</div>}
    </div>
  )
}

/** Shown when a fetch fails, so a dead service is legible instead of blank. */
export function ErrorState({ error, onRetry }) {
  return (
    <div className="empty">
      <div style={{ fontWeight: 600, color: 'var(--danger)' }}>Could not load this</div>
      <div style={{ marginTop: 6 }}>{error?.message || 'The service did not respond.'}</div>
      {onRetry && (
        <button className="secondary" style={{ marginTop: 12 }} onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}
