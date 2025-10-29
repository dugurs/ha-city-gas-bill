# custom_components/city_gas_bill/providers/__init__.py

"""Provider discovery for the City Gas Bill integration."""
import os
import importlib
import inspect
import logging
from pathlib import Path
from typing import Final

from .base import GasProvider

_LOGGER = logging.getLogger(__name__)

def discover_providers() -> dict[str, type[GasProvider]]:
    """Dynamically discover and load GasProvider classes from the providers directory."""
    providers = {}
    provider_dir = Path(__file__).parent

    for f in provider_dir.glob("*.py"):
        module_name = f.stem
        if module_name in ("__init__", "base"):
            continue

        try:
            module = importlib.import_module(f".{module_name}", __package__)
            for _, cls in inspect.getmembers(module, inspect.isclass):
                if issubclass(cls, GasProvider) and cls is not GasProvider:
                    provider_id = module_name
                    providers[provider_id] = cls
                    _LOGGER.debug("Discovered gas provider: %s", provider_id)
                    break
        except Exception as e:
            _LOGGER.error("Failed to load provider from %s: %s", f.name, e)

    return providers

AVAILABLE_PROVIDERS: Final = discover_providers()