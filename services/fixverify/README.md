# Fix & Verify Service (:8003)

Work orders, LLM evidence recommendations, proof-of-work upload with vision-model
relevance checking (irrelevant proofs rejected with a reason), and human final
verification. See `docs/04-ai-integration.md` §5–6.

```bash
pip install -r requirements.txt
uvicorn app.main:app --port 8003 --reload
```
