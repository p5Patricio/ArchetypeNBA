> **Status: historical (April 2026).** This is the proposal written before the PostgreSQL migration. The system that was actually built is described in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); the decisions behind it are in [`docs/DECISIONS.md`](docs/DECISIONS.md). The content below is kept unchanged for context.

# NBA Analytics Platform — Database & Backend Architecture Report

> **Date:** 2026-04-29  
> **Scope:** Migrate from in-memory Excel-backed FastAPI prototype to a production-ready NBA analytics platform.  
> **Current Stack:** FastAPI + pandas + scikit-learn + Excel files + `nba_api` + Next.js frontend.

---

## Executive Summary

The current backend uses a `DataContext` singleton that loads Excel files into memory and runs K-Means clustering on demand. This works for a single-season demo but blocks multi-season analysis, player comparisons, game-level insights, and concurrent usage. The report below recommends a **PostgreSQL** database, **SQLModel** ORM, a **Repository + Service** layer architecture, and a phased rollout of new analytics endpoints and ML models.

---

## 1. Database Choice

### Recommendation: **PostgreSQL** (primary) + **SQLite** (local dev / CI only)

| Criterion | PostgreSQL | SQLite | Others (MongoDB, MySQL) |
|-----------|------------|--------|------------------------|
| **Relational fit** | Excellent — joins across players, teams, games, box scores are natural and fast with proper indexing. | Good for single-user local dev. | MySQL is acceptable; MongoDB adds unnecessary complexity for normalized stats. |
| **JSON flexibility** | `JSONB` columns allow storing variable shot-chart metadata, play-by-play events, and raw API responses while keeping relational core. | JSON support exists but no `JSONB` indexing. | MongoDB is schemaless, but you lose ACID transactions across documents. |
| **Complex queries** | Window functions, CTEs, advanced aggregations (rankings, rolling averages) are first-class. | Limited window-function support in older versions. | MySQL 8+ is fine; MariaDB less ideal for analytics. |
| **Time-series / game data** | **TimescaleDB** extension turns game logs and play-by-play into high-performance hypertables. | Not applicable. | InfluxDB is overkill unless you stream real-time sensor data. |
| **Local dev** | Docker one-liner; slight overhead. | Zero-config; perfect for unit tests. | — |
| **Production hosting** | Managed on AWS RDS, Google Cloud SQL, DigitalOcean, Heroku, etc. | Not recommended for production web APIs. | — |
| **Python ecosystem** | `asyncpg` + SQLAlchemy/SQLModel async support is mature. | `aiosqlite` works but is slower under concurrency. | — |

### Why not stick with Excel/CSV?
- No concurrent writes, no ACID, full-table scans in memory, impossible to query across seasons efficiently.

### Suggested connection string strategy
```python
# .env
DATABASE_URL="postgresql+asyncpg://user:pass@localhost/nba_analytics"
TEST_DATABASE_URL="sqlite+aiosqlite:///./test.db"
```

---

## 2. Schema Design

### Design Principles
1. **Normalize the core**, **denormalize for reads** (materialized views or cache for leaderboards).
2. Use `JSONB` sparingly — only for API responses or attributes that change shape (e.g., play-by-play events).
3. Keep `nba_api` IDs (`PLAYER_ID`, `TEAM_ID`, `GAME_ID`) as natural keys to simplify ETL.

### Core Tables

