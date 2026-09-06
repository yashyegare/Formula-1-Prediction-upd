# F1 Race Predictor

Full-stack Formula 1 prediction platform: an ML race predictor, an interactive season simulator, and a community leaderboard — three apps sharing one Flask API.

| App | Stack | Live |
|-----|-------|------|
| Race Predictor | Next.js 15 · React 18 · Tailwind | [nextjs-app-yashyegare.vercel.app](https://nextjs-app-yashyegare.vercel.app/) |
| Season Simulator | Astro 5 · React · Redux Toolkit | [f1pointscalculator.yashyegare.com](https://f1pointscalculator.yashyegare.com) |
| Backend API | Flask · PostgreSQL/SQLite · scikit-learn | [f1-predictor-api-nddf.onrender.com](https://f1-predictor-api-nddf.onrender.com/health) |

## Features

- **ML Race Predictor** — Random Forest classifier (94% validation accuracy) trained on 70+ years of F1 data; predicts podium / points / outside-points from qualifying position, driver form, constructor reliability, and circuit history.
- **Season Simulator** — drag-and-drop full-season grid editor, 20+ scoring systems (Current, 90s, Fibonacci, Olympic Medals…), Monte Carlo championship projections (1,500 runs), historical seasons from 1981–2026.
- **Community Leaderboard** — accounts with server-side session auth, predictions locked per season, accuracy scored against real results, public leaderboard and per-race consensus.
- **Draw Line Racing** — canvas mini-game: draw a racing line, race it, compare lap times.

## Architecture

```
Next.js (Vercel)  ── rewrites /api/* ──┐
                                       ▼
Season Simulator (Vercel) ── fetch ──▶ Flask API (Render) ──▶ PostgreSQL / SQLite
                                       │
                                       └──▶ rffinal.pkl (Random Forest, loaded at boot)
```

- Sessions are cross-origin cookies (`SameSite=None; Secure`); state-changing requests are CSRF-guarded via Origin verification.
- Auth endpoints are rate-limited (flask-limiter) and return JSON 429s.
- With `DATABASE_URL` set, data persists on PostgreSQL; without it, SQLite is used (ephemeral on Render free tier).

## Quick Start

Prerequisites: Python 3.10+, Node 18+.

```bash
git clone https://github.com/yashyegare/Formula-1-Prediction-upd.git
cd Formula-1-Prediction-upd

# Backend (http://localhost:8000)
cd flask-app
pip install -r requirements.txt
python seed_data.py        # one-time, ~5-8 min
python app.py

# Race Predictor (http://localhost:3000)
cd ../nextjs-app
npm install
npm run dev

# Season Simulator (http://localhost:5173)
cd ../f1-points-calc
npm install
npm run dev
```

Frontend env vars (optional locally — both default to `localhost:8000`): `NEXT_PUBLIC_API_URL` (Next.js), `PUBLIC_API_BASE_URL` (Astro).

## Environment Variables (Render backend)

| Variable | Required | Purpose |
|----------|----------|---------|
| `SECRET_KEY` | **Yes** | Signs session cookies. Unset = new key every restart = all users silently logged out. Generate: `openssl rand -hex 32`. |
| `CORS_ORIGINS` | **Yes (prod)** | Comma-separated frontend origins; drives both CORS and the CSRF Origin check. |
| `DATABASE_URL` | Recommended | PostgreSQL URL. Without it, SQLite is ephemeral on Render free tier — accounts wiped on every deploy. Schema auto-creates on first boot. |
| `RATELIMIT_STORAGE_URI` | Optional | Redis URL for shared rate-limit counters (multi-worker only). |
| `F1_DB_PATH` | Test-only | SQLite location override used by the test suite. |

Example:

```
SECRET_KEY=<openssl rand -hex 32>
CORS_ORIGINS=https://nextjs-app-yashyegare.vercel.app,https://f1pointscalculator.yashyegare.com,https://formula-1-prediction-upd-fxzg.vercel.app
DATABASE_URL=postgres://<user>:<password>@<host>/<db>
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/signup` · `/login` · `/logout` | POST | Account + session management |
| `/api/auth/me` | GET | Current user |
| `/api/auth/profile` | GET/PUT/DELETE | Profile with prediction history / update display name / delete account |
| `/api/auth/forgot-password` · `/reset-password` | POST | Password reset (token flow) |
| `/api/me/prediction` | GET/POST | Get/save season prediction |
| `/api/me/prediction/lock` | POST | Lock prediction |
| `/api/leaderboard` · `/api/consensus` | GET | Leaderboard / per-race consensus |
| `/api/init?year=2026` | GET | Full season data (<250ms, served from SQLite) |
| `/predictGrid` · `/roster` | POST/GET | ML prediction / driver roster |

## Testing & CI

- `flask-app/tests/` — 90 pytest tests covering auth, cookies, password reset, rate limiting, CSRF, profile endpoints (incl. display-name injection regressions), prediction scoring, and the auth contracts of both prediction endpoint families (`python -m pytest tests/ -q`). CI runs the suite against **both SQLite and PostgreSQL**, so the dual-backend query paths are exercised on every push.
- `model-notebooks/tests/` — 20 pytest tests pinning the ML training pipeline: `position_index()` bucket boundaries, the quali-vs-finish leakage fix, DNF detection, and an end-to-end train/predict run matching `/predictGrid`'s inference contract.
- `f1-points-calc/tests/` — 125 vitest tests covering the scoring engine (points systems, half/double points, dropped scores, DSQ overrides), grid drag-and-drop reducers, standings/chart selectors, auth client (timeouts, 429s), and UI primitives (`npm test`).
- `nextjs-app/src/lib/auth.test.ts` — 16 vitest tests for the auth client (error mapping, timeouts, non-JSON responses) (`npm test`).
- GitHub Actions CI runs all four test suites, builds all three apps, audits dependencies (`pip-audit` + `npm audit --omit=dev`), and auto-deploys the backend on green main pushes.

## ML Model

Random Forest (scikit-learn, `rffinal.pkl`) trained on historical race data with feature engineering (qualifying position, driver confidence, constructor reliability, home advantage, circuit characteristics). 3-class output: podium / points / outside points — 94% validation accuracy, up from a 50% baseline. Training notebooks live in `model-notebooks/`.

## Deployment

| Service | Platform | Notes |
|---------|----------|-------|
| `nextjs-app/` | Vercel | Root dir `nextjs-app`, framework Next.js |
| `f1-points-calc/` | Vercel | Root dir `f1-points-calc`, framework Astro, build `npm run build`, output `dist` |
| `flask-app/` | Render | Root dir `flask-app`, start `gunicorn app:app`; **auto-deploys** on green main pushes via the CI `deploy-render` job (set the `RENDER_DEPLOY_HOOK_URL` repo secret; manual Dashboard deploy remains as fallback) |

A keep-alive workflow (`.github/workflows/keep-alive.yml`) pings `/health` every 10 minutes to avoid Render free-tier cold starts.

## Author

[Yash Yegare](https://github.com/yashyegare) · MIT License
