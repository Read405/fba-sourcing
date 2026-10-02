"""Selling-channel registry. Adding a channel means adding a class here, its
fee data file and a config.yaml path; the evaluator never changes."""
from __future__ import annotations

from .amazon_fba import AmazonFBA
from .base import Channel

IMPLEMENTED: dict[str, type[Channel]] = {cls.key: cls for cls in (AmazonFBA,)}


class ChannelNotAvailable(Exception):
    pass


def get_channel(key: str, settings) -> Channel:
    if key not in settings.active_channels:
        raise ChannelNotAvailable(f"channel {key!r} is not active in config.yaml")
    cls = IMPLEMENTED.get(key)
    if cls is None:
        raise ChannelNotAvailable(f"channel {key!r} isn't built yet")
    return cls(settings)
