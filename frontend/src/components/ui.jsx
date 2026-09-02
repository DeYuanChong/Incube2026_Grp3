// The small pieces every page was hand-rolling: KPI tiles, filter pills, the
// segmented toggle, chips, and loading/empty/error states.
import {
  LIFECYCLE_STEPS,
  STATUS_COLOR,
  STATUS_STAMP,
  chipStyle,
  sev as sevToken,
  statusLabel,
} from '../lib/tokens'

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


/**
 * Where a defect sits in its lifecycle, as a horizontal rail.
 *
 * Two things stop this being a plain index comparison:
 *
 *  - `in_progress` can be *skipped*. The resolved-on-arrival path goes
 *    triaged → pending_verification directly, so a step behind the current one
 *    is only "done" if its timestamp column was actually stamped.
 *  - The rail moves *backwards*. A rejected proof sends pending_verification →
 *    in_progress and a reporter dispute sends verified → in_progress, so steps
 *    ahead of the current one return to "upcoming" even though their column is
 *    still populated from the first pass. The caption explains why.
 */
function railSteps(issue) {
  const cancelled = issue.status === 'cancelled'
  // A cancellation always branches off `reported`, so it occupies slot 2 —
  // where `triaged` would have been had the defect gone on living.
  const current = cancelled ? 1 : LIFECYCLE_STEPS.indexOf(issue.status)

  return LIFECYCLE_STEPS.map((status, i) => {
    if (cancelled && i === 1) {
      return {
        status: 'cancelled',
        label: 'Cancelled',
        state: 'cancelled',
        // cancel stamps only updated_at — there is no closed_at to fall back on
        at: issue.updated_at,
      }
    }
    const at = issue[STATUS_STAMP[status]]
    let state
    // A cancelled defect was still genuinely reported; only what comes after
    // the cancellation became unreachable.
    if (cancelled) state = i < current ? 'done' : 'unreachable'
    else if (i < current) state = at ? 'done' : 'skipped'
    else if (i === current) state = 'current'
    else state = 'upcoming'
    return { status, label: statusLabel(status), state, at }
  })
}

const STEP_TITLE = {
  skipped: 'Skipped — the defect was already resolved when maintenance arrived',
  upcoming: 'Not reached yet',
  unreachable: 'Never reached — the defect was cancelled',
}

function stepTitle(step) {
  if (STEP_TITLE[step.state]) return STEP_TITLE[step.state]
  return step.at ? new Date(step.at).toLocaleString() : undefined
}

/** The work order's substate, which the issue status alone cannot show — most
 *  importantly a rejected proof, which moves the work order but not the issue. */
function railCaption(issue, work) {
  if (issue.status === 'cancelled') {
    return {
      lead: 'Cancelled',
      text: issue.cancellation_reason || 'No reason recorded.',
      alert: true,
    }
  }

  const wo = work?.work_order
  if (!wo) return null

  const arrival = wo.resolved_on_arrival
    ? ' Resolved on arrival — no work was started.'
    : ''

  if (wo.status === 'awaiting_proof') {
    // Proofs come back ordered created_at ascending, so the last is the newest.
    const last = work.proofs?.[work.proofs.length - 1]
    let why = 'The last upload was not accepted.'
    if (last?.human_verdict === 'rejected') {
      why = last.human_notes
        ? `Sign-off rejected: ${last.human_notes}`
        : 'Sign-off was rejected.'
    } else if (last?.ai_verdict === 'irrelevant') {
      why = last.ai_reason
        ? `The last upload was judged unrelated: ${last.ai_reason}`
        : 'The last upload was judged unrelated to this defect.'
    }
    return { lead: 'Awaiting proof', text: `${why} A replacement is needed.`, alert: true }
  }

  if (wo.status === 'open') {
    return {
      lead: 'Not started',
      text: `Waiting for a maintenance user to pick this up.${arrival}`,
    }
  }
  if (wo.status === 'in_progress') {
    return {
      lead: 'Work underway',
      text: `${wo.assignee ? `Assigned to ${wo.assignee}.` : 'Unassigned.'}${arrival}`,
    }
  }
  if (wo.status === 'pending_human_verification') {
    return {
      lead: 'Awaiting sign-off',
      text: `Proof uploaded; an admin still has to approve it.${arrival}`,
    }
  }
  if (wo.status === 'verified') {
    return {
      lead: 'Signed off',
      text: `The proof was approved.${arrival}`,
    }
  }
  return null
}

export function LifecycleRail({ issue, work }) {
  const steps = railSteps(issue)
  const current = steps.findIndex((s) => s.state === 'current' || s.state === 'cancelled')
  const caption = railCaption(issue, work)

  return (
    <div>
      <div className="lifecycle">
        {steps.map((step, i) => (
          <div
            key={step.status}
            className={`lifecycle-step${step.state === 'unreachable' ? ' unreachable' : ''}`}
          >
            <div className="lifecycle-track">
              {/* the filled track runs up to the current dot and stops there */}
              <span className={`lifecycle-line${i <= current ? ' filled' : ''}`} />
              <span
                className={`lifecycle-dot ${step.state}`}
                style={
                  step.state === 'current'
                    ? { background: STATUS_COLOR[step.status] }
                    : undefined
                }
                title={stepTitle(step)}
              />
              <span className={`lifecycle-line${i < current ? ' filled' : ''}`} />
            </div>
            <div className={`lifecycle-label ${step.state}`}>{step.label}</div>
          </div>
        ))}
      </div>

      {caption && (
        <div className={`lifecycle-caption${caption.alert ? ' alert' : ''}`}>
          <strong>{caption.lead}</strong> — {caption.text}
        </div>
      )}
    </div>
  )
}

/**
 * A hover/focus hint on a field label. Purely presentational — it explains, it
 * never acts, so pointing at it costs nothing. Anything that fetches or changes
 * state belongs in a control the user deliberately clicks.
 */
export function InfoHint({ label, children }) {
  return (
    <span className="info" tabIndex={0} role="button" aria-label={label}>
      i
      <span className="info-pop" role="tooltip">
        <span className="info-pop-body">{children}</span>
      </span>
    </span>
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
export function Pills({ legend, options, value, onChange, labelOf = (v) => v }) {
  return (
    <div className="filter-row">
      {legend && <span className="filter-legend">{legend}</span>}
      {options.map((option) => (
        <button
          type="button"
          key={option}
          className={`pill${option === value ? ' on' : ''}`}
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