```
players
├── id (PK, int) — NBA API PLAYER_ID
├── full_name (str)
├── first_name, last_name
├── birthdate (date)
├── height, weight
├── position (str)
├── jersey_number (str, nullable)
├── is_active (bool)
├── headshot_url (str, generated)
├── created_at, updated_at

teams
├── id (PK, int) — NBA API TEAM_ID
├── abbreviation (str, unique)
├── full_name, city, state, year_founded
├── conference, division
├── logo_url (str)

seasons
├── id (PK, serial)
├── season_label (str, e.g. "2024-25", unique)
├── start_date, end_date (date)
├── is_current (bool)

player_season_stats  (one row per player per team per season)
├── id (PK, serial)
├── player_id (FK → players)
├── team_id (FK → teams)
├── season_id (FK → seasons)
├── season_type (Enum: REGULAR, PLAYOFFS, PRESEASON)
├── gp, gs, min
├── fgm, fga, fg_pct
├── fg3m, fg3a, fg3_pct
├── ftm, fta, ft_pct
├── oreb, dreb, reb
├── ast, stl, blk, tov, pf, pts
├── plus_minus (nullable)
├── ts_pct, efg_pct, usg_pct (advanced, nullable)
├── per, vorp, ws (nullable — calculated post-ingest)
├── cluster_id (FK → clusters, nullable)

player_game_logs  (granular per-game stats)
├── id (PK, serial)
├── player_id (FK)
├── game_id (FK → games)
├── team_id (FK)
├── minutes (int)
├── fgm ... pts (same stat cols as above)
├── plus_minus
├── is_starter (bool)

games
├── id (PK, str) — NBA API GAME_ID
├── season_id (FK)
├── season_type (Enum)
├── game_date (date)
├── home_team_id (FK)
├── away_team_id (FK)
├── home_score, away_score
├── home_q1 ... away_q4 (quarter scores, nullable)
├── attendance, arena (nullable)
├── is_finished (bool)

team_season_stats
├── id (PK, serial)
├── team_id (FK)
├── season_id (FK)
├── season_type (Enum)
├── wins, losses
├── off_rating, def_rating, net_rating (nullable)
├── pace (nullable)

game_box_scores  (team-level per game)
├── id (PK, serial)
├── game_id (FK)
├── team_id (FK)
├── is_home (bool)
├── fgm ... pts
├── team_reb, team_tov, fast_break_pts (nullable)

shot_charts  (can be huge — consider partitioning by season)
├── id (PK, serial)
├── player_id (FK)
├── game_id (FK, nullable)
├── season_id (FK)
├── loc_x, loc_y (float)
├── shot_distance (float)
├── shot_made (bool)
├── action_type (str)
├── shot_zone_basic, shot_zone_area, shot_zone_range (str)

clusters  (model versioning)
├── id (PK, serial)
├── model_version (str)
├── season_id (FK, nullable)
├── season_type (Enum)
├── k (int)
├── stats_columns (JSONB) — which features were used
├── created_at

cluster_assignments
├── id (PK, serial)
├── cluster_id (FK)
├── player_season_stat_id (FK)
├── cluster_label (int)
├── cluster_role (str) — e.g. "Anotador de Volumen"
├── distance_to_center (float, nullable)

player_similarity  (pre-computed or on-demand)
├── id (PK, serial)
├── source_player_id (FK)
├── target_player_id (FK)
├── season_id (FK)
├── similarity_score (float) — cosine or correlation
├── method (str) — "cosine", "euclidean", "pearson"
```

### Indexes to Create Early
- `player_season_stats`: composite `(season_id, season_type, min DESC)` for leaderboards.
- `player_game_logs`: `(player_id, game_id)`, `(game_id)`.
- `shot_charts`: `(player_id, season_id)`, `(game_id)` — BRIN or B-tree depending on partition strategy.
- `games`: `(game_date)`, `(season_id, season_type)`.

### Views / Materialized Views
- `v_leaderboard_pts`: pre-aggregated top scorers per season (refresh after ETL).
- `v_team_standings`: wins/losses per team per season.
- `v_player_advanced`: joins `player_season_stats` with calculated PER/VORP.

---

## 3. ORM Choice

### Recommendation: **SQLModel** (primary) + **SQLAlchemy 2.0** (escape hatch)

| Factor | SQLModel | SQLAlchemy 2.0 | Raw SQL |
|--------|----------|----------------|---------|
| **FastAPI integration** | Native — same class serves as DB model, Pydantic schema, and OpenAPI doc. | Good, but requires manual Pydantic schema duplication. | None — you write all validation manually. |
| **Learning curve** | Low if you know Pydantic. | Medium — declarative base, session management. | High maintenance overhead. |
| **Async support** | Full via SQLAlchemy 2.0 async under the hood. | Full with `async_sessionmaker`. | Possible with `asyncpg` directly, but verbose. |
| **Complex analytics queries** | Can fall short on raw aggregation performance vs pure SA. | Best for raw SQL expression language, window functions, CTEs. | Fastest execution, worst maintainability. |
| **Migrations** | Works with **Alembic** (same as SA). | Works with Alembic. | You manage schema drift manually. |

