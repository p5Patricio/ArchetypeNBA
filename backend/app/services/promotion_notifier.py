"""
Promotion notifications: format and dispatch Telegram alerts for model league role changes.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Sequence

from app.config import settings
from app.models import ModelVersion
from app.services import model_promotion
from app.services.telegram_service import TelegramService

logger = logging.getLogger(__name__)


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _gain_str(gain) -> str:
    if gain is None:
        return "n/a"
    interval = "" if getattr(gain, "ci_low", None) is None else f" (95% CI {gain.ci_low:+.4f} .. {gain.ci_high:+.4f})"
    return f"{gain.mean:+.4f}{interval}"


def format_pass_change_message(entry: model_promotion.PassEntry, champion_label: str, now: datetime) -> str:
    date_str = _aware_utc(now).strftime("%Y-%m-%d")
    result = entry.result

    if entry.action == model_promotion.ACTION_PROMOTED:
        header = f"[Model Promotion] {date_str}"
        body = f"Model '{entry.model}' promoted to champion, replacing '{champion_label}'."
        if result is not None:
            evidence = f"Evidence: paired n={result.n_games}, log-loss gain {_gain_str(result.log_loss_gain)}."
        else:
            evidence = f"Evidence: {entry.note or 'promoted by evaluation pass'}."
        return f"{header}\n{body}\n{evidence}"

    elif entry.action == model_promotion.ACTION_ROLLED_BACK:
        header = f"[Model Rollback] {date_str}"
        body = f"Model '{entry.model}' rolled back to champion, replacing '{champion_label}'."
        if result is not None:
            evidence = f"Evidence: paired n={result.n_games}, log-loss gain {_gain_str(result.log_loss_gain)}."
        else:
            evidence = f"Evidence: {entry.note or 'rolled back by evaluation pass'}."
        return f"{header}\n{body}\n{evidence}"

    elif entry.action == model_promotion.ACTION_RETIRED:
        header = f"[Model Retirement] {date_str}"
        body = f"Challenger '{entry.model}' retired."
        reason = entry.note or (result.reason if result is not None else "retired by evaluation pass")
        if result is not None:
            evidence = f"Evidence: paired n={result.n_games}, log-loss gain {_gain_str(result.log_loss_gain)}. Reason: {reason}."
        else:
            evidence = f"Reason: {reason}."
        return f"{header}\n{body}\n{evidence}"

    return f"[Model Update] {date_str}\n{entry.model}: {entry.action}"


def format_candidate_registration_message(
    model: ModelVersion,
    candidate: Optional[Any],
    now: datetime,
) -> str:
    date_str = _aware_utc(now).strftime("%Y-%m-%d")
    model_name = f"{model.name} {model.version}"
    header = f"[New Challenger Registered] {date_str}"
    body = f"Model '{model_name}' registered as active challenger."

    if candidate is not None and getattr(candidate, "holdout", None) is not None:
        n_games = getattr(candidate.holdout, "n_games", 0)
        gain = getattr(candidate.gate, "gain", 0.0)
        holdout_gain = getattr(candidate, "holdout_gain", None)
        ci_low = getattr(holdout_gain, "ci_low", None) if holdout_gain else None
        ci_high = getattr(holdout_gain, "ci_high", None) if holdout_gain else None
        ci_str = "" if ci_low is None else f" (95% CI {ci_low:+.4f} .. {ci_high:+.4f})"
        evidence = f"Evidence: hold-out n={n_games}, gain {gain:+.4f}{ci_str}; passed historical gate."
    else:
        evidence = "Evidence: passed historical gate in candidate lab."

    return f"{header}\n{body}\n{evidence}"


class PromotionNotifier:
    """Dispatches Telegram notifications for model promotion events with error swallowing and token masking."""

    def __init__(
        self,
        sender: Optional[Callable[[str], bool]] = None,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        self._sender = sender
        self._bot_token = bot_token if bot_token is not None else settings.TELEGRAM_BOT_TOKEN
        self._chat_id = chat_id if chat_id is not None else settings.TELEGRAM_CHAT_ID

    @property
    def is_configured(self) -> bool:
        if self._sender is not None:
            return True
        return bool(
            self._bot_token
            and self._chat_id
            and "your_" not in self._bot_token
            and "your_" not in self._chat_id
        )

    def _mask_token(self, text: str) -> str:
        if self._bot_token and self._bot_token in text:
            return text.replace(self._bot_token, "***")
        return text

    def send(self, message: str) -> bool:
        if not self.is_configured:
            return False
        try:
            if self._sender is not None:
                return bool(self._sender(message))
            service = TelegramService(bot_token=self._bot_token, chat_id=self._chat_id)
            return service.send_plain_text_sync(message)
        except Exception as exc:
            masked = self._mask_token(str(exc))
            logger.warning("Promotion notification failed to send: %s", masked)
            return False

    def notify_pass_entry(self, entry: model_promotion.PassEntry, champion_label: str, now: datetime) -> bool:
        if entry.action not in (
            model_promotion.ACTION_PROMOTED,
            model_promotion.ACTION_ROLLED_BACK,
            model_promotion.ACTION_RETIRED,
        ):
            return False
        msg = format_pass_change_message(entry, champion_label, now)
        return self.send(msg)

    def notify_registered_candidate(
        self,
        model: ModelVersion,
        candidate: Optional[Any],
        now: datetime,
    ) -> bool:
        msg = format_candidate_registration_message(model, candidate, now)
        return self.send(msg)
