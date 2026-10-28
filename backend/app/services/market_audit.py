"""
Market audit: closing-total error on settled games and player-prop closing quotes vig.
Read-only analysis of stored closing market data.
"""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import math
import statistics
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlmodel import Session

from app.analytics.props_engine import american_to_decimal
from app.models import (
    CAPTURE_CLOSING,
    CAPTURE_CLOSING_PROPS,
    BetSide,
    Game,
    MarketType,
    OddsHistory,
    OddsSnapshotCapture,
    Sportsbook,
)


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _line(value) -> Optional[Decimal]:
    return None if value is None else _dec(value).quantize(Decimal("0.1"))


def _recency(quote: OddsHistory) -> Tuple[datetime, datetime, int]:
    return (_aware_utc(quote.captured_at), _aware_utc(quote.book_last_update), quote.id)


@dataclass
class TotalErrorAudit:
    n_games: int = 0
    mean_error: Optional[float] = None
    std_dev: Optional[float] = None


@dataclass
class PropVigAudit:
    n_pairs: int = 0
    mean_vig: Optional[float] = None
    median_vig: Optional[float] = None


@dataclass
class TotalsShadowAudit:
    n_games: int = 0
    brier_model: Optional[float] = None
    brier_pinnacle: Optional[float] = None
    brier_diff: Optional[float] = None
    brier_diff_ci_low: Optional[float] = None
    brier_diff_ci_high: Optional[float] = None
    log_loss_model: Optional[float] = None
    log_loss_pinnacle: Optional[float] = None
    log_loss_diff: Optional[float] = None
    log_loss_diff_ci_low: Optional[float] = None
    log_loss_diff_ci_high: Optional[float] = None
    mean_total_error: Optional[float] = None
    sd_total_error: Optional[float] = None


@dataclass
class MarketAuditResult:
    totals: TotalErrorAudit = field(default_factory=TotalErrorAudit)
    props: PropVigAudit = field(default_factory=PropVigAudit)
    totals_shadow: TotalsShadowAudit = field(default_factory=TotalsShadowAudit)


def audit_closing_totals(session: Session) -> TotalErrorAudit:
    """
    Computes error of (final total points - closing total line) on settled games
    that have a closing marker.
    """
    # 1. Settled games with closing marker
    closing_marker_ids = set(
        session.execute(
            select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)
        ).scalars()
    )
    if not closing_marker_ids:
        return TotalErrorAudit()

    finals = session.execute(
        select(Game.id, Game.home_score, Game.away_score, Game.commence_time).where(
            Game.id.in_(list(closing_marker_ids)),
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        )
    ).all()

    if not finals:
        return TotalErrorAudit()

    game_scores = {g_id: (h_score + a_score, commence) for g_id, h_score, a_score, commence in finals}
    game_ids = list(game_scores.keys())

    # 2. Closing totals quotes for these games
    quotes = session.execute(
        select(OddsHistory)
        .join(Sportsbook, Sportsbook.id == OddsHistory.sportsbook_id)
        .where(
            OddsHistory.game_id.in_(game_ids),
            OddsHistory.market == MarketType.totals,
            OddsHistory.player_id.is_(None),
            OddsHistory.line.is_not(None),
        )
        .order_by(Sportsbook.is_sharp.desc(), OddsHistory.captured_at.asc(), OddsHistory.id.asc())
    ).scalars().all()

    # Find latest quote at or before tip-off for each game (prioritizing sharp books)
    best_quote_by_game: Dict[int, OddsHistory] = {}
    for q in quotes:
        if q.captured_at is None:
            continue
        commence = game_scores[q.game_id][1]
        if _aware_utc(q.captured_at) > _aware_utc(commence):
            continue
        g_id = q.game_id
        if g_id not in best_quote_by_game:
            best_quote_by_game[g_id] = q
        else:
            prev = best_quote_by_game[g_id]
            # Replace if current is sharper or more recent among same sharpness
            if _recency(q) > _recency(prev):
                best_quote_by_game[g_id] = q

    errors: List[float] = []
    for g_id, q in best_quote_by_game.items():
        actual_total = game_scores[g_id][0]
        closing_line = float(q.line)
        errors.append(actual_total - closing_line)

    n = len(errors)
    if n == 0:
        return TotalErrorAudit()

    mean_err = sum(errors) / n
    sd_err = math.sqrt(sum((e - mean_err) ** 2 for e in errors) / (n - 1)) if n >= 2 else None

    return TotalErrorAudit(n_games=n, mean_error=mean_err, std_dev=sd_err)