### Proposed Pattern
```python
# models.py
from sqlmodel import SQLModel, Field, Relationship

class Player(SQLModel, table=True):
    __tablename__ = "players"
    id: int = Field(primary_key=True)
    full_name: str
    player_season_stats: list["PlayerSeasonStat"] = Relationship(back_populates="player")

# For complex aggregations that SQLModel syntax obscures, drop to SQLAlchemy select()
from sqlalchemy import select, func
from sqlmodel.ext.asyncio.session import AsyncSession

async def get_leaderboard(session: AsyncSession, season_id: int):
    stmt = (
        select(PlayerSeasonStat.player_id, func.sum(PlayerSeasonStat.pts).label("total_pts"))
        .where(PlayerSeasonStat.season_id == season_id)
        .group_by(PlayerSeasonStat.player_id)
        .order_by(func.sum(PlayerSeasonStat.pts).desc())
        .limit(50)
    )
    result = await session.exec(stmt)
    return result.all()
```

### Tradeoff Summary
- Start with **SQLModel** for 90% of CRUD and schema definition.
- Use **SQLAlchemy Core/ORM expressions** inside repositories for heavy analytics.
- Avoid raw SQL strings except for one-off data-science notebooks.

---

## 4. ETL Pipeline — Ingesting from `nba_api`

### Current Pain Points
- `nba_player_data.py` iterates **synchronously** over ~500 active players with `time.sleep(0.5)` → ~4–5 minutes per run.
- No retry logic, no partial-failure handling, writes directly to Excel.
- No incremental updates: every run fetches every player.

### Recommended Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌──────────────┐
│  Scheduler  │────▶│  Celery Worker  │────▶│  PostgreSQL  │
│  (cron/AP)  │     │  (or FastAPI    │     │  (analytics  │
│             │     │   Background)   │     │   DB)        │
└─────────────┘     └─────────────────┘     └──────────────┘
                           │
                           ▼
                    ┌──────────────┐
                    │   nba_api    │
                    │  (throttled) │
                    └──────────────┘
```

### Implementation Strategy

1. **Rate Limiting & Throttling**
   - `nba_api` endpoints are heavily rate-limited by the NBA CDN.
   - Use `asyncio.Semaphore(3)` or **Celery** with `rate_limit="10/m"`.
   - Wrap calls in `tenacity` retry with exponential backoff (`HTTP 429`, timeouts).

2. **Batch Jobs by Domain**
   | Job | Frequency | Endpoint |
   |-----|-----------|----------|
   | Player roster sync | Daily | `static/players` |
   | Team standings | Daily | `leaguestandings` |
   | Season stats | Weekly | `playercareerstats` |
   | Game logs | Nightly (post-games) | `playergamelogs` |
   | Shot charts | Weekly / on-demand | `shotchartdetail` |
   | Play-by-play | On-demand / nightly | `playbyplayv2` |

3. **Incremental Ingestion**
   - Store `last_synced_at` per entity type.
   - For game logs: only fetch games where `game_date > last_synced_at`.
   - Use `UPSERT` (`INSERT ... ON CONFLICT DO UPDATE`) to handle duplicates idempotently.

4. **Async Architecture**
   - **Phase 1 (MVP):** FastAPI `BackgroundTasks` for lightweight updates (e.g., single-player shot chart).
   - **Phase 2 (Production):** **Celery + Redis/RabbitMQ** for heavy season-wide ETL. Prevents API timeout and supports retries.

5. **Data Quality Checks**
   - After each batch, run validation: `SUM(home_score) = SUM(home_team_box_pts)`, player minutes per game ≤ 65, etc.
   - Log anomalies to a `etl_audit_log` table rather than failing silently.

### Python Stack Additions
```
celery>=5.4
redis>=5.0
tenacity>=9.0
alembic>=1.13
sqlmodel>=0.0.21
asyncpg>=0.29
```

---

## 5. Backend Restructuring — Replacing DataContext

### Current Problem
- `DataContext` is a **global mutable singleton** holding pandas DataFrames, scaler, and K-Means model.
- Not thread-safe, resets on every deploy, cannot share state across workers, blocks true REST semantics.

### Target Architecture: Dependency Injection + Repository + Service

```
┌─────────────┐
│   Routes    │  ← FastAPI APIRouter, no business logic
│  (api/v1/)  │
└──────┬──────┘
       │
