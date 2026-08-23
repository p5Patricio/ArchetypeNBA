<p align="center">
  <img src="docs/assets/archetypenba-logo.jpg" alt="ArchetypeNBA Logo" width="600" style="border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.15);" />
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
  <img src="https://img.shields.io/badge/License-MIT-blue?style=flat-square" alt="License" />
</p>

---

## 🌟 Overview

**ArchetypeNBA** is an enterprise-grade analytics, sports science, and tactical simulation platform built for coaches, scouts, analysts, and basketball enthusiasts. Powered by unsupervised clustering (K-Means), multi-dimensional dimensionality reduction (UMAP), predictive Hall of Fame modeling, and possession-based game simulation engines, it transforms raw NBA statistics into actionable scouting intelligence across **23+ historical and active seasons (2003-04 through 2025-26, plus classic 80s/90s championship eras)**.

---

## 🚀 Key Modules & Capabilities

### 1. 🔍 Scouting Hub & Player Lab
- **7 Unsupervised Tactical Archetypes**: Reclassifies players beyond traditional 1-to-5 positions into modern tactical roles (*Dominant Volume Scorer*, *Primary Creator*, *3&D Wing*, *Stretch Big*, *Rim Protector & Anchor*, *Connector / Defensive Specialist*, *Interior Rebounder*).
- **Multi-Dimensional Radar**: Visualizes scoring, playmaking, floor spacing, perimeter defense, interior protection, and rebounding percentiles against cohort peers.
- **Automated Scouting Reports**: Generates downloadable PDF reports with tactical strengths, development areas, and shot profiles.

