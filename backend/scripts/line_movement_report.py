"""
Pinnacle open-to-close line movement from OddsPapi paths, and the D-68 line-move model tested on it. READ-ONLY.

    python scripts/line_movement_report.py                 # movement + naive baselines + walk-forward line-move model
    python scripts/line_movement_report.py --no-model      # movement and baselines only (no archive files needed)
    python scripts/line_movement_report.py --n-boot 2000 --seed 7
    python scripts/line_movement_report.py --entry-rule in_force   # leak-safe entry = the quote in force (sensitivity)

The model part re-runs the historical backtest (``app.services.historical_backtest.run_backtest``) with the archive
lines (SBRO / Kaggle, ``~/ArchetypeNBA-data/raw``) plus the OddsPapi Pinnacle open/close of the games that have a
path, so each game is predicted from earlier seasons only. Every number prints its n and a seeded bootstrap 95%
interval; under 30 games it says "insufficient data" (or flags the row). Methods and caveats: docs/QUANT_MODULE.md
section 15.

The LEAK-SAFE part (default with the model, D-71) bets at the BETTABLE instant instead of the opener: the first
stored Pinnacle quote at or after max(opener, both teams' previous games final + 30 min), with every feature
computed from games final by then (``line_movement.features_as_of``) and the targets of earlier path games redefined
as close - entry. It prints naive baselines at the entry, the model by threshold, the back-to-back split and the
month split, next to the opener-based (leaky) numbers above.
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
    parser.add_argument("--no-leak-safe", action="store_true", help="skip the leak-safe evaluation at the bettable instant")
    parser.add_argument("--entry-rule", choices=lm.ENTRY_RULES, default=lm.ENTRY_FIRST_AFTER)
    parser.add_argument("--sbro-dir", type=Path, default=base / "raw" / "sbro")
    parser.add_argument("--kaggle-csv", type=Path, default=base / "raw" / "kaggle_cviaxmiwnptr" / "nba_2008-2026.csv")
    return parser


def load_archive(session, args) -> Optional[tuple]:
    """(archive lines by nba_game_id, games, season labels) or None when the archive files are missing."""
    from app.services import historical_lines as lines_service
    from scripts.historical_backtest import game_lines_by_nba_id

    parsed, reports = lines_service.read_sources(args.sbro_dir, args.kaggle_csv)
    if not parsed:
        return None
    matched, _, games = lines_service.prepare(session, parsed, reports)
    return game_lines_by_nba_id(matched), games, lines_service.season_labels(session)


def model_predictions(session, paths: List[lm.GamePath], args, archive=None, overrides=None,
                      export_season: Optional[str] = None) -> Optional[tuple]:
    """
    (predicted moves, sigmas, scores, backtest result) keyed by path, from a walk-forward backtest run in which the
    Pinnacle "open"/close of each path replaces the archive lines; None when archives are missing. With entry paths
    and ``overrides`` (features as of the bettable instant) this is the leak-safe run.
    """
    from app.services import historical_backtest as bt

    archive = archive if archive is not None else load_archive(session, args)
    if archive is None:
        return None
    base_lines, games, labels = archive
    game_lines = dict(base_lines)
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
    result = bt.run_backtest(games, labels, game_lines,
                             bt.BacktestConfig(seed=args.seed, n_boot=args.n_boot, export_season=export_season),
                             feature_overrides=overrides)
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
    return predicted, sigma, scores, result


def leak_safe_inputs(session, paths: List[lm.GamePath], games, rule: str):
    """Entry paths, feature overrides as of each bettable instant, entry stats and refused games."""
    tips = lm.load_tip_times(session)
    readiness = lm.readiness_times(games, tips)
    entries, as_of, stats = lm.entry_paths(paths, readiness, rule)
    overrides, refused = lm.features_as_of(games, tips, as_of)
    refused_set = set(refused)
    entries = [p for p in entries if p.nba_game_id in overrides and p.nba_game_id not in refused_set]
    return entries, overrides, stats, refused, readiness


def leak_safe_section(session, paths: List[lm.GamePath], leaky_model, archive, args) -> List[str]:
    """The leak-safe evaluation lines (see the module docstring)."""
    games = archive[1]
    entries, overrides, stats, refused, readiness = leak_safe_inputs(session, paths, games, args.entry_rule)
    out = ["", "=== LEAK-SAFE: bets at the bettable instant, features as of that instant (D-71) ==="]
    out.extend(lm.format_entry_stats(stats, args.entry_rule))
    if refused:
        out.append(f"  refused (a team game on/after the date would have been fed): {len(refused)}")
    model = model_predictions(session, entries, args, archive=archive, overrides=overrides)
    predicted, sigma, scores, result = model
    lm.attach_scores(entries, scores)
    out.extend(lm.format_strategies(lm.naive_strategies(entries, args.seed, args.n_boot),
                                    "Naive baselines at the leak-safe entry"))
    out.extend(lm.format_rows(
        [("all", r) for r in lm.model_strategies(entries, predicted, sigma, args.seed, args.n_boot)],
        "Line-move model at the leak-safe entry (target close - entry, walk-forward by season)",
    ))
    # bridge to the earlier numbers: the opener-based model on games whose opener already came after readiness
    l_pred, l_sigma = leaky_model[0], leaky_model[1]
    clean = [p for p in paths if p.nba_game_id in readiness and p.markets and (
        readiness[p.nba_game_id].ready_at is None
        or min(oc.open_at for m, oc in p.markets.items() if m != "h2h") >= readiness[p.nba_game_id].ready_at)]
    out.extend(lm.format_rows(
        [("clean-open", r) for r in lm.model_strategies(clean, l_pred, l_sigma, args.seed, args.n_boot)],
        f"Opener-based (leaky) model restricted to the {len(clean)} games whose opener came after readiness",
    ))
    index = {gid: i for i, gid in enumerate(result.game_ids)}
    b2b = {}
    for p in entries:
        i = index.get(p.nba_game_id)
        if i is not None and result.b2b_any is not None:
            b2b[p.key] = "b2b" if bool(result.b2b_any[i]) else "no_b2b"
    out.extend(lm.format_rows(lm.split_results(entries, predicted, sigma, b2b, args.seed, args.n_boot),
                              "Leak-safe model, back-to-back (either team played the day before) vs not"))
    month = {p.key: p.tip.strftime("%Y-%m") for p in entries if p.tip is not None}
    out.extend(lm.format_rows(lm.split_results(entries, predicted, sigma, month, args.seed, args.n_boot, (0.25, 0.5)),
                              "Leak-safe model by month of the tip (thresholds 0.25 and 0.5)"))
    return out


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    args = build_parser().parse_args(argv)
    if session_factory is None:
        from app.deps import get_db_context

        session_factory = get_db_context
    from app.services.elo_service import EloRatingService
    from app.services.historical_lines import set_read_only

    out = [f"Line movement report ({datetime.now().isoformat(timespec='seconds')}), seed {args.seed}, "
           f"{args.n_boot} bootstrap resamples"]
    leak_safe: List[str] = []
    with session_factory() as session:
        set_read_only(session)
        paths = lm.load_pinnacle_paths(session)
        archive = None if args.no_model else load_archive(session, args)
        model = None if archive is None else model_predictions(session, paths, args, archive=archive)
        if model is not None:
            scores = model[2]
            if not args.no_leak_safe:
                leak_safe = leak_safe_section(session, paths, model, archive, args)
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
        predicted, sigma = model[0], model[1]
        with_pred = sum(1 for v in predicted["spreads"].values() if not math.isnan(v))
        out.append(f"Line-move model (D-68 ridge, walk-forward by season): predictions for {with_pred} game(s)")
        out.extend(lm.format_strategies(
            lm.model_strategies(paths, predicted, sigma, args.seed, args.n_boot),
            "Betting Pinnacle's opener where the model predicts the close will move (LEAKY: the features can include "
            "a previous game that ended after the opener)",
        ))
        out.extend(leak_safe)
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
