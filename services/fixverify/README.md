# Fix & Verify Service (:8003)

Work orders, LLM evidence recommendations, and proof-of-work upload with
vision-model relevance checking. Upload is two-step: it stores a draft and runs
the check, then the uploader confirms or cancels — an `irrelevant` proof can be
overridden into human sign-off (flagged `ai_overridden`). An admin makes the
final call. See `docs/04-ai-integration.md` §5–6.

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8003 --reload
```