┌──────▼──────┐
│  Services   │  ← Business logic: clustering, analytics, PDF gen
│  (domain)   │
└──────┬──────┘
       │
┌──────▼──────┐
│ Repositories│  ← DB access, query construction
│  (infra)    │
└──────┬──────┘
       │
┌──────▼──────┐
│   Models    │  ← SQLModel tables
│   (DB)      │
└─────────────┘
```

### Code Sketch

```python
# db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

DATABASE_URL = "postgresql+asyncpg://..."
engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

# repositories/player.py
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

class PlayerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_name(self, name: str) -> Player | None:
        stmt = select(Player).where(Player.full_name == name)
        result = await self.session.exec(stmt)
        return result.first()

    async def list_by_team_season(self, team_id: int, season_id: int):
        ...

# services/clustering.py
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import pandas as pd

class ClusteringService:
    def __init__(self, player_repo: PlayerRepository):
        self.player_repo = player_repo

    async def fit_season(self, season_id: int, k: int = 5):
        rows = await self.player_repo.get_stats_df(season_id)
        scaler = StandardScaler()
        scaled = scaler.fit_transform(rows[STATS_COLS])
        model = KMeans(n_clusters=k, random_state=42, n_init=10)
        labels = model.fit_predict(scaled)
        # Persist to cluster_assignments table
        return labels

# api/v1/players.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/players", tags=["players"])

@router.get("/{player_id}/analysis")
async def analyze_player(
    player_id: int,
    db: AsyncSession = Depends(get_db),
):
    player_repo = PlayerRepository(db)
    service = AnalysisService(player_repo)
    return await service.generate_analysis(player_id)
```

### What happens to the existing DataContext?
- **Eliminate** the global singleton.
- For the clustering model (scikit-learn), either:
  1. **Train on demand** (fast enough for <600 players), or
  2. **Serialize** the fitted `KMeans` + `StandardScaler` to `joblib` files or a `models` table (blob), then load per-request.
- The pandas DataFrames currently used for analysis should be replaced by **SQL queries** or **pandas read_sql** calls inside services.

---

## 6. New Endpoints Needed

### Current Endpoints (baseline)
- `GET /health`
- `POST /cluster/init`
- `GET /teams`
- `GET /players?team=...`
- `GET /player/{name}/analysis`
- `GET /player/{name}/report`
- `GET /player/{name}/profile`
- `GET /player/{name}/shots`
- `GET /player/{name}/radars`
- `POST /data/update`

### Recommended New Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/players` | `GET` | **Search** with filters: `?q=LeBron&team=LAL&season=2024-25&min_pts=20`. Returns paginated list with basic stats. |
| `/players/{id}/profile` | `GET` | Rich player profile: bio, career trajectory, current contract (if available), injury status stub. |
| `/players/{id}/career` | `GET` | Career stat lines per season (for trend charts). |
| `/players/{id}/compare` | `POST` | Body: `{target_player_id, season_id, stats[]}`. Returns head-to-head comparison deltas and radar data. |
| `/players/{id}/similar` | `GET` | Most similar players by stat profile (cosine similarity or pre-computed table). |
| `/teams` | `GET` | List teams with current season record, ranking, net rating. |
| `/teams/{id}` | `GET` | Team profile: roster, coach, arena, standings, recent form. |
| `/teams/{id}/stats` | `GET` | Aggregated team stats for a season (offensive/defensive rating, pace). |
| `/teams/{id}/schedule` | `GET` | Upcoming / past games with results. |
| `/games` | `GET` | List games: `?season=2024-25&team_id=1610612747&date_from=...`. |
| `/games/{id}` | `GET` | Box score, play-by-play summary, win probability graph data. |
| `/games/{id}/win-probability` | `GET` | Pre-computed or on-demand win probability timeline (0–48 min). |
| `/leaderboards` | `GET` | `?category=pts&season=2024-25&season_type=REGULAR`. Top N players per stat. Supports `per_game` and `total`. |
| `/leaderboards/teams` | `GET` | Team standings / rankings by net rating, offense, defense. |
| `/analytics/cluster` | `POST` | Trigger clustering for a season (replaces `/cluster/init`). Returns job ID. |
| `/analytics/cluster/{id}` | `GET` | Cluster results: centroids, player assignments, roles. |
| `/analytics/elo` | `GET` | Current Elo ratings for all teams. |
| `/analytics/elo/history` | `GET` | Elo timeline for a team: `?team_id=...`. |
| `/search` | `GET` | Global typeahead: `?q=Curry` returns players + teams + games. |

