# Triage Service (:8002)

Auto-triage pipeline (severity/urgency via vLLM + hard rules, duplicate
detection, systemic-fault clustering) and macro analytics (MTBF, MTTR, location
and issue profiles). See `docs/05-triage-analytics.md`.

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8002 --reload
```
