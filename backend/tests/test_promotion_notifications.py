"""
Tests for promotion notifications over Telegram:
- message sent once per committed change (promote, rollback, retire, new challenger registered)
- summary contents: what happened, model names, evidence numbers (paired n, gain, CI), date
- opt-in: nothing sent when unset or containing placeholder "your_"
- failure swallowed: notification failure never breaks the tick
- secrecy: bot token never appears in logs
"""
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import select

from app.config import settings
from app.models import ModelVersion
from app.services import model_promotion, tick
from app.services.model_evaluation import EvaluationConfig
from app.services.promotion_notifier import PromotionNotifier
from app.services.telegram_service import TelegramService
from tests.test_model_evaluation import NOW, League, simulate

UTC = timezone.utc


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_ctx(session, *, dry_run=False, notifier=None, now=NOW):
    return tick.TickContext(
        session,
        None,
        now,
        dry_run,
        30,
        1,
        25,
        UTC,
        None,
        Clock(),
        tick.LEARN_BUDGET_SECONDS,
        notifier=notifier,
    )


def test_notification_sent_on_promotion(db_session):
    """When a challenger qualifies and is promoted, exactly one notification is dispatched."""
    league = League(db_session)
    win, margin, mu_champion, mu_challenger = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=40)
    league.champion.promoted_at = NOW - timedelta(days=60)
    db_session.commit()

    sent_messages = []

    def fake_sender(msg: str) -> bool:
        sent_messages.append(msg)
        return True

    ctx = make_ctx(db_session, notifier=fake_sender)
    res = tick.learn_step(ctx)
    assert res.status == tick.STEP_OK

    # Exactly one promotion message sent
    assert len(sent_messages) >= 1
    promo_msg = [m for m in sent_messages if "[Model Promotion]" in m]
    assert len(promo_msg) == 1
    msg = promo_msg[0]

    # Verify summary contents: what happened, model names, evidence numbers (paired n, gain, CI), date
    assert "promoted to champion, replacing 'elo_538 1.1'" in msg
    assert "elo_538 lab-x" in msg
    assert "paired n=400" in msg
    assert "log-loss gain" in msg
    assert "95% CI" in msg
    assert NOW.strftime("%Y-%m-%d") in msg


def test_notification_sent_on_retirement(db_session):
    """When a challenger is retired by the evaluation pass, exactly one notification is dispatched."""
    league = League(db_session)
    # Simulator with challenger significantly worse than champion
    win, margin, mu_champion, mu_challenger = simulate(150, 42, 1.0, 8.0, challenger_bias=-5.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=30)
    # Add a second dummy Elo model to satisfy Elo protection rule
    extra_elo = ModelVersion(name="elo_backup", version="1.0", role="challenger", params={"sigma": 12.0})
    db_session.add(extra_elo)
    db_session.commit()

    sent_messages = []

    def fake_sender(msg: str) -> bool:
        sent_messages.append(msg)
        return True

    ctx = make_ctx(db_session, notifier=fake_sender)
    # Configure so look budget allows action
    with patch("app.services.model_evaluation.plan_look") as mock_look:
        from app.services.model_evaluation import LookPlan
        mock_look.return_value = LookPlan(True, 1, 12, False)
        res = tick.learn_step(ctx)

    assert res.status == tick.STEP_OK
    retire_msgs = [m for m in sent_messages if "[Model Retirement]" in m]
    assert len(retire_msgs) == 1
    msg = retire_msgs[0]

    assert "Challenger 'elo_538 lab-x' retired" in msg
    assert "paired n=150" in msg
    assert "log-loss gain" in msg
    assert NOW.strftime("%Y-%m-%d") in msg