def audit_prop_vig(session: Session) -> PropVigAudit:
    """
    Computes typical vig of stored player-prop closing quotes (over/under pairs).
    """
    # Quotes on games with a closing_props marker, or player prop quotes at/before tip-off
    closing_prop_games = set(
        session.execute(
            select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING_PROPS)
        ).scalars()
    )

    query = (
        select(OddsHistory, Game.commence_time)
        .join(Game, Game.id == OddsHistory.game_id)
        .where(
            OddsHistory.player_id.is_not(None),
            OddsHistory.side.in_([BetSide.over, BetSide.under, BetSide.over.value, BetSide.under.value]),
            OddsHistory.line.is_not(None),
        )
    )
    if closing_prop_games:
        query = query.where(OddsHistory.game_id.in_(list(closing_prop_games)))

    rows = session.execute(query).all()
    if not rows:
        return PropVigAudit()

    # Group by (game_id, sportsbook_id, market, player_id, line) -> side -> latest quote
    grouped: Dict[tuple, Dict[str, OddsHistory]] = defaultdict(dict)
    for q, commence in rows:
        if q.captured_at is None or _aware_utc(q.captured_at) > _aware_utc(commence):
            continue
        key = (q.game_id, q.sportsbook_id, _enum_value(q.market), q.player_id, _line(q.line))
        side_str = _enum_value(q.side)
        if side_str not in grouped[key] or _recency(q) > _recency(grouped[key][side_str]):
            grouped[key][side_str] = q

    vigs: List[float] = []
    for sides in grouped.values():
        if BetSide.over.value in sides and BetSide.under.value in sides:
            q_over = sides[BetSide.over.value]
            q_under = sides[BetSide.under.value]
            d_over = american_to_decimal(q_over.price_american)
            d_under = american_to_decimal(q_under.price_american)
            if d_over > 0 and d_under > 0:
                # Vig = sum of implied probabilities - 1.0
                vig = (1.0 / d_over + 1.0 / d_under) - 1.0
                vigs.append(vig)

    if not vigs:
        return PropVigAudit()

    return PropVigAudit(
        n_pairs=len(vigs),
        mean_vig=statistics.mean(vigs),
        median_vig=statistics.median(vigs),
    )