### Pagination & Filtering Standards
- Use **cursor pagination** for leaderboards (fast, stable ordering).
- Use **offset pagination** for admin/search UIs (user-friendly).
- Standard query params: `limit`, `cursor`, `season`, `season_type`, `team_id`, `date_from`, `date_to`.

---

## 7. ML / Analytics Models

### Feasibility Matrix

| Model | Complexity | Data Needed | Feasibility | Value |
|-------|-----------|-------------|-------------|-------|
| **K-Means Clustering** (existing) | Low | Season avg stats | ✅ Done | Player archetypes, role labels |
| **Win Probability (in-game)** | Medium | Play-by-play + point spread | ✅ High | Engagement, game narratives |
| **Pre-game Win Probability** | Medium | Team stats, Elo, rest days | ✅ High | Predictions, betting context |
| **Elo Ratings** | Low | Game results only | ✅ High | Team strength over time |
| **Player Similarity** | Low | Season stat vectors | ✅ High | Comparisons, scouting |
| **PER / VORP / WS** | Medium | Box score + team pace | ✅ Medium | Standard advanced metrics |
| **Player Projections** | High | Multi-season trajectories + age curves | ⚠️ Medium | Fantasy, contract valuation |
| **Play-by-play Expected Points** | High | Shot location + defender distance | ⚠️ Hard | Requires SportVU / tracking data |

### Detailed Recommendations

#### 7.1 Win Probability Model
- **Approach:** Logistic Regression or XGBoost with features:
  - `time_remaining` (seconds)
  - `score_differential`
  - `has_possession` (boolean)
  - `home_court` (boolean)
  - `pre_game_elo_diff` or `vegas_spread`
- **Training data:** Play-by-play from `nba_api` (`playbyplayv2`).
- **Output:** Probability [0,1] updated every possession.
- **Storage:** Pre-compute per game and store as `JSONB` in `games.win_probability_timeline`.

#### 7.2 Elo Ratings
- **Formula:** Standard Elo with K ≈ 20 and home-court adjustment ≈ 69 Elo points (≈ 59.8% home win rate).
- **Update rule:**
  ```
  R_new = R_old + K * (S - E)
  E = 1 / (1 + 10^((R_opp - R_home + advantage) / 400))
  ```
- **Season carryover:** Regress each team toward 1500 by 1/3 at season start.
- **Storage:** `team_elo_history` table with `(team_id, game_id, elo_before, elo_after)`.

#### 7.3 Player Similarity
- **Method:** Cosine similarity on z-scored season stats (PTS, AST, REB, STL, BLK, FG%, 3P%, FT%, TOV, USG%).
- **Optimization:** Pre-compute top-10 similar players per player per season and store in `player_similarity`.
- **UI:** "Players like Luka Dončić" → list with similarity %.

#### 7.4 Clustering Improvements
- **Current:** K-Means with hard rule-based role assignment.
- **Upgrade path:**
  1. **Gaussian Mixture Models (GMM)** — soft cluster membership ("70% playmaker, 30% scorer").
  2. **Hierarchical clustering** — dendrogram for interactive exploration.
  3. **Dimensionality reduction** — UMAP or t-SNE for 2-D scatter plots in the frontend.
