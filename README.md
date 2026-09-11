<p align="center">
  <img src="docs/assets/archetypenba-logo.jpg" alt="ArchetypeNBA Logo" width="650" style="border-radius: 20px; box-shadow: 0 12px 40px rgba(0,0,0,0.18);" />
</p>

<h1 align="center">🏀 ArchetypeNBA</h1>

<p align="center">
  <strong>Next-Generation Sports Science, AI Archetype Intelligence & Tactical Scouting Platform</strong>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Next.js-16.2.6-black?style=flat-square&logo=next.js" alt="Next.js" />
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=flat-square&logo=fastapi" alt="FastAPI" />
  <img src="https://img.shields.io/badge/PostgreSQL-16+-336791?style=flat-square&logo=postgresql" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python" alt="Python" />
  <img src="https://img.shields.io/badge/TypeScript-5.0+-3178C6?style=flat-square&logo=typescript" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Tailwind_CSS-4.0-38B2AC?style=flat-square&logo=tailwind-css" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/scikit--learn-ML_Engine-F7931E?style=flat-square&logo=scikit-learn" alt="scikit-learn" />
  <img src="https://img.shields.io/badge/Tests-61%20Passed-emerald?style=flat-square" alt="Tests" />
  <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square" alt="License" />
</p>

---

## 🌟 Overview

**ArchetypeNBA** is an enterprise-grade sports science, machine learning analytics, and tactical simulation platform built for coaches, scouting departments, analysts, and basketball enthusiasts. 

Powered by unsupervised clustering (K-Means), multi-dimensional dimensionality reduction (UMAP), Monte Carlo quantitative prop models (Negative Binomial distribution), tracking-level defensive matchups, and possession-based 5v5 simulation engines, the platform converts raw NBA data into actionable scouting intelligence across **23+ historical and modern NBA seasons (2003-04 through 2025-26, plus classic 80s and 90s championship eras)**.

---

## 🚀 Key Modules & Capabilities

### 1. 🔍 Scouting Hub & Player Lab (`/`)
- **7 Unsupervised Tactical Archetypes**: Classifies players beyond traditional 1-to-5 positions into modern tactical roles (*Dominant Volume Scorer*, *Primary Creator*, *3&D Wing*, *Stretch Big*, *Rim Protector & Anchor*, *Connector / Defensive Specialist*, *Interior Rebounder*).
- **Multi-Dimensional Radar**: Visualizes scoring, playmaking, floor spacing, perimeter defense, interior protection, and rebounding percentiles against cohort peers.
- **Automated Scouting Reports**: Generates downloadable PDF reports with tactical strengths, development areas, and shot profiles.

### 2. 🎯 Coordenadas Paralelas de Tiro (4 Zonas NBA) (`/shot-zones`)
- **Continuous Cubic Bézier Spline Curves**: Replicates professional broadcast multivariate visualizations across 4 normalized vertical axes: **Pintura (Paint)**, **Media Distancia (Mid-Range)**, **Tiro Libre (Free Throw)**, and **Triple (3-Point)**.
- **300-Player Cohort Context**: Renders ~300 active rotation players in subtle background curves to expose real league density and variance, with a central **Media de la Liga** (50th percentile) reference guideline.
- **Multi-Player Comparison**: Compare multiple players simultaneously with distinct vibrant color strokes, drop-shadow neon glows, and rank annotations (`#1`, `Top 10`, `Top 30`).
- **Tactical Presets**: One-click duel loading including *Curry vs Giannis*, *Edwards vs Brunson vs Mitchell*, *Westbrook vs DeRozan*, *Kawhi vs Harden*, and *Duren vs Cunningham*.
- **Dual Analytical Modes**: Switch between **Impacto Anotador (Score)** ($FGM \times FG\%$) and **% Acierto Puro**.

### 3. 📈 NBA Player Props & Expected Value (+EV) (`/props`)
- **Monte Carlo Quantitative Modeling**: Runs 10,000 simulations per player prop utilizing a tailored **Negative Binomial count distribution** parameterized by season averages, pace, opponent defensive rating, and volatility.
- **Consensus Line & Odds Integration**: Live lines and odds via **The Odds API** to compute exact implied probabilities and detect mathematical market inefficiencies (**Edge %** and **Expected Value +EV %**).
- **Quarter-Kelly Bankroll Sizing**: Calculates disciplined stake recommendations based on fractional Kelly Criterion.
- **Gemini AI Qualitative Layer**: Integrates contextual injury reports and lineup impact reasoning.

