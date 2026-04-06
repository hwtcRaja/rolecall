# RollCall — Simple Setup Guide

## Requirements
- Python 3.8+
- pip

## Setup & Run (3 steps)

```bash
# 1. Install dependencies
pip install flask flask-cors

# 2. Run the app
python app.py

# 3. Open your browser
open http://localhost:5000
```

That's it. The database is created automatically on first run.

## Demo Accounts
| Email | Password | Role |
|-------|----------|------|
| admin@horizonwest.org | admin123 | Admin (full access) |
| board@horizonwest.org | board123 | Board (read-only) |

## Files
```
rollcall-simple/
├── app.py          ← Server + all API routes
├── requirements.txt
├── rollcall.db     ← Created automatically (SQLite database)
└── static/
    └── index.html  ← Entire frontend
```

## Deploy to Railway (free)
1. Go to railway.app and sign up
2. Click "New Project" → "Deploy from GitHub"
3. Push this folder to a GitHub repo first:
   ```bash
   git init && git add . && git commit -m "init"
   gh repo create rollcall --public --push
   ```
4. Railway auto-detects Python and deploys it
5. Add environment variable: `SECRET_KEY=your-random-string`

## Deploy to Render (free)
1. Go to render.com and sign up
2. New → Web Service → connect your GitHub repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `python app.py`
5. Done — free tier keeps it running

## Production Notes
- Change `app.secret_key` in app.py to a random string
- Passwords are SHA256 hashed (fine for internal tools, use bcrypt for public-facing)
- SQLite works great for small teams; migrate to PostgreSQL if needed
