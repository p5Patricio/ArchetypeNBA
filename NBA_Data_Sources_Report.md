> **Status: historical research.** This survey of free NBA data sources predates the quantitative system. The feed decisions taken since are in [`docs/DECISIONS.md`](docs/DECISIONS.md) and the open data work (injuries and lineups, a second odds feed) is in [`docs/ROADMAP.md`](docs/ROADMAP.md). The current architecture is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The content below is kept unchanged for context.

# NBA Data Sources Investigation Report

## Executive Summary

This report investigates all major free NBA data sources, with emphasis on the `nba_api` Python package currently used by the project. It covers available endpoints, data granularity, historical depth, rate limits, alternative sources, and data requirements for common analytics use cases.

---

## 1. Current Project Ingestion Approach

**File:** `backend/nba_player_data.py`

The current pipeline:
1. Fetches all active players via `nba_api.stats.static.players.get_active_players()`
2. Iterates player-by-player calling `playercareerstats.PlayerCareerStats(player_id=...)`
3. Extracts either Regular Season (`get_data_frames()[0]`) or Playoffs (`get_data_frames()[1]`)
4. Filters by `SEASON_ID` and a minimum minutes threshold (`MIN >= 100`)
5. Appends to a combined DataFrame and exports to Excel

**Current columns ingested:**
`GP`, `GS`, `MIN`, `FGM`, `FGA`, `FG_PCT`, `FG3M`, `FG3A`, `FG3_PCT`, `FTM`, `FTA`, `FT_PCT`, `OREB`, `DREB`, `REB`, `AST`, `STL`, `BLK`, `TOV`, `PF`, `PTS`

**Observed limitations:**
- Only uses **season totals** (no per-game, per-36, per-100-poss, or advanced stats)
- Only covers **active players** (no retired/historical players)
- Looping over ~450 active players with `time.sleep(0.5)` per call is slow (~4+ minutes per run)
- No injury, lineup, tracking, or play-by-play data

---

## 2. `nba_api` — Complete Endpoint Inventory

`nba_api` is an unofficial Python client for `stats.nba.com` and `cdn.nba.com`. It requires **no API key** and is the most comprehensive free source for official NBA data.

### 2.1 Static Data (no HTTP calls)
| Module | Content |
|--------|---------|
| `nba_api.stats.static.players` | Active/retired player IDs, names, teams |
| `nba_api.stats.static.teams` | Team IDs, abbreviations, franchise info |

### 2.2 Stats Endpoints (`nba_api.stats.endpoints`) — Complete List

#### Player Career & Profile
- `playercareerstats` — Season totals / per-game / advanced by season (regular + playoffs)
- `playerprofilev2` — Deep career splits (by month, pre/post ASG, etc.)
- `commonplayerinfo` — Bio, height, weight, draft info, team
- `playerindex` — League-wide player directory with bios
- `playerawards` — Awards history

#### Game Logs
- `playergamelog` / `playergamelogs` — Box score stats for every game of a season
- `teamgamelog` / `teamgamelogs` — Team-level game logs

#### Box Scores (per-game detail)
- `boxscoretraditionalv2/v3` — Standard box score
- `boxscoreadvancedv2/v3` — Advanced metrics (AST%, REB%, USG%, etc.)
- `boxscorefourfactorsv2/v3` — Dean Oliver's Four Factors
- `boxscorescoringv2/v3` — Scoring breakdowns (PITP, fast break, second chance)
- `boxscoreusagev2/v3` — Usage-rate details
- `boxscoreplayertrackv3` — Player tracking box score (speed, distance, touches)
- `boxscorehustlev2` — Hustle stats (deflections, loose balls, screen assists)
- `boxscoredefensivev2` — Defensive stats (charges drawn, contested shots)
- `boxscoremiscv2/v3` — Miscellaneous (pts off TOV, bench pts, biggest lead)
- `boxscorematchupsv3` — Individual matchup data
- `boxscoresummaryv2/v3` — Game metadata, officials, inactive players

#### Play-by-Play
- `playbyplay` / `playbyplayv2` / `playbyplayv3` — Event-level logs for every possession
- `winprobabilitypbp` — Win probability after each event