def audit_totals_shadow(session: Session, seed: int = 42) -> TotalsShadowAudit:
    """
    Evaluates the shadow totals model (totals_pace) against Pinnacle's de-vigged closing line
    on settled games with matching totals lines.
    """
    import numpy as np
    from app.analytics.props_engine import devig_two_way
    from app.analytics.totals_model import PROB_CLIP
    from app.models import ModelPrediction
    from app.services import model_registry
    from app.services.model_lab import paired_bootstrap

    shadow_model = model_registry.get_totals_shadow_model(session)
    if shadow_model is None:
        return TotalsShadowAudit()

    # 1. Settled games with closing marker
    closing_marker_ids = set(
        session.execute(
            select(OddsSnapshotCapture.game_id).where(OddsSnapshotCapture.kind == CAPTURE_CLOSING)
        ).scalars()
    )
    if not closing_marker_ids:
        return TotalsShadowAudit()

    finals = session.execute(
        select(Game.id, Game.home_score, Game.away_score, Game.commence_time).where(
            Game.id.in_(list(closing_marker_ids)),
            Game.status == "final",
            Game.home_score.is_not(None),
            Game.away_score.is_not(None),
        )
    ).all()
    if not finals:
        return TotalsShadowAudit()

    game_scores = {g_id: (int(h_score) + int(a_score), commence) for g_id, h_score, a_score, commence in finals}
    game_ids = list(game_scores.keys())

    # 2. Pinnacle closing totals quotes
    quotes = session.execute(
        select(OddsHistory)
        .join(Sportsbook, Sportsbook.id == OddsHistory.sportsbook_id)
        .where(
            OddsHistory.game_id.in_(game_ids),
            Sportsbook.is_sharp == True,
            OddsHistory.market == MarketType.totals,
            OddsHistory.player_id.is_(None),
            OddsHistory.line.is_not(None),
            OddsHistory.price_american.is_not(None),
        )
        .order_by(OddsHistory.captured_at.asc(), OddsHistory.id.asc())
    ).scalars().all()

    # Latest closing quote per (game_id, line, side) at or before tip-off
    pinnacle_quotes: Dict[Tuple[int, Decimal, str], OddsHistory] = {}
    for q in quotes:
        if q.captured_at is None:
            continue
        commence = game_scores[q.game_id][1]
        if _aware_utc(q.captured_at) > _aware_utc(commence):
            continue
        line_key = _line(q.line)
        if line_key is None:
            continue
        side_key = _enum_value(q.side)
        key = (q.game_id, line_key, side_key)
        if key not in pinnacle_quotes or _recency(q) > _recency(pinnacle_quotes[key]):
            pinnacle_quotes[key] = q

    # 3. Model predictions under totals_pace
    preds = session.execute(
        select(ModelPrediction).where(
            ModelPrediction.model_version_id == shadow_model.id,
            ModelPrediction.game_id.in_(game_ids),
            ModelPrediction.market == MarketType.totals,
            ModelPrediction.line.is_not(None),
        )
    ).scalars().all()

    preds_by_game_line_side: Dict[Tuple[int, Decimal, str], ModelPrediction] = {}
    for p in preds:
        line_key = _line(p.line)
        if line_key is not None:
            preds_by_game_line_side[(p.game_id, line_key, _enum_value(p.side))] = p

    # 4. Pair up (game, line) where both Pinnacle (over+under) and Model (over) exist
    game_lines = set()
    for (g_id, line_key, side_key) in pinnacle_quotes:
        if (g_id, line_key, BetSide.over.value) in pinnacle_quotes and (g_id, line_key, BetSide.under.value) in pinnacle_quotes:
            if (g_id, line_key, BetSide.over.value) in preds_by_game_line_side:
                game_lines.add((g_id, line_key))

    if not game_lines:
        return TotalsShadowAudit()

    sorted_game_lines = sorted(game_lines, key=lambda x: (x[0], x[1]))

    brier_mod_list: List[float] = []
    brier_pin_list: List[float] = []
    ll_mod_list: List[float] = []
    ll_pin_list: List[float] = []
    total_errors: List[float] = []

    for g_id, line_key in sorted_game_lines:
        actual_total = game_scores[g_id][0]
        q_over = pinnacle_quotes[(g_id, line_key, BetSide.over.value)]
        q_under = pinnacle_quotes[(g_id, line_key, BetSide.under.value)]
        pred_over = preds_by_game_line_side[(g_id, line_key, BetSide.over.value)]

        p_over_dec = american_to_decimal(q_over.price_american)
        p_under_dec = american_to_decimal(q_under.price_american)
        if p_over_dec <= 0 or p_under_dec <= 0:
            continue

        fair_over, _ = devig_two_way(p_over_dec, p_under_dec)
        model_prob = float(pred_over.model_prob)

        # Model total error (actual - mu)
        if pred_over.projection is not None:
            mu = float(pred_over.projection)
            total_errors.append(actual_total - mu)

        line_val = float(line_key)
        if actual_total == line_val:
            # Push on integer line: outcome is not binary won/lost
            continue
        y = 1.0 if actual_total > line_val else 0.0

        # Brier
        b_m = (model_prob - y) ** 2
        b_p = (fair_over - y) ** 2
        brier_mod_list.append(b_m)
        brier_pin_list.append(b_p)

        # Log loss
        p_m_clip = float(np.clip(model_prob, PROB_CLIP, 1.0 - PROB_CLIP))
        p_p_clip = float(np.clip(fair_over, PROB_CLIP, 1.0 - PROB_CLIP))
        ll_m = -(y * math.log(p_m_clip) + (1.0 - y) * math.log(1.0 - p_m_clip))
        ll_p = -(y * math.log(p_p_clip) + (1.0 - y) * math.log(1.0 - p_p_clip))
        ll_mod_list.append(ll_m)
        ll_pin_list.append(ll_p)

    n_eval = len(sorted_game_lines)
    if n_eval == 0:
        return TotalsShadowAudit()

    brier_m_mean = float(np.mean(brier_mod_list)) if brier_mod_list else None
    brier_p_mean = float(np.mean(brier_pin_list)) if brier_pin_list else None
    brier_diff = (brier_m_mean - brier_p_mean) if (brier_m_mean is not None and brier_p_mean is not None) else None

    ll_m_mean = float(np.mean(ll_mod_list)) if ll_mod_list else None
    ll_p_mean = float(np.mean(ll_pin_list)) if ll_pin_list else None
    ll_diff = (ll_m_mean - ll_p_mean) if (ll_m_mean is not None and ll_p_mean is not None) else None

    brier_ci_low, brier_ci_high = None, None
    ll_ci_low, ll_ci_high = None, None

    if len(brier_mod_list) >= 2:
        diff_b_arr = np.array(brier_mod_list) - np.array(brier_pin_list)
        delta_b = paired_bootstrap(diff_b_arr, seed=seed)
        brier_ci_low, brier_ci_high = delta_b.ci_low, delta_b.ci_high

    if len(ll_mod_list) >= 2:
        diff_ll_arr = np.array(ll_mod_list) - np.array(ll_pin_list)
        delta_ll = paired_bootstrap(diff_ll_arr, seed=seed)
        ll_ci_low, ll_ci_high = delta_ll.ci_low, delta_ll.ci_high

    mean_err = float(np.mean(total_errors)) if total_errors else None
    sd_err = float(np.std(total_errors, ddof=1)) if len(total_errors) >= 2 else None

    return TotalsShadowAudit(
        n_games=n_eval,
        brier_model=brier_m_mean,
        brier_pinnacle=brier_p_mean,
        brier_diff=brier_diff,
        brier_diff_ci_low=brier_ci_low,
        brier_diff_ci_high=brier_ci_high,
        log_loss_model=ll_m_mean,
        log_loss_pinnacle=ll_p_mean,
        log_loss_diff=ll_diff,
        log_loss_diff_ci_low=ll_ci_low,
        log_loss_diff_ci_high=ll_ci_high,
        mean_total_error=mean_err,
        sd_total_error=sd_err,
    )


