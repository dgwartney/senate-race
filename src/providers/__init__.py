"""Election data providers and the factory that picks one from configuration."""
from src.providers.base import ElectionDataProvider, ProviderError
from src.providers.factory import PROVIDERS, create_provider

__all__ = ["ElectionDataProvider", "ProviderError", "create_provider", "PROVIDERS"]
