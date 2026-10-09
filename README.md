# FinMentor

FinMentor is a private personal-finance Q&A agent. You upload your own statements, ask in chat, and it answers **only** from retrieved chunks of those files. If similarity is below the threshold, it returns a fixed refusal and does not call the language model.

The numbers in `samples/` are fictional. Do not put real account numbers in this project.

Full architecture, API, dummy responses, and measured metrics: **[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)**.

## Run locally (Python 3.12+)

From the **repository root**:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r finmentor/requirements.txt
copy finmentor\.env.example finmentor\.env
$env:PYTHONPATH = (Get-Location).Path
uvicorn finmentor.main:app --reload --host 127.0.0.1 --port 8000
```

Leave `SUPABASE_URL` as the example host to use **demo mode** (no live database):

- Email: `demo@finmentor.app`
- Password: `Demo@12345`

For production: create a Supabase project, run `finmentor/db/migrations.sql`, `migrations_auth.sql`, then `migrations_chat.sql`. Fill `.env` with real keys (`SUPABASE_ANON_KEY` is required for Auth).