- **Persistence:** Store `cluster_assignments` table so historical seasons keep their clusters.

#### 7.5 PER / VORP / Win Shares
- **PER** (Hollinger): A single-season box-score aggregate. Formula is public; normalize to league average = 15.0.
- **VORP** (Value Over Replacement Player): (`BPM - (-2.0)`) × `% minutes played` × team games / 82.
- **WS** (Win Shares): Offensive + defensive components based on points produced / allowed.
- **Implementation:** Compute after each ETL batch and update `player_season_stats` columns.

---

## Migration Roadmap (Phased)

### Phase 1 — Foundation (Weeks 1–2)
1. Set up PostgreSQL + SQLModel + Alembic.
2. Design and create core schema (`players`, `teams`, `seasons`, `player_season_stats`, `games`).
3. Rewrite `nba_player_data.py` as an ETL module with async batches and UPSERT.
4. Seed DB with existing Excel seasons.

### Phase 2 — API Refactor (Weeks 3–4)
1. Introduce Repository + Service layers.
2. Replace `DataContext` with DB-driven endpoints.
3. Port existing endpoints: `/teams`, `/players`, `/player/{id}/analysis`, `/report`.
4. Add `/players/search`, `/leaderboards`.

### Phase 3 — New Features (Weeks 5–6)
1. Ingest `player_game_logs` and `shot_charts`.
2. Build `/games`, `/teams/{id}/schedule`, `/player/{id}/career`.
3. Implement Elo ratings service.
4. Implement player similarity pre-computation.

### Phase 4 — ML & Analytics (Weeks 7–8)
1. Win probability model (logistic regression on play-by-play).
2. Clustering v2: GMM + UMAP visualization endpoints.
3. Advanced stats pipeline: PER, VORP, WS.
4. Background jobs: Celery for nightly ETL + model retraining.

---

## Technology Stack Summary

| Layer | Current | Recommended |
|-------|---------|-------------|
| Web Framework | FastAPI | FastAPI (keep) |
| Frontend | Next.js 14+ | Next.js (keep) |
| Database | Excel files | **PostgreSQL** (+ TimescaleDB optional) |
| ORM | None (pandas) | **SQLModel** + SQLAlchemy 2.0 |
| Migrations | None | **Alembic** |
| Task Queue | None (sync loop) | **Celery + Redis** |
| ML / Stats | scikit-learn, pandas | scikit-learn, **XGBoost**, pandas, numpy |
| Caching | None | **Redis** (leaderboards, Elo) |
| Testing | None visible | pytest, pytest-asyncio, factory-boy |
| Deployment | Local | Docker, Docker Compose |

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| `nba_api` rate limits / blocks | Cache aggressively; use Celery throttling; respect `Retry-After` headers. |
| DB size bloat (shot charts) | Partition `shot_charts` by season; archive old seasons to S3 if needed. |
| Complex queries slow down | Materialized views for leaderboards; Redis cache for 1–5 min TTL. |
| scikit-learn models in async | Run fit/predict in `asyncio.to_thread()` or dedicated Celery task. |
| Frontend breakage during API migration | Version the API (`/api/v1/...`) and keep old routes until v1 is stable. |

---

## Conclusion

The path from the current Excel-backed prototype to a production-grade NBA analytics platform is well-trodden:
1. **PostgreSQL** provides the relational integrity and analytical power needed for sports data.
2. **SQLModel** reduces boilerplate while keeping full SQLAlchemy power available.
3. A **Repository + Service** architecture eliminates the `DataContext` singleton and makes the codebase testable.
4. **Celery-backed ETL** solves the synchronous `nba_api` scraping bottleneck.
5. New endpoints for **games, leaderboards, comparisons, and win probability** unlock significant user value.
6. **Elo, PER, similarity, and improved clustering** are all feasible with the data already available through `nba_api`.

**Next immediate step:** Bootstrap a `docker-compose.yml` with PostgreSQL + Redis, define the first three SQLModel tables (`Player`, `Team`, `PlayerSeasonStat`), and write the Alembic migration.
