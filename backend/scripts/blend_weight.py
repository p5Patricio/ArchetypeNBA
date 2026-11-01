"""
Prints the fitted model weight of the `calibrated` strategy and how far the champion sits from Pinnacle.
Read-only.

    python scripts/blend_weight.py

* ``w_used`` / ``w_hat`` / n: see ``app.analytics.betting_policy.fit_blend_weight``; the `calibrated` strategy places
  no bet while ``w_used`` is 0 (fewer than 100 calibration games, or no evidence the model adds to the market).
* Distribution of ``|p_model - p_fair|`` over the same calibration games (the champion's home probability against
  Pinnacle's de-vigged home probability at prediction time), with the share inside the 6pp cap.
"""
import sys
from pathlib import Path
from typing import List, Optional, Sequence

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.analytics import betting_policy as policy  # noqa: E402
from app.services import model_registry  # noqa: E402
from app.services.blend_calibration import BlendWeight, load_calibration_data  # noqa: E402

_QUANTILES = (0.0, 0.25, 0.5, 0.75, 0.9, 1.0)


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def format_blend(session) -> str:
    champion = model_registry.get_champion(session)
    if champion is None:
        return "No champion registered: no calibration data."
    data = load_calibration_data(session, champion.id)
    w_used, w_hat, n = policy.fit_blend_weight(data.p_models, data.p_fairs, data.outcomes)
    lines = [
        f"Champion: {champion.name} {champion.version}",
        BlendWeight(w_used, w_hat, n).report_line(),
        f"  needs at least {policy.MIN_CALIBRATION_GAMES} games; w_used = w_hat * n / (n + {policy.CALIBRATION_PRIOR_GAMES}); "
        f"w_hat searched on 0.00..{policy.W_MAX:.2f}",
    ]
    if not n:
        lines.append("No final game has a champion h2h prediction recorded before tip-off and a Pinnacle pair at that time.")
        return "\n".join(lines)
    gaps = sorted(abs(m - f) for m, f in zip(data.p_models, data.p_fairs))
    lines.append(f"Distribution of |p_model - p_fair| over {n} games (percentage points)")
    lines.append("  " + " | ".join(f"{'min' if q == 0 else 'max' if q == 1 else f'p{round(q * 100)}'} {_quantile(gaps, q) * 100:.1f}" for q in _QUANTILES))
    inside = sum(1 for gap in gaps if gap <= policy.MAX_DISAGREEMENT)
    lines.append(f"  within the {policy.MAX_DISAGREEMENT * 100:.0f}pp cap: {inside} of {n} ({inside / n:.0%})")
    mean_model = sum(data.p_models) / n
    mean_fair = sum(data.p_fairs) / n
    home_rate = sum(data.outcomes) / n
    lines.append(
        f"  mean home probability: model {mean_model:.3f} | Pinnacle at prediction {mean_fair:.3f} | home win rate {home_rate:.3f}"
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None, session_factory=None) -> int:
    if session_factory is None:
        from app.deps import get_db_context  # imported late so --help never builds a DB engine

        session_factory = get_db_context
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError, OSError):
        pass
    with session_factory() as session:
        print(format_blend(session))
    return 0


if __name__ == "__main__":
    sys.exit(main())
