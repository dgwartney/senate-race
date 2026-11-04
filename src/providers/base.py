"""The provider interface every election data source implements."""
from abc import ABC, abstractmethod
from typing import List, Optional

from src.models import EarlyVote, RaceData


class ProviderError(Exception):
    """Raised by any provider when results cannot be retrieved or understood.

    Providers wrap transport and parsing errors in this exception so calling code
    never has to know which library or data source a provider uses.
    """

class ElectionDataProvider(ABC):
    """Source of live race data. The app depends only on this interface."""

    name: str = "unknown"
    attribution: Optional[str] = None

    @abstractmethod
    def get_live_races(self) -> List[RaceData]:
        """Return the current state of every tracked race, or raise ProviderError."""

    def get_early_vote(self) -> Optional[EarlyVote]:
        """Optional: early ballots cast so far, or None if this source doesn't publish them."""
        return None
