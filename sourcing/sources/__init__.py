"""Source-type registry. Adding a source type means adding a class here and
an entry in sources.yaml; the evaluator never changes."""
from __future__ import annotations

from .base import SourceType
from .retail import RetailOnline, RetailStore

IMPLEMENTED: dict[str, type[SourceType]] = {cls.key: cls for cls in (RetailStore, RetailOnline)}


class SourceNotAvailable(Exception):
    pass


def get_source(key: str, settings) -> SourceType:
    types = settings.sources.get("types", {})
    if key not in types:
        raise SourceNotAvailable(
            f"source type {key!r} is not in sources.yaml. Known types: {', '.join(types)}")
    cls = IMPLEMENTED.get(key)
    if cls is None:
        raise SourceNotAvailable(
            f"source type {key!r} is built in phase {types[key].get('phase')}; it isn't available yet")
    return cls(types[key])
