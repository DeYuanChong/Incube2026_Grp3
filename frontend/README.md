# Frontend (:5173)

React (Vite) app, no UI framework and no state library — `useState`/`useEffect`
per page, plain CSS with custom properties. All API calls go through the gateway
(`VITE_GATEWAY_URL`, default `http://localhost:8000`).

```bash
npm install
npm run dev
```

## Layout

```
src/
  main.jsx                mounts <App> in a BrowserRouter, imports styles.css
  App.jsx                 identity state, sidebar badge polling, <Routes>
  api.js                  the one fetch client; injects X-User / X-Role
  styles.css              design tokens (:root custom properties) + component classes
  components/
    Shell.jsx             sidebar + topbar, and ROUTES — the single nav/route table
    ui.jsx                KpiCard, Pills, Segmented, chips, LifecycleRail,
                          Spinner/Empty/Error states
  lib/
    tokens.js             colour + display-label maps for the real enums
    format.js             age, SLA state, location and duration formatting
  pages/
    Dashboard.jsx         Defects Management: KPI tiles, filter chips, grid table
    AiInsights.jsx        recommendation cards from /analytics/insights (admin)
    ReportIssue.jsx       submission, with the AI category suggestion + ETA
    IssueDetail.jsx       one issue and its timeline (reporter view)
    DefectWorkspace.jsx   one defect + its work order and proofs (maintenance/admin)
    TriageBoard.jsx       triage queue, systemic findings, MTBF/MTTR (admin)
    Notifications.jsx     inbox
```

`components/` and `lib/` exist so pages stop re-implementing the same tile,
pill, chip and empty-state markup. Add to them rather than inlining a fourth
variant of a table header.

## Pages

| Page | Route | Who | What |
|---|---|---|---|
| Defects Management | `/` | all | Four KPI tiles from `GET /stats/dashboard`, four rows of filter chips, and a grid table with age vs SLA. Breached rows are tinted and carry a nudge banner. |
| AI insights | `/insights` | admin | Systemic / predictive / pre-emptive cards from `GET /analytics/insights`, as cards or a briefing feed. Each card links back to the issues behind it. |
| Report Issue | `/report` | reporter | AI re-categorization suggestion + ETA on submission. |
| Defect detail | `/issues/:id` | reporter | Issue, AI suggestions, triage result and timeline; confirm-close at `verified`. |
| Defect workspace | `/issues/:id` | maintenance, admin | The same route for the roles that work the defect: defect header, work order (start, evidence recommendation, proof upload), proof history with admin sign-off, photos and history. |
| Triage board | `/triage` | admin | Queue with confirm/override, systemic clusters, MTBF/MTTR by group. |
| Notifications | `/notifications` | all | Role- and user-targeted inbox. |

`ROUTES` in `components/Shell.jsx` is the one place that lists a page: the
sidebar, the topbar title and the router all read from it. Adding a page means
adding a row there and a `<Route>` in `App.jsx`.

`/issues/:id` is the exception: one route, two pages. `IssueRoute` in `App.jsx`
sends reporters to `IssueDetail` and everyone else to `DefectWorkspace`, because
Fix & Verify was folded into the latter — there is no separate `/fix-verify`
page, and maintenance works entirely out of Defects Management and the defect it
opens. Admins reach proofs awaiting sign-off by filtering the queue to
**Pending verification**.

## Demo-mode identity

No login. Name and role are picked in the **sidebar footer** and stored in
`localStorage` (`demo_user`, `demo_role`), then sent on every request as
`X-User` / `X-Role` (see `docs/01-architecture.md`).

Role does two things:

1. **Hides nav items** — `roles` on each `ROUTES` row. Routes themselves are not
   gated: the identity is `localStorage`, so client-side route gating would be
   theatre. Typing a URL still reaches any page.
2. **Scopes what the API returns.** This is enforced server-side, in reporting's
   `resolve_scope()`, and it is the part that actually matters:

   | Role | Sees |
   |---|---|
   | Reporter | only issues they reported |
   | Maintenance | only `in_progress`, `pending_verification`, `verified`, `closed`, `cancelled` |
   | Admin | everything |

The dashboard's status filter offers only the statuses the caller is scoped to,
derived from `scope.statuses` in the `/stats/dashboard` response rather than
from a second copy of the rule here. Switching role resets a status filter that
the new scope cannot show, so the table never reads as empty for an invisible
reason.

## Two things worth knowing before editing the Dashboard

**Where filtering happens.** The KPI tiles come from `GET /stats/dashboard`,
computed server-side over the caller's whole scoped population, so the headline
numbers are never capped by the table's `limit=500`. The filter chips then
filter the fetched rows in the browser, which is what makes them feel instant.
The two describe different sets on purpose, and the table states how many rows
it is showing.

**The SLA rule is written twice.** Server: `SLA_BREACH_DAYS` and
`SLA_SETTLED_STATUSES` in `services/reporting/app/config.py`. Client:
`slaState()` in `lib/format.js`, which decides how a row is drawn. The server is
the authority for the counts; the client mirror only exists so a row can be
tinted without a round trip. **Change both together** — a defect is in breach
when it has been open longer than 30 days and has not reached
`pending_verification`, `verified`, `closed` or `cancelled`.

Note that "open" (not `closed`/`cancelled`) and "not settled" (the SLA rule
above) are deliberately different: an issue awaiting proof is still open work,
but its repair is done, so it stops ageing towards a breach.

## Deep links

`AiInsights` links into the dashboard using the `filter` hint the insights
endpoint supplies — `/?open=1&category=lighting&q=Block%20A%20/%20L3`. Params:
`open=1` (hide closed and cancelled), `category=<enum>`, `status=<enum>`,
`q=<text>`. `status` and `category` are validated against the enums, so a stale
link degrades to no filter rather than silently matching nothing.

## Styling

`styles.css` defines the palette, radii and fonts as custom properties on
`:root` (`--accent`, `--muted`, `--border`, `--grad`, …). Use the tokens, not
hex values. The webfonts (Instrument Sans, IBM Plex Mono) load from Google
Fonts in `index.html` and fall back to the system stack offline.

The `.badge.<status>` and `.badge.<severity>` classes are used by ReportIssue,
IssueDetail, TriageBoard and Notifications — keep them when editing.
`lib/tokens.js` carries the newer chip vocabulary (`SEV`, `STATUS_COLOR`,
`STATUS_LABEL`, `CATEGORY_LABEL`, plus `WO_STATUS_*`, `URGENCY` and `VERDICT`
for the work-order enums) for the dashboard, insights and workspace pages.