### 2. ⚔️ 1 vs 1 Colosseum Arena
- **Career-Peak Matchups**: Head-to-head simulations of NBA legends and current superstars (e.g. *Michael Jordan '88 vs LeBron James '13*, *Shaquille O'Neal '00 vs Nikola Jokić '24*).
- **Season-by-Season Resolution**: Users can select any historical season with instant **`⭐ [PEAK]`** recommendation tags.
- **Accolades & Series Simulation**: Accolades comparison (MVPs, Finals MVPs, Rings, Scoring Titles, All-NBA) and 7-game playoff series probability simulation.

### 3. 🏟️ 5 vs 5 Tactical Lineup Arena (Fantasy Builder)
- **Aerial SVG Full Court**: Interactive 940x500 basketball court in clean white/orange/blue aesthetics with 10 draggable tactical position nodes.
- **1-Click Classic Presets**: Pre-packaged championship squads including *Chicago Bulls 1995-96*, *Golden State Warriors 2016-17*, *Los Angeles Lakers 2000-01*, *San Antonio Spurs 2013-14*, *Miami Heat 2012-13*, *Boston Celtics 2023-24*, *USA Dream Team*, and *World All-Time Legends*.
- **Real-Time Synergy & Spacing Ratings**: Calculates ORTG, DRTG, Net Rating, Floor Spacing (0-100), Playmaking (0-100), Rebounding, and Archetype Chemistry.
- **48-Minute Game Simulation & Full Box Score**: Possession model projecting final scores, quarter breakdowns, MVP selection, and full individual Box Scores (PTS, REB, AST, STL, BLK, FG%, 3PT, FT, +/-).

### 4. 🌌 Tactical Galaxy (2D UMAP Explorer)
- Interactive 2D projection of NBA player spatial distributions, visualizing similarity neighborhoods and transition patterns across basketball eras.

### 5. 👑 Hall of Fame Predictor & Historical Registry
- **Predictive ML Modeling**: Logistic Regression & Random Forest models computing real-time enshrinement probability for active players based on accolades, statistical milestones, and peak win shares.
- **Naismith Memorial HOF Registry**: Complete database of all-time enshrined legends.

### 6. 🛡️ NBA Franchises & Roster Intelligence
- In-depth scouting for all 30 NBA teams, featuring depth charts, cap distribution, archetype balance, and offensive/defensive ratings.

---

## 🛠️ Architecture & Tech Stack

```
Clasificador_Entrenador-NBA/
├── backend/                  # FastAPI REST API & Machine Learning Engine
│   ├── app/
│   │   ├── api/v1/          # Modular API endpoints (players, versus, lineup, galaxy, hof)
│   │   ├── etl/             # Data extraction & historical season seeding
│   │   ├── models.py        # SQLModel / SQLAlchemy database schema
│   │   ├── schemas.py       # Pydantic v2 request/response models
│   │   ├── services/        # Business logic & simulation engines
│   │   └── deps.py          # Database sessions & connection pooling
│   └── tests/               # Pytest automated test suite (37 unit tests)
│
├── frontend/                 # Next.js 16 (App Router + Turbopack)
│   ├── src/
│   │   ├── app/             # Application routes (scouting, versus, lineup, galaxy, hof)
│   │   ├── components/      # Modular UI components (HorizontalCourt, Radar, Navbar)
│   │   ├── context/         # Preferences provider (i18n ES/EN & Metric/Imperial)
│   │   └── lib/             # API client & internationalization dictionaries
│   └── public/              # Static assets and brand imagery
│
└── docs/                     # Documentation & visual assets
```

### Core Technologies
- **Backend**: Python 3.12, FastAPI, SQLModel / SQLAlchemy, PostgreSQL, psycopg, Pydantic v2, scikit-learn, UMAP, NumPy, Pandas, ReportLab.
- **Frontend**: Next.js 16.2 (Turbopack), React 19, TypeScript, Tailwind CSS v4, Lucide Icons, Canvas Confetti, Radix UI primitives.
- **Internationalization & Units**: Dual-language support (English / Spanish) and dual unit conversions (Metric cm/kg $\leftrightarrow$ Imperial ft/lbs).

---

## ⚡ Quick Start Guide

### Prerequisites
- **Python**: `3.10+` (3.12 recommended)
- **Node.js**: `18+` (20+ recommended)
- **PostgreSQL**: `15+` with active database connection

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

# Configure environment variables
# Create .env inside backend/
DATABASE_URL=postgresql://user:password@localhost:5432/nba_platform

# Run database migrations / seed initial historical rosters
python -m app.etl.seed_bulls_1996

# Launch backend development server
python -m uvicorn app.main:app --reload --port 8000
```
Backend API will be live at `http://127.0.0.1:8000` (Interactive Swagger docs at `http://127.0.0.1:8000/docs`).

### 2. Frontend Setup

```bash
# Navigate to frontend
cd ../frontend

# Install dependencies
npm install

# Launch frontend with Turbopack
npm run dev
```
Web platform will be live at `http://localhost:3000`.

---

## 🧪 Testing & Quality Assurance

The backend includes a comprehensive automated test suite verifying all database repositories, ETL pipelines, similarity metrics, 1v1 matchup resolutions, and 5v5 possession simulations:

```bash
cd backend
python -m pytest tests/ -v
```

```
======================== 37 passed, 1 warning in 0.85s ========================
```

---

## 📡 Key REST API Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/players` | Query players with archetype filtering, season selection, and pagination |
| `GET` | `/api/v1/players/{id}/radar` | Retrieve multi-dimensional percentile radar data |
| `GET` | `/api/v1/versus/players` | List catalog of players with available historical seasons & peak years |
| `GET` | `/api/v1/versus/matchup` | Simulate 1 vs 1 matchup with probability, radar, and 7-game series |
| `GET` | `/api/v1/lineup/presets` | Retrieve 8 legendary pre-configured championship lineups |
| `POST` | `/api/v1/lineup/evaluate` | Evaluate 5v5 lineup chemistry, spacing, ratings, and tactical diagnosis |
| `POST` | `/api/v1/lineup/simulate` | Simulate full 48-minute game with quarter scores and Box Scores |
| `GET` | `/api/v1/galaxy/points` | Retrieve 2D UMAP projection points for all players across seasons |
| `GET` | `/api/v1/hall-of-fame/players` | List Naismith HOF enshrinees and active star induction probabilities |

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
