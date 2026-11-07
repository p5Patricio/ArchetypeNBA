"""
Walk-forward backtest of the game models against free historical lines. READ-ONLY: the database session is set
to a read-only transaction (PostgreSQL) and rolled back; lines are parsed straight from the raw files, so no import
or migration is needed.

    python scripts/historical_backtest.py                       # report to stdout + ~/ArchetypeNBA-data/reports/
    python scripts/historical_backtest.py --availability        # add the post-game availability UPPER BOUND
    python scripts/historical_backtest.py --n-boot 2000 --seed 7

What it measures, and how to read it: ``app.services.historical_backtest`` and docs/QUANT_MODULE.md
("Historical lines and the backtest").
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import func, select  # noqa: E402

from app.analytics import historical_lines as hl  # noqa: E402
from app.models import PlayerGameLog  # noqa: E402
from app.services import historical_backtest as bt  # noqa: E402
from app.services import historical_lines as lines_service  # noqa: E402
from app.services.elo_service import CURRENT_TEAMS, FRANCHISE_ALIASES, INCLUDED_GAME_TYPES  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    base = lines_service.default_data_dir()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sbro-dir", type=Path, default=base / "raw" / "sbro")
    parser.add_argument("--kaggle-csv", type=Path, default=base / "raw" / "kaggle_cviaxmiwnptr" / "nba_2008-2026.csv")
    parser.add_argument("--reports-dir", type=Path, default=base / "reports")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--availability", action="store_true", help="add the player_game_log availability UPPER BOUND")
    parser.add_argument("--no-save", action="store_true")
    return parser


def load_player_lines(session, games) -> List[bt.PlayerLine]:
    """Box scores of the backtest's games with canonical team ids (read-only query)."""
    from app.analytics.availability import compute_production_score
    from app.models import Team

    rows = session.execute(select(Team.id, Team.abbreviation)).all()
    abbr_to_id = {abbr: tid for tid, abbr in rows}
    canonical: Dict[int, Optional[int]] = {}
    for tid, abbr in rows:
        target = FRANCHISE_ALIASES.get(abbr, abbr)
        canonical[tid] = abbr_to_id.get(target) if target in CURRENT_TEAMS else None
    wanted = {g.game_id for g in games}
    stmt = select(
        PlayerGameLog.game_id, PlayerGameLog.team_id, PlayerGameLog.player_id, PlayerGameLog.min, PlayerGameLog.pts,
        PlayerGameLog.fgm, PlayerGameLog.fga, PlayerGameLog.ftm, PlayerGameLog.fta, PlayerGameLog.oreb,
        PlayerGameLog.dreb, PlayerGameLog.reb, PlayerGameLog.ast, PlayerGameLog.stl, PlayerGameLog.blk,
        PlayerGameLog.tov, PlayerGameLog.pf,
    ).where(func.substr(PlayerGameLog.game_id, 3, 1).in_(INCLUDED_GAME_TYPES))
    out = []
    for r in session.execute(stmt):
        team = canonical.get(r.team_id)
        if r.game_id not in wanted or team is None:
            continue
        score = compute_production_score(
            pts=r.pts or 0, fgm=r.fgm or 0, fga=r.fga or 0, ftm=r.ftm or 0, fta=r.fta or 0, oreb=r.oreb or 0,
            dreb=r.dreb or 0, reb=r.reb or 0, ast=r.ast or 0, stl=r.stl or 0, blk=r.blk or 0, tov=r.tov or 0, pf=r.pf or 0,
        )
        out.append(bt.PlayerLine(r.game_id, team, r.player_id, float(r.min or 0), float(score)))
    return out


def game_lines_by_nba_id(matched) -> Dict[str, bt.GameLines]:
    """One line per player_game_log game: SBRO when present (it has the opening lines), else Kaggle."""
    best: Dict[str, lines_service.ResolvedLine] = {}
    for item in matched:
        if item.nba_game_id is None:
            continue
        current = best.get(item.nba_game_id)
        if current is None or (item.line.source == hl.SOURCE_SBRO and current.line.source != hl.SOURCE_SBRO):
            best[item.nba_game_id] = item
    return {
        gid: bt.GameLines(
            source=i.line.source, open_spread_home=i.line.open_spread_home, close_spread_home=i.line.close_spread_home,
            open_total=i.line.open_total, close_total=i.line.close_total,
            close_moneyline_home=i.line.close_moneyline_home, close_moneyline_away=i.line.close_moneyline_away,
        )
        for gid, i in best.items()
    }


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    parsed, parse_reports = lines_service.read_sources(args.sbro_dir, args.kaggle_csv)
    if not parsed:
        print(f"No input found (looked at {args.sbro_dir} and {args.kaggle_csv}).")
        return 1
    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context
    with session_factory() as session:
        lines_service.set_read_only(session)
        matched, import_report, games = lines_service.prepare(session, parsed, parse_reports)
        labels = lines_service.season_labels(session)
        player_lines = load_player_lines(session, games) if args.availability else None
        session.rollback()

    game_lines = game_lines_by_nba_id(matched)
    config = bt.BacktestConfig(seed=args.seed, n_boot=args.n_boot)
    availability = bt.availability_upper_bound(games, player_lines) if player_lines is not None else None
    result = bt.run_backtest(games, labels, game_lines, config, availability)
    by_source: Dict[str, int] = {}
    for gl in game_lines.values():
        by_source[gl.source] = by_source.get(gl.source, 0) + 1
    header = [
        f"Run {datetime.now().isoformat(timespec='seconds')}; games in player_game_log: {len(games)}; games with a "
        f"line: {len(game_lines)} ({', '.join(f'{k} {v}' for k, v in sorted(by_source.items()))}).",
        "Sources: SBRO archive 2007-08..2023-01-16 (open + close spreads/totals, close moneyline); Kaggle CC0 "
        "compilation for later games (ONE line per game, no open; no moneyline after Jan 2023, so the market "
        "probability there is spread-implied). Neither is Pinnacle; the book behind each line is not documented.",
        "Elo's home advantage (60) was tuned in-sample on 2021-22..2025-26: its rows are slightly optimistic there.",
    ]
    if availability is not None:
        header.append(
            "`_avail_ub` / `avail_UPPER_BOUND` rows use who ACTUALLY played (post-game knowledge): an upper bound, "
            "not a deployable signal."
        )
    report = bt.format_report(result, config, header)
    print(report)
    if not args.no_save:
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        path = args.reports_dir / f"historical_backtest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path.write_text(report + "\n", encoding="utf-8")
        print(f"\nSaved a copy to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