def run_market_audit(session: Session) -> MarketAuditResult:
    return MarketAuditResult(
        totals=audit_closing_totals(session),
        props=audit_prop_vig(session),
        totals_shadow=audit_totals_shadow(session),
    )


def format_market_audit(result: MarketAuditResult) -> str:
    lines = ["Market Audit Report", ""]

    # (a) Closing totals error
    lines.append("1. Closing-total error on settled games (actual - closing line):")
    if result.totals.n_games > 0:
        sd_str = f"{result.totals.std_dev:.2f} pts" if result.totals.std_dev is not None else "n/a"
        lines.append(
            f"   n = {result.totals.n_games} games | "
            f"mean error = {result.totals.mean_error:+.2f} pts | "
            f"sd = {sd_str}"
        )
    else:
        lines.append("   no data (no settled games with closing totals quotes)")

    lines.append("")

    # (b) Player props vig
    lines.append("2. Player-prop closing quotes typical vig (over/under pairs):")
    if result.props.n_pairs > 0:
        lines.append(
            f"   n = {result.props.n_pairs} pairs | "
            f"mean vig = {result.props.mean_vig * 100:.2f}% | "
            f"median vig = {result.props.median_vig * 100:.2f}%"
        )
    else:
        lines.append("   no data (no over/under closing prop pairs)")

    lines.append("")

    # (c) Totals shadow model vs Pinnacle's close
    lines.append("3. Totals shadow model vs Pinnacle's close:")
    shadow = result.totals_shadow
    if shadow.n_games == 0:
        lines.append("   no data (no settled games with totals prediction and Pinnacle close)")
    elif shadow.n_games < 30:
        lines.append(f"   insufficient data (n = {shadow.n_games} < 30)")
        if shadow.brier_model is not None and shadow.brier_pinnacle is not None:
            lines.append(
                f"   Brier: model {shadow.brier_model:.4f} | Pinnacle {shadow.brier_pinnacle:.4f} | diff {shadow.brier_diff:+.4f}"
            )
            lines.append(
                f"   Log loss: model {shadow.log_loss_model:.4f} | Pinnacle {shadow.log_loss_pinnacle:.4f} | diff {shadow.log_loss_diff:+.4f}"
            )
        if shadow.mean_total_error is not None:
            sd_str = f"{shadow.sd_total_error:.2f} pts" if shadow.sd_total_error is not None else "n/a"
            lines.append(f"   Model total error (actual - mu): mean = {shadow.mean_total_error:+.2f} pts | sd = {sd_str}")
    else:
        lines.append(f"   n = {shadow.n_games} games")
        lines.append(
            f"   Brier: model {shadow.brier_model:.4f} | Pinnacle {shadow.brier_pinnacle:.4f} | "
            f"diff {shadow.brier_diff:+.4f} (95% CI [{shadow.brier_diff_ci_low:+.4f}, {shadow.brier_diff_ci_high:+.4f}])"
        )
        lines.append(
            f"   Log loss: model {shadow.log_loss_model:.4f} | Pinnacle {shadow.log_loss_pinnacle:.4f} | "
            f"diff {shadow.log_loss_diff:+.4f} (95% CI [{shadow.log_loss_diff_ci_low:+.4f}, {shadow.log_loss_diff_ci_high:+.4f}])"
        )
        sd_str = f"{shadow.sd_total_error:.2f} pts" if shadow.sd_total_error is not None else "n/a"
        lines.append(f"   Model total error (actual - mu): mean = {shadow.mean_total_error:+.2f} pts | sd = {sd_str}")

    return "\n".join(lines)