#### Shot Charts
- `shotchartdetail` — Every shot attempt with x/y coordinates, zone, distance, defender distance
- `shotchartleaguewide` — League aggregate shooting by zone
- `shotchartlineupdetail` — Lineup-level shot chart data

#### League-Wide Dashboards (Bulk Data)
- `leaguedashplayerstats` — All players in one call (totals, per-game, per-36, per-100-poss, advanced)
- `leaguedashteamstats` — All teams in one call
- `leaguedashplayerclutch` — Clutch-time player stats
- `leaguedashteamclutch` — Clutch-time team stats
- `leaguedashlineups` — Lineup combinations and performance
- `leaguedashplayershotlocations` — Shooting splits by zone for all players
- `leaguedashteamshotlocations` — Team shooting by zone
- `leaguedashplayerbiostats` — Bio + physical measurements
- `leagueleaders` — Category leaders
- `leaguestandings` / `leaguestandingsv3` — Conference/division standings
- `leaguegamefinder` — Query any game in NBA history by filters
- `leaguegamelog` — All games for a season in one call
- `leaguehustlestatsplayer` / `leaguehustlestatsteam` — Hustle leaderboards
- `leaguedashptstats` — Player/team tracking stats (drives, passes, touches, pull-ups, catch-and-shoot)
- `leaguedashptdefend` / `leaguedashptteamdefend` — Defensive tracking (opponent FG% by distance)
- `leagueplayerondetails` — On/off court impact
- `leagueseasonmatchups` — Season-long matchup data
- `matchupsrollup` — Aggregated matchup stats

#### Player Tracking (SportVU / Second Spectrum era)
- `playerdashptshots` — Player shooting by touch time, dribbles, defender distance
- `playerdashptpass` — Passes made/received, assist opportunities
- `playerdashptreb` — Rebounding by shot distance, contest status
- `playerdashptshotdefend` — Shots defended by distance
- `teamdashptshots` / `teamdashptpass` / `teamdashptreb` — Team-level tracking

#### Team & Franchise
- `teamyearbyyearstats` — Franchise season history
- `teamhistoricalleaders` — Franchise all-time leaders
- `teamdetails` — Franchise history, retired jerseys, social media
- `teaminfocommon` — Basic team info
- `commonteamroster` — Current roster with positions, height, weight, experience
- `franchisehistory` / `franchiseleaders` / `franchiseplayers`

#### Draft & Combine
- `drafthistory` — Every draft pick
- `draftboard` — Draft board by year
- `draftcombinedrillresults` / `draftcombinestats` / `draftcombineplayeranthro` / `draftcombinespotshooting` / `draftcombinenonstationaryshooting`

#### Misc
- `scoreboardv2/v3` — Daily schedule + scores
- `scheduleleaguev2` — Full season schedule
- `playernextngames` — Upcoming games for a player
- `playercompare` — Side-by-side comparison
- `playervsplayer` — Head-to-head stats
- `playerdashboardbyclutch` / `bygamesplits` / `bygeneralsplits` / `bylastngames` / `byshootingsplits` / `byteamperformance` / `byyearoveryear`
- `teamdashboardbygeneralsplits` / `byshootingsplits`
- `teamplayerdashboard` / `teamplayeronoffdetails` / `teamplayeronoffsummary`
- `gamerotation` — Substitution patterns with timestamps
- `cumestatsplayer` / `cumestatsplayergames` — Cumulative stats
- `synergyplaytypes` — Synergy play-type data (P&R ball handler, spot-up, iso, etc.)
- `defensehub` — Defensive hub aggregations
- `gravityleaders` / `assistleaders` / `assisttracker` / `dunkscoreleaders`
- `fantasywidget` / `infographicfanduelplayer`
- `homepageleaders` / `homepagev2` / `leaderstiles`
- `playoffpicture` / `iststandings`
- `videodetails` / `videoevents` / `videostatus`
- `glalumboxscoresimilarityscore`
- `alltimeleadersgrids`
- `commonallplayers` / `commonplayoffseries` / `commonteamyears`

### 2.3 Live Data (`nba_api.live.nba.endpoints`)
- `scoreboard` — Live scores, game status, arena info
- `boxscore` — Live player/team stats, lineups
- `playbyplay` — Live play-by-play
- `odds` — Betting odds

---