def test_notification_sent_on_new_challenger_registered(db_session):
    """When a weekly proposal registers a new challenger, exactly one notification is dispatched."""
    league = League(db_session)
    sent_messages = []

    def fake_sender(msg: str) -> bool:
        sent_messages.append(msg)
        return True

    new_model = ModelVersion(name="margin_features", version="lab-new", role="challenger", params={})
    db_session.add(new_model)
    db_session.commit()

    # Mock proposal returning a registered model
    fake_proposal = MagicMock()
    fake_proposal.summary = "1 candidate(s) evaluated, 1 passed; 1 registered"
    fake_proposal.registration = MagicMock()
    fake_proposal.registration.registered = [new_model]
    fake_candidate = MagicMock()
    fake_candidate.label = "margin_features lab-new"
    fake_candidate.holdout = MagicMock()
    fake_candidate.holdout.n_games = 120
    fake_candidate.gate = MagicMock()
    fake_candidate.gate.gain = 0.0025
    fake_candidate.holdout_gain = MagicMock()
    fake_candidate.holdout_gain.ci_low = 0.0005
    fake_candidate.holdout_gain.ci_high = 0.0045
    fake_proposal.report = MagicMock()
    fake_proposal.report.candidates = [fake_candidate]

    with patch("app.services.model_promotion.run_proposal", return_value=fake_proposal), \
         patch("app.services.model_promotion.last_proposal", return_value=None):
        ctx = make_ctx(db_session, notifier=fake_sender)
        res = tick.learn_step(ctx)

    assert res.status == tick.STEP_OK
    cand_msgs = [m for m in sent_messages if "[New Challenger Registered]" in m]
    assert len(cand_msgs) == 1
    msg = cand_msgs[0]

    assert "Model 'margin_features lab-new' registered as active challenger" in msg
    assert "hold-out n=120" in msg
    assert "gain +0.0025" in msg
    assert "(95% CI +0.0005 .. +0.0045)" in msg
    assert NOW.strftime("%Y-%m-%d") in msg


def test_nothing_sent_when_unset_or_placeholder():
    """When Telegram credentials are unset or placeholder ('your_...'), nothing is sent."""
    sent = []

    # Token empty
    n1 = PromotionNotifier(bot_token="", chat_id="12345")
    assert not n1.is_configured
    assert n1.send("test") is False

    # Token placeholder
    n2 = PromotionNotifier(bot_token="your_bot_token", chat_id="12345")
    assert not n2.is_configured
    assert n2.send("test") is False

    # Chat ID placeholder
    n3 = PromotionNotifier(bot_token="123456:ABC-DEF", chat_id="your_chat_id")
    assert not n3.is_configured
    assert n3.send("test") is False


def test_notification_failure_is_swallowed_and_tick_continues(db_session, caplog):
    """When sender raises an exception, the failure is caught, logged at warning, and tick succeeds."""
    league = League(db_session)
    win, margin, mu_champion, mu_challenger = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=40)
    league.champion.promoted_at = NOW - timedelta(days=60)
    db_session.commit()

    SECRET_TOKEN = "987654321:SECRET_BOT_TOKEN"

    def crashing_sender(msg: str) -> bool:
        # Simulate network error that leaks the full API URL containing secret token
        raise ConnectionError(f"HTTP 500 connecting to https://api.telegram.org/bot{SECRET_TOKEN}/sendMessage")

    notifier = PromotionNotifier(sender=crashing_sender, bot_token=SECRET_TOKEN, chat_id="123456")

    ctx = make_ctx(db_session, notifier=notifier)
    with caplog.at_level(logging.WARNING):
        res = tick.learn_step(ctx)

    # Tick step completed successfully despite notification exception
    assert res.status == tick.STEP_OK

    # Warning was logged
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING and "Promotion notification" in r.message]
    assert len(warning_records) >= 1

    # SECRECY: The actual bot token must NEVER appear anywhere in the logs!
    for record in caplog.records:
        assert SECRET_TOKEN not in record.message
        assert SECRET_TOKEN not in str(record.exc_info)


def test_dry_run_never_sends_notifications(db_session):
    """A dry-run tick must never dispatch any promotion notification."""
    league = League(db_session)
    win, margin, mu_champion, mu_challenger = simulate(400, 21, 7.0, 1.0)
    league.populate(win, margin, mu_champion, mu_challenger, days=40)
    db_session.commit()

    sent = []
    ctx = make_ctx(db_session, dry_run=True, notifier=lambda m: sent.append(m))
    res = tick.learn_step(ctx)
    assert res.status == tick.STEP_OK
    assert len(sent) == 0
