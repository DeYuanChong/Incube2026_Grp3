# Reporting Service (:8001)

Source of truth for issues: intake, smart categorization (vLLM suggestion, user
never overridden), ETA estimation from live backlog, and the full status state
machine. See `docs/02-data-model.md` and `docs/03-api-contracts.md`.

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8001 --reload
```
