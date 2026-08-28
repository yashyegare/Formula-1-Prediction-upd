# F1 Race Predictor

A full-stack Formula 1 race prediction platform that combines machine learning with community-driven season simulations. Users can predict race outcomes using a Random Forest model trained on 70+ years of historical data, simulate entire seasons with custom scoring systems, and compete on a public leaderboard.

**Live Demo:** [https://nextjs-app-yashyegare.vercel.app/](https://nextjs-app-yashyegare.vercel.app/)

## Features

### ML Race Predictor
- Predict whether a driver will finish on the podium (P1-3), score points (P4-10), or finish outside the points (P11+)
- Random Forest classifier trained on 70+ years of F1 race data
- Considers qualifying position, driver confidence, constructor reliability, circuit characteristics, and home advantage
- 94% accuracy on validation set

### Season Simulator
- Predict entire F1 seasons with a drag-and-drop grid editor
- 20+ scoring systems (Current F1, historical, exotic like Fibonacci, Olympic Medals, Underdog)
- Monte Carlo simulation (1500 runs) for championship projections
- Head-to-head driver comparison
- Live 2026 season data with official standings
- 36+ historical seasons available (1981-2026)

### Community Leaderboard
- Sign up and submit your season predictions
- Server-side accuracy scoring against real race results
- Public leaderboard ranked by prediction accuracy
- Consensus view showing what other users predicted per race

### Draw Line Racing
- Simple canvas-based racing game where you draw your racing line
- Race along your drawn path and track lap times

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Next.js App   │────▶│   Flask Backend  │────▶│   SQLite DB     │
│   (Port 3000)   │     │   (Port 8000)    │     │   (f1_data.db)  │
│                 │     │                  │     │                 │
│ - Race Predictor│     │ - ML Model       │     │ - 36 seasons    │
│ - Docs/Presentation    │ - Auth (login)   │     │ - Race results  │
│                 │     │ - Predictions    │     │ - Standings     │
│                 │     │ - Leaderboard    │     │ - User accounts │
└─────────────────┘     │ - Season Data API│     └─────────────────┘
                        └──────────────────┘
┌─────────────────┐            │
│  Astro App      │────────────┘
│  (Port 5173)    │
│                 │
│ - Season Sim    │
│ - Drag & Drop   │
│ - Charts        │
└─────────────────┘
```

| Service | Tech | Port | Description |
|---------|------|------|-------------|
| **Frontend** | Next.js 13 + React + Tailwind | 3000 | ML predictor, docs, homepage |
| **Backend** | Python + Flask + SQLite | 8000 | ML model, auth, predictions, API |
| **Season Sim** | Astro + React + Redux | 5173 | Interactive season simulator |

## Tech Stack

### Backend
- **Python 3.14** — Core language
- **Flask** — Web framework
- **SQLite** — Database (40 seasons of F1 data, ~2MB)
- **scikit-learn** — Random Forest classifier (joblib model)
- **Flask-Login** — Session management
- **werkzeug** — Password hashing (pbkdf2:sha256)
- **Flask-CORS** — Cross-origin support

### Frontend
- **Next.js 13** — React framework (Pages Router)
- **React 18** — UI library
- **Tailwind CSS** — Styling
- **@tanstack/react-query** — Data fetching
- **html-to-image** — Export predictions as images

### Season Simulator
- **Astro** — Static site generator
- **React** — UI components
- **Redux Toolkit** — State management
- **Recharts** — Championship charts

### Data
- **Jolpica/Ergast API** — Historical F1 data (results, standings, circuits)
- **Custom SQLite DB** — Pre-seeded for instant API responses

## Local Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- npm or yarn

### 1. Clone the repository
```bash
git clone https://github.com/yashyegare/Formula-1-Prediction.git
cd Formula-1-Prediction
```

### 2. Set up the Flask backend
```bash
cd flask-app

# Install Python dependencies
pip install flask flask-cors joblib pandas flask-login

# Seed the SQLite database (one-time, ~5-8 minutes)
python seed_data.py

# Start the backend
python app.py
```

The backend runs on `http://localhost:8000`.

### 3. Set up the Next.js frontend
```bash
cd nextjs-app

# Install dependencies
npm install

# Create environment file
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local

# Start the dev server
npm run dev
```

The frontend runs on `http://localhost:3000`.

### 4. Set up the Season Simulator (optional)
```bash
cd f1-points-calc

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The Season Simulator runs on `http://localhost:5173`.

### 5. Open in browser
- **Main app:** [http://localhost:3000](http://localhost:3000)
- **Season Simulator:** [http://localhost:5173](http://localhost:5173)
- **API health check:** [http://localhost:8000/roster](http://localhost:8000/roster)

## API Endpoints

### Authentication
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/auth/signup` | POST | Register (username, email, password) |
| `/api/auth/login` | POST | Log in |
| `/api/auth/logout` | POST | Log out |
| `/api/auth/me` | GET | Current user profile |

### Predictions & Leaderboard
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/me/prediction` | GET/POST | Get/save your season prediction |
| `/api/me/prediction/lock` | POST | Lock prediction (no more edits) |
| `/api/leaderboard` | GET | Public leaderboard |
| `/api/consensus` | GET | Aggregate predictions per race |

### Season Data
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/init?year=2026` | GET | Full season data (from SQLite, <250ms) |
| `/api/circuits?year=2026` | GET | Circuit ID mapping |
| `/predictGrid` | POST | ML prediction (podium/points/out) |
| `/roster` | GET | Driver/team/GP list |

## ML Model

The Random Forest classifier is trained on historical F1 data with the following features:
- **Qualifying position** — Starting grid position
- **Driver confidence** — Percentage of races completed without DNF
- **Constructor reliability** — Team's DNF rate
- **Home advantage** — Whether driver is racing at home circuit
- **Circuit characteristics** — Track type, length, corners
- **Historical performance** — Past results at this circuit

**Output:** 3-class classification:
1. Podium finish (P1-3)
2. Points finish (P4-10)
3. Outside points (P11+)

**Accuracy:** 94% on validation set (improved from 50% baseline through feature engineering)

## Database Schema

SQLite database (`flask-app/f1_data.db`) with 8 tables:

| Table | Rows | Description |
|-------|------|-------------|
| `seasons` | 36 | One per F1 season (1981-2026) |
| `races` | ~850 | One per Grand Prix |
| `drivers` | ~800 | Driver per season |
| `constructors` | ~250 | Team per season |
| `results` | ~18,000 | Race finishing positions |
| `standings` | ~1,600 | Championship standings |
| `users` | — | Registered user accounts |
| `predictions` | — | User season predictions |
| `leaderboard` | — | Computed accuracy scores |

## Project Structure

```
Formula-1-Prediction/
├── flask-app/                  # Python backend
│   ├── app.py                  # Flask routes + ML model
│   ├── auth.py                 # Authentication (Flask-Login)
│   ├── predictions_api.py      # Predictions + leaderboard API
│   ├── database.py             # SQLite schema + queries
│   ├── seed_data.py            # Jolpica data importer
│   ├── f1_data.db              # SQLite database (~2MB)
│   ├── rffinal.pkl             # Trained Random Forest model
│   ├── id_maps.json            # Driver/GP/constructor ID mappings
│   └── current_roster.json     # Current driver-team pairings
├── nextjs-app/                 # Next.js frontend
│   ├── src/
│   │   ├── pages/              # Routes (index, calculator, leaderboard)
│   │   ├── components/         # React components
│   │   ├── lib/                # Utilities, API client
│   │   └── data/               # Points systems, season rules
│   └── package.json
├── f1-points-calc/             # Astro Season Simulator
│   ├── src/
│   │   ├── components/         # Grid, standings, charts
│   │   ├── store/              # Redux state
│   │   └── data/               # Points systems, season rules
│   └── package.json
├── model-notebooks/            # Jupyter notebooks for model training
├── reports/                    # Project reports/documentation
└── README.md
```

## Performance

| Metric | Before (API calls) | After (SQLite) |
|--------|-------------------|----------------|
| Season data load | 20-30 seconds | **<250ms** |
| First request | 20+ seconds | ~5 seconds (cache warm) |
| Subsequent requests | Cached in memory | **<250ms** (file read) |
| Data persistence | Lost on restart | **Permanent** (SQLite file) |

## Data Sources

- **Jolpica/Ergast API** — Historical F1 race results, standings, circuits
- **Formula 1 Official** — 2026 standings (includes sprint + fastest lap points)
- **Custom analysis** — Driver confidence metrics, constructor reliability scores

## Deployment

The project is deployed across two platforms:

| Service | Platform | URL |
|---------|----------|-----|
| **Next.js Frontend** | Vercel | `https://nextjs-app-yashyegare.vercel.app` |
| **Flask Backend** | Railway | `https://your-railway-app.up.railway.app` |
| **Season Simulator** | Vercel | `https://f1pointscalculator.yashyegare.com` |

### Deploy Flask Backend to Railway

1. **Push to GitHub** (the `flask-app/` directory)
2. Go to [Railway](https://railway.app) → New Project → Deploy from GitHub
3. Set the **root directory** to `flask-app`
4. Railway auto-detects the `Procfile` and `requirements.txt`
5. Add environment variables:
   - `SECRET_KEY` = (any random string, e.g. `openssl rand -hex 32`)
   - `CORS_ORIGINS` = `https://nextjs-app-yashyegare.vercel.app,https://f1pointscalculator.yashyegare.com`
6. The `f1_data.db` is committed to git — it ships with the code
7. Railway will run `gunicorn app:app` on the assigned `$PORT`

### Deploy Next.js Frontend to Vercel

1. Go to [Vercel](https://vercel.com) → New Project → Import GitHub repo
2. Set **root directory** to `nextjs-app`
3. Framework: **Next.js**
4. Add environment variable:
   - `NEXT_PUBLIC_API_URL` = `https://your-railway-app.up.railway.app`
5. Deploy — Vercel builds and hosts the frontend
6. The Next.js rewrites proxy `/api/*` → Flask backend

### Deploy Season Simulator to Vercel

1. Go to [Vercel](https://vercel.com) → New Project → Import GitHub repo
2. Set **root directory** to `f1-points-calc`
3. Framework: **Astro**
4. Add environment variable:
   - `PUBLIC_API_BASE_URL` = `https://your-railway-app.up.railway.app`
5. Build command: `npm run build`
6. Output directory: `dist`

### After Deployment

Update the CORS origins in Railway to include your actual Vercel URLs:
```
CORS_ORIGINS=https://nextjs-app-xxx.vercel.app,https://f1pointscalculator-xxx.vercel.app
```

### How It Works in Production

```
User → Vercel (Next.js) → /api/* rewrites → Railway (Flask) → SQLite
User → Vercel (Astro)  → direct fetch     → Railway (Flask) → SQLite
```

- **SQLite database** ships with the code (~2MB) — no external database needed
- **Auth** uses Flask-Login sessions — cookies work cross-origin with `supports_credentials`
- **ML model** (`rffinal.pkl`) loads once at startup — gunicorn workers share it

## Developed By

[Yash Yegare](https://github.com/yashyegare)

## License

MIT License
