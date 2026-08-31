# Notification Service (:8004)

In-app notification inbox. Consumes all events from the gateway fan-out and maps
them to role-/user-targeted notifications (`app/rules.py`).

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8004 --reload
```
