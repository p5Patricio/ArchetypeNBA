"""
Pinnacle open-to-close line movement from OddsPapi paths, and the D-68 line-move model tested on it. READ-ONLY.

    python scripts/line_movement_report.py                 # movement + naive baselines + walk-forward line-move model
    python scripts/line_movement_report.py --no-model      # movement and baselines only (no archive files needed)
    python scripts/line_movement_report.py --n-boot 2000 --seed 7

The model part re-runs the historical backtest (``app.services.historical_backtest.run_backtest``) with the archive
lines (SBRO / Kaggle, ``~/ArchetypeNBA-data/raw``) plus the OddsPapi Pinnacle open/close of the games that have a
path, so each game is predicted from earlier seasons only. Every number prints its n and a seeded bootstrap 95%
interval; under 30 games it says "insufficient data". Methods and caveats: docs/QUANT_MODULE.md section 15.
"""
import argparse
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.services import line_movement as lm  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    from app.services.historical_lines import default_data_dir

    base = default_data_dir()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--n-boot", type=int, default=1000)
    parser.add_argument("--no-model", action="store_true", help="skip the walk-forward line-move model")
    parser.add_argument("--sbro-dir", type=Path, default=base / "raw" / "sbro")
    parser.add_argument("--kaggle-csv", type=Path, default=base / "raw" / "kaggle_cviaxmiwnptr" / "nba_2008-2026.csv")
    return parser


def model_predictions(session, paths: List[lm.GamePath], args) -> Optional[tuple]:
    """(predicted moves, sigmas) keyed by path, from a walk-forward backtest run; None when archives are missing."""
    from app.services import historical_backtest as bt
    from app.services import historical_lines as lines_service
    from scripts.historical_backtest import game_lines_by_nba_id

    parsed, reports = lines_service.read_sources(args.sbro_dir, args.kaggle_csv)
    if not parsed:
        return None
    matched, _, games = lines_service.prepare(session, parsed, reports)
    labels = lines_service.season_labels(session)
    game_lines = game_lines_by_nba_id(matched)
    by_nba = {p.nba_game_id: p for p in paths if p.nba_game_id}
    for nba_id, p in by_nba.items():
        s, t = p.markets.get("spreads"), p.markets.get("totals")
        if s is None and t is None:
            continue
        old = game_lines.get(nba_id)
        game_lines[nba_id] = bt.GameLines(
            source="oddspapi_pinnacle",
            open_spread_home=s.open_line if s else None, close_spread_home=s.close_line if s else None,
            open_total=t.open_line if t else None, close_total=t.close_line if t else None,
            close_moneyline_home=old.close_moneyline_home if old else None,
            close_moneyline_away=old.close_moneyline_away if old else None,
        )
    result = bt.run_backtest(games, labels, game_lines, bt.BacktestConfig(seed=args.seed, n_boot=args.n_boot))
    index = {gid: i for i, gid in enumerate(result.game_ids)}
    predicted: Dict[str, Dict[str, float]] = {"spreads": {}, "totals": {}}
    sigma: Dict[str, Dict[str, float]] = {"spreads": {}, "totals": {}}
    for nba_id, p in by_nba.items():
        i = index.get(nba_id)
        if i is None:
            continue
        predicted["spreads"][p.key] = float(result.margins["move_spread"][i])
        predicted["totals"][p.key] = float(result.margins["move_total"][i])
        sigma["spreads"][p.key] = float(result.sigma_spread[i])
        sigma["totals"][p.key] = float(result.sigma_total[i])
    scores = {g.game_id: (g.home_pts, g.away_pts) for g in games}
    return predicted, sigma, scores


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context
    from app.services.elo_service import EloRatingService
    from app.services.historical_lines import set_read_only

    out = [f"Line movement report ({datetime.now().isoformat(timespec='seconds')}), seed {args.seed}, "
           f"{args.n_boot} bootstrap resamples"]
    with session_factory() as session:
        set_read_only(session)
        paths = lm.load_pinnacle_paths(session)
        model = None if args.no_model else model_predictions(session, paths, args)
        if model is not None:
            scores = model[2]
        else:
            scores = {g.game_id: (g.home_pts, g.away_pts) for g in EloRatingService(session).load_games()}
        session.rollback()
    lm.attach_scores(paths, scores)
    n_games = sum(1 for p in paths if p.markets)
    out.append(f"Games with a stored Pinnacle path: {n_games} (with a final score: "
               f"{sum(1 for p in paths if p.home_score is not None)})")
    out.extend(lm.format_movement(lm.movement_stats(paths, args.seed, args.n_boot)))
    out.extend(lm.format_strategies(lm.naive_strategies(paths, args.seed, args.n_boot),
                                    "Naive baselines at Pinnacle's opener"))
    if args.no_model:
        out.append("Line-move model: skipped (--no-model).")
    elif model is None:
        out.append(f"Line-move model: no archive lines found ({args.sbro_dir}, {args.kaggle_csv}); skipped.")
    else:
        predicted, sigma, _ = model
        with_pred = sum(1 for v in predicted["spreads"].values() if not math.isnan(v))
        out.append(f"Line-move model (D-68 ridge, walk-forward by season): predictions for {with_pred} game(s)")
        out.extend(lm.format_strategies(
            lm.model_strategies(paths, predicted, sigma, args.seed, args.n_boot),
            "Betting Pinnacle's opener where the model predicts the close will move",
        ))
    out.append(
        "Caveats: close = last OddsPapi createdAt at or before the real tip (seconds to minutes early); the main line "
        "is the most balanced active line at each instant; the model was trained mostly on SBRO opens of an unknown "
        "book and earlier timing, so a Pinnacle opener is a distribution shift; ROI uses Pinnacle's opening price but "
        "ignores opening limits."
    )
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
