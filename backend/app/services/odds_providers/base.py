"""
Abstract provider interface for external odds feeds.
"""
from typing import List, Protocol, runtime_checkable

from app.services.odds_api_service import GameQuote


@runtime_checkable
class OddsProvider(Protocol):
    """
    Protocol for external odds providers supplying game-line quotes.
    """

    @property
    def name(self) -> str:
        """Provider identifier (e.g. 'the_odds_api', 'sportsgameodds')."""
        ...

    @property
    def is_configured(self) -> bool:
        """True if the provider has API credentials and configuration set."""
        ...

    def fetch_game_lines(self) -> List[GameQuote]:
        """
        Fetches moneyline (h2h), spread, and totals quotes for upcoming NBA games.
        Returns a list of GameQuote instances; returns empty list if unconfigured or on error.
        """
        ...
