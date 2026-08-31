# Frontend (:5173)

React (Vite) app. All API calls go through the gateway (`VITE_GATEWAY_URL`,
default `http://localhost:8000`). Demo-mode identity: pick a name and role in
the top-right — sent as `X-User` / `X-Role` headers.

Pages: Dashboard (live issue tracking), Report Issue (with AI recategorization
suggestion + ETA), Triage board (admin), Fix & Verify (maintenance/admin),
Notifications.

```bash
npm install
npm run dev
```