## 3. Data Granularity Available via `nba_api`

| Granularity | Endpoint Examples | Notes |
|-------------|-------------------|-------|
| **Season Totals** | `playercareerstats`, `leaguedashplayerstats` | Raw cumulative stats for a season |
| **Per-Game** | `leaguedashplayerstats` (PerMode=PerGame) | Averages per game played |
| **Per-36-Min** | `leaguedashplayerstats` (PerMode=Per36) | Normalized to 36 minutes |
| **Per-100-Poss** | `leaguedashplayerstats` (PerMode=Per100Possessions) | Pace-adjusted; best for cross-era comparison |
| **Advanced Stats** | `boxscoreadvancedv3`, `playerprofilev2` | USG%, AST%, REB%, TS%, eFG%, PIE, etc. |
| **Tracking Data** | `leaguedashptstats`, `playerdashptshots` | Drives, pull-ups, catch-and-shoot, touches, passes, defensive distance |
| **Hustle Stats** | `leaguehustlestatsplayer`, `boxscorehustlev2` | Deflections, contested shots, screen assists, loose balls |
| **Shot-Level** | `shotchartdetail` | Every shot with x/y, zone, distance, defender distance, make/miss |
| **Play-by-Play** | `playbyplayv3` | Every possession/event with timestamps |
| **Lineup-Level** | `leaguedashlineups` | 5-man unit stats, plus/minus, minutes |
| **Matchup-Level** | `boxscorematchupsv3` | Who guarded whom and results |
| **On/Off Splits** | `teamplayeronoffdetails` | Team performance with/without player |
| **Clutch Splits** | `leaguedashplayerclutch` | Stats in last 5 min, score within 5 pts |
| **Game Logs** | `playergamelog`, `teamgamelog` | Game-by-game box scores for a season |
| **Live/In-Game** | `live.nba.endpoints.*` | Real-time scores, box scores, play-by-play |
| **Estimated Metrics** | `playerestimatedmetrics` / `teamestimatedmetrics` | PIE, pace, net rating (NBA's own advanced estimates) |

---

## 4. Other Free Data Sources

### 4.1 Basketball-Reference (basketball-reference.com)
- **Scope:** Deep historical database; the gold standard for NBA researchers.
- **Data:** Season totals, per-game, per-36, per-100-poss, advanced stats (PER, BPM, VORP, WS, TS%, ORtg, DRtg), game logs, play-by-play (modern seasons), team stats, franchise histories, draft data, salaries.
- **Historical Depth:** 1946-47 (BAA inception) to present.
- **Access:** Web scraping (requires `requests` + `BeautifulSoup`/`pandas.read_html`). No official API.
- **Rate Limits / Reliability:** ~3-5 sec delay recommended. Aggressive scraping can trigger blocks. Very reliable, but scraping is fragile to HTML changes.
- **Coverage Gaps:**
  - Minutes: >99% complete back to 1976-77
  - STL/BLK/TOV: complete back to 1983-84
  - 3P/3PA: complete back to 1979-80
  - ORB/DRB: complete back to 1983-84
  - +/-: complete back to 1996-97
  - Play-by-play: roughly 2000s onward (varies by game)

### 4.2 data.nba.com / cdn.nba.com (Official NBA JSON Feeds)
- **Scope:** Official static JSON feeds used by NBA.com front end.
- **Data:** Schedule, standings, player bios, team rosters, live box scores, shot charts.
- **Access:** Direct HTTPS GET (no key). Example: `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_{game_id}.json`
- **Rate Limits / Reliability:** Undocumented but generally permissive. Still requires `User-Agent` and `Referer` headers.

### 4.3 balldontlie.io API
- **Scope:** Simplified REST API for NBA data.
- **Data:** Players, teams, games, box scores, season averages, advanced stats, injuries, standings, betting odds, player props.
- **Access:** API key required (free tier available).
- **Rate Limits:**
  - Free: 5 req/min
  - All-Star ($9.99/mo): 60 req/min
  - GOAT ($39.99/mo): 600 req/min
- **Historical Depth:** Modern era (roughly 1979 onward for many endpoints, but varies).
- **Reliability:** Good for prototyping; not as deep or granular as `nba_api`. Many advanced endpoints are paywalled.

### 4.4 ESPN Hidden API
- **Scope:** Unofficial API powering ESPN.com.
- **Data:** Box scores, team/player stats, schedules, summaries, play-by-play.
- **Access:** `https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/...`
- **Rate Limits / Reliability:** Undocumented. Can change without notice. Good backup source.

### 4.5 pbpstats.com / API
- **Scope:** Play-by-play derived stats.
- **Data:** On/off data, WOWY, lineup stats, possession-level metrics.
- **Access:** Public API for some endpoints; deeper access requires subscription.
- **Reliability:** Highly specialized; excellent for lineup/possession analytics.

### 4.6 Community / Aggregated Datasets
- **Kaggle:** Pre-built datasets (season stats, shot logs, play-by-play). Quality varies; check provenance.
- **FiveThirtyEight GitHub:** Historical RAPTOR data (2014 onward) freely downloadable.
- **Dunks & Threes / BBall Index / Crafted NBA:** Public leaderboards for EPM, LEBRON, DARKO, DRIP (not raw data APIs, but valuable reference).

---

## 5. Historical Depth Comparison

| Source | Earliest Season | Play-by-Play | Tracking Data | Notes |
|--------|-----------------|--------------|---------------|-------|
| `stats.nba.com` (`nba_api`) | ~1946 (varies by endpoint) | V2/V3 from ~1996 | 2013-14 onward (SportVU/Second Spectrum) | Most endpoints work reliably from 1996-97 onward. Some newer endpoints (tracking, hustle) only from 2013-14. |
| Basketball-Reference | 1946-47 | ~2000s onward | N/A (aggregated only) | Best for cross-era historical research. |
| balldontlie | ~1979-80 | Limited | None | Simpler schema; good for modern era. |
| data.nba.com / cdn | ~1996 | Modern | Modern | Front-end feeds; not guaranteed for old seasons. |

### Key Historical Milestones
- **1946-47:** BAA founding; Basketball-Reference has basic totals.
- **1973-74:** STL/BLK/TOV first officially tracked in NBA.
- **1979-80:** Three-point line introduced.
- **1983-84:** STL/BLK/TOV consistently complete in most sources.
- **1996-97:** Play-by-play widely available; +/- tracked.
- **2013-14:** Player tracking (SportVU) introduced; hustle/tracking endpoints begin.
- **2014-15:** Second Spectrum tracking begins.

---

## 6. Rate Limits & Reliability

### `nba_api` / `stats.nba.com`
- **No documented rate limit**, but the backend uses Cloudflare and can ban IPs temporarily.
- **Best Practice:** Add **0.6–1.0 second delay** between requests (project currently uses 0.5s, which is borderline).
- **Headers:** Must include realistic `User-Agent`, `Referer: https://www.nba.com/`, and `Accept` headers (nba_api handles this automatically).
- **Reliability:** Generally good during off-peak. Shot chart and tracking endpoints are the most restricted and may return empty datasets or 403s, especially for recent games or high-profile players.
- **Retry Logic:** Implement exponential backoff on `429` or `ConnectionError`.

### Basketball-Reference
- **Best Practice:** 3–5 seconds between page requests.
- **Reliability:** Very high uptime. HTML structure changes rarely but can break scrapers.

### balldontlie
- **Hard limits:** 5 req/min (free), 60 req/min (All-Star), 600 req/min (GOAT).
- **Reliability:** Good. Well-documented but paywalled for advanced features.

### General Tips
- Cache responses locally to avoid re-fetching static data (player lists, schedules).
- Use bulk endpoints (`leaguedashplayerstats`) instead of looping over individual players (`playercareerstats`) when possible — this reduces hundreds of calls to **one call**.

---

## 7. Data Requirements by Use Case

### 7.1 Player Profiles (Current Status)
**Currently implemented:** Basic bio + season totals + shot charts + cluster comparison.

**Data needed:**
- Bio: `commonplayerinfo` (height, weight, age, draft, experience)
- Season stats: `playercareerstats` or `leaguedashplayerstats` (totals, per-game, advanced)
- Shot chart: `shotchartdetail` (x/y coordinates, zones)
- Headshots: `https://cdn.nba.com/headshots/nba/latest/260x190/{player_id}.png`
- **Enhancement opportunities:** Add per-36/per-100-poss stats, tracking splits (drives, catch-and-shoot), defensive metrics (opponent FG%), and clutch splits for richer profiles.

### 7.2 Team Stats
**Data needed:**
- `leaguedashteamstats` — Team totals/per-game/advanced
- `leaguestandings` / `leaguestandingsv3` — W/L, conference rank, streaks
- `teamdashboardbygeneralsplits` — Home/away, rest days, opponent strength
- `teamdashptshots` / `teamdashptpass` / `teamdashptreb` — Team tracking
- `boxscorefourfactorsv3` — Dean Oliver Four Factors (shooting, turnovers, rebounding, free throws)

### 7.3 Game Predictions
**Data needed:**
- **Historical box scores:** `leaguegamelog`, `boxscoretraditionalv3`, `boxscoreadvancedv3`
- **Rolling averages:** Aggregate last 10/20/30 games per team (Four Factors, ORtg, DRtg, pace)
- **Rest & schedule:** `scheduleleaguev2` (back-to-backs, road trips, rest days)
- **Injuries / lineup:** `boxscoresummaryv3` (inactive list), `commonteamroster`, `gamerotation`
- **Home-court advantage:** Venue data from schedule/box score
- **On/Off impact:** `teamplayeronoffsummary` (how team performs with/without key players)
- **Matchup history:** `leaguegamefinder` (head-to-head results)
- **Advanced features (optional but powerful):**
  - EPM/RAPTOR/DARKO from external sources (FiveThirtyEight, Dunks & Threes)
  - Player tracking (pace, speed, distance) from `leaguedashptstats`
  - Lineup data from `leaguedashlineups`

### 7.4 Advanced Analytics
**Data needed:**
- **Plus/Minus metrics:** `teamplayeronoffdetails`, `leagueplayerondetails`, lineup-level +/-
- **Tracking data:** `leaguedashptstats`, `playerdashptshots` (shot quality, touch time, defender distance)
- **Hustle data:** `leaguehustlestatsplayer` (deflections, contested shots, screen assists)
- **Defensive stats:** `leaguedashptdefend` (opponent FG% at rim, from 3, etc.)
- **Play-by-Play:** `playbyplayv3` (possession-level modeling, win probability)
- **Synergy:** `synergyplaytypes` (play-type efficiency: P&R, iso, spot-up, transition)
- **Estimated impact metrics:** `playerestimatedmetrics` / `teamestimatedmetrics` (NBA's PIE, net rating)

---

## 8. Strategic Recommendations for This Project

1. **Switch to bulk ingestion**
   - Replace the per-player `playercareerstats` loop with `leaguedashplayerstats`.
   - One API call returns **all players** for a season with totals, per-game, per-36, per-100-poss, and advanced stats.
   - Reduces ingestion time from ~4 minutes to **< 1 second**.

2. **Expand stat columns**
   - Current clustering uses only basic counting stats.
   - Add efficiency stats (`TS_PCT`, `EFG_PCT`), advanced stats (`USG_PCT`, `AST_PCT`, `REB_PCT`, `PIE`), and tracking stats (`DRIVE_PTS`, `CATCH_SHOOT_PTS`, `PULL_UP_PTS`) for much richer player profiles.

3. **Add game-log support**
   - Use `playergamelog` / `teamgamelog` to support rolling averages and trend analysis.

4. **Add shot-chart depth**
   - Already using `shotchartdetail`. Consider adding zone-based efficiency comparisons (e.g., corner 3%, mid-range, rim) to the player profile.

5. **Cache static data**
   - Player/team ID mappings change rarely. Cache them to avoid redundant API calls.

6. **Improve rate-limit handling**
   - Increase sleep to **0.6–1.0s** when individual endpoints are required.
   - Add exponential backoff retry logic.

7. **Consider Basketball-Reference as fallback**
   - For historical data pre-1996 or for advanced metrics not in `nba_api` (e.g., BPM, VORP), scrape Basketball-Reference or use their downloadable CSVs where available.

---

*Report compiled: 2026-04-29*
*Sources: nba_api GitHub repository, stats.nba.com documentation, Basketball-Reference data coverage pages, balldontlie.io docs, ESPN API observations, FiveThirtyEight methodology articles, and project codebase review.*