### 4. ⚔️ 1 vs 1 Colosseum Arena (`/versus`)
- **Career-Peak Matchups**: Head-to-head simulations of NBA legends and active superstars (e.g. *Michael Jordan '88 vs LeBron James '13*, *Shaquille O'Neal '00 vs Nikola Jokić '24*).
- **Season-by-Season Resolution**: Select any historical season with instant **`⭐ [PEAK]`** recommendation tags.
- **Accolades & Series Simulation**: Accolades comparison (MVPs, Finals MVPs, Rings, Scoring Titles, All-NBA) and 7-game playoff series probability simulation.

### 5. 🏟️ 5 vs 5 Tactical Lineup Arena (`/lineup`)
- **Aerial SVG Full Court**: Interactive basketball court with draggable tactical position nodes.
- **Championship Presets**: Pre-packaged squads including *Bulls 1995-96*, *Warriors 2016-17*, *Lakers 2000-01*, *Spurs 2013-14*, *Heat 2012-13*, *Celtics 2023-24*, *USA Dream Team*, and *World All-Time Legends*.
- **Real-Time Synergy Ratings**: Calculates ORTG, DRTG, Net Rating, Floor Spacing (0-100), Playmaking (0-100), Rebounding, and Archetype Chemistry.
- **48-Minute Possession Simulation**: Full individual Box Scores (PTS, REB, AST, STL, BLK, FG%, 3PT, FT, +/-) with quarter-by-quarter flow and MVP selection.

### 6. 🛡️ Matchups Defensivos 1v1 ("¿Quién lo para?") (`/matchups`)
- **Authentic Possession-by-Possession Tracking**: Ingests official NBA tracking matchup data to reveal individual defender performance against offensive stars.
- **Kryptonite & Mismatch Classification**: Categorizes matchups into *Kryptonite Stoppers* (drastically lower TS% and points per 75 possessions) and *Exploited Mismatches*.

### 7. ⏳ Línea del Tiempo Histórica (`/timeline`)
- **Interactive Chronological Canvas**: Explores transformative NBA eras from the 1980s Showtime/Celtics rivalry, 90s Bulls Dynasty, 2000s Kobe/Duncan/Shaq era, 2010s Heatles and Warriors dynasty, to the modern 2020s spacing and international MVP revolution.

### 8. 💰 Finanzas & Contratos NBA (`/contracts`)
- **Cap Space & Tax Aprons**: Complete salary cap analytics, second apron penalties, and contract value efficiency ratings.

### 9. 👥 Doppelgängers Históricos (`/doppelgangers`)
- **Statistical Similarity Engine**: Multi-feature Euclidean distance mapping modern players to historical counterparts sharing identical athletic and statistical fingerprints.

### 10. 🌌 Galaxia Táctica (UMAP Explorer) & 👑 Salón de la Fama (`/galaxy`, `/hall-of-fame`)
- **2D UMAP Projection**: Visualizes player transition trajectories across basketball history.
- **Hall of Fame Probability Model**: Random Forest and Logistic Regression engines predicting enshrinement probability for active players.

---

## 🛠️ Architecture & Tech Stack

```
ArchetypeNBA/
├── backend/                  # FastAPI REST API & Machine Learning Engine
│   ├── app/
│   │   ├── api/v1/          # Modular routers (shot_zones, props, matchups, versus, lineup, galaxy, hof)
│   │   ├── etl/             # Data extraction & historical season seeding
│   │   ├── models.py        # SQLModel / SQLAlchemy database schema
│   │   ├── schemas.py       # Pydantic v2 request/response models
│   │   ├── services/        # Business logic, Monte Carlo simulators, parallel zones service
│   │   └── deps.py          # Database sessions & connection pooling
│   └── tests/               # Pytest automated test suite (61 unit tests passing)
│
├── frontend/                 # Next.js 16 (App Router + Turbopack)
│   ├── src/
│   │   ├── app/             # Application routes (shot-zones, props, matchups, versus, lineup, etc.)
│   │   ├── components/      # Modular UI components (ParallelShotZonesChart, HorizontalCourt, Radar, Navbar)
│   │   ├── context/         # Preferences provider (i18n ES/EN & Metric/Imperial)
│   │   └── lib/             # Typed API clients & internationalization dictionaries
│   └── public/              # Static brand assets and logo
│
└── docs/                     # Documentation & visual assets
```

### Core Technologies
- **Backend**: Python 3.12, FastAPI, SQLModel / SQLAlchemy, PostgreSQL, psycopg, Pydantic v2, scikit-learn, UMAP, NumPy, Pandas, ReportLab.
- **Frontend**: Next.js 16.2 (Turbopack), React 19, TypeScript, Tailwind CSS v4, Lucide Icons, Canvas Confetti, Radix UI primitives.
- **Design System**: ArchetypeNBA Clean Sports Analytics System (Light-first, `#F8FAFC`, crisp slate borders, athletic orange & emerald accents).
- **Internationalization**: Dual-language support (English / Spanish) and dual unit conversions (Metric cm/kg $\leftrightarrow$ Imperial ft/lbs).

---

## ⚡ Quick Start Guide

### Prerequisites
- **Python**: `3.10+` (3.12 recommended)
- **Node.js**: `18+` (20+ recommended)
- **PostgreSQL**: `15+` with an active database connection

### 1. Database & Backend Setup

```bash
# Navigate to backend
cd backend

# Create & activate virtual environment
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables (.env in backend/)
DATABASE_URL=postgresql://user:password@localhost:5432/nba_platform

# Run database migrations
alembic upgrade head

# Launch backend server
python -m uvicorn app.main:app --reload --port 8000
```
Backend API will be live at `http://127.0.0.1:8000` (Interactive OpenAPI Swagger at `http://127.0.0.1:8000/docs`).

### 2. Frontend Setup

```bash
# Navigate to frontend
cd ../frontend

# Install dependencies
npm install

# Launch frontend dev server
npm run dev
```
Web platform will be live at `http://localhost:3000`.

---

## 🧪 Testing & Quality Assurance

The backend includes an automated test suite verifying all database repositories, ETL pipelines, similarity metrics, 1v1 matchup resolutions, shot zones calculations, prop model distributions, and 5v5 possession simulations:

```bash
cd backend
python -m pytest tests/ -v
```

```
======================= 61 passed, 1 warning in 14.22s ========================
```

---

## 📡 Key REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/shot-zones/parallel` | Retrieve 4-zone parallel coordinates data, percentiles, and ranks for top 300 players |
| `GET` | `/api/v1/shot-zones/presets` | Get curated player comparison duel presets (Curry vs Giannis, etc.) |
| `GET` | `/api/v1/props/today` | Fetch daily player props with Monte Carlo +EV simulation and Kelly bankroll stakes |
| `GET` | `/api/v1/matchups/player/{id}` | Query 1v1 defensive tracking matchups, stoppers, and mismatches |
| `GET` | `/api/v1/players` | Query players with archetype filtering, season selection, and pagination |
| `GET` | `/api/v1/players/{id}/radar` | Retrieve multi-dimensional percentile radar data |
| `GET` | `/api/v1/versus/players` | List catalog of players with available historical seasons & peak years |
| `GET` | `/api/v1/versus/matchup` | Simulate 1 vs 1 matchup with probability, radar, and 7-game series |
| `GET` | `/api/v1/lineup/presets` | Retrieve legendary pre-configured championship lineups |
| `POST` | `/api/v1/lineup/evaluate` | Evaluate 5v5 lineup chemistry, spacing, ratings, and tactical diagnosis |
| `POST` | `/api/v1/lineup/simulate` | Simulate full 48-minute game with quarter scores and Box Scores |
| `GET` | `/api/v1/timeline` | Query NBA historical timeline eras and milestones |
| `GET` | `/api/v1/galaxy/points` | Retrieve 2D UMAP projection points for all players across seasons |
| `GET` | `/api/v1/hall-of-fame/players` | List Naismith HOF enshrinees and active star induction probabilities |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
