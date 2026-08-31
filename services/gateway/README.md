# API Gateway (:8000)

Reverse-proxies `/api/{service}/*` to the owning service and fans out events
posted to `/events` per `app/subscriptions.py`. Aggregated `/health`.

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8000 --reload
```
