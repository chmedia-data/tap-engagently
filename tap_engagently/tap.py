"""Engagently tap class."""

from __future__ import annotations

import sys
from functools import cached_property

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

from singer_sdk import Tap
from singer_sdk import typing as th

from tap_engagently import streams
from tap_engagently.client import Throttle


class TapEngagently(Tap):
    """Singer tap for the Engagently Data API."""

    name = "tap-engagently"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "api_host",
            th.StringType(nullable=False),
            required=True,
            title="API Host",
            description="Data API host of the community.",
        ),
        th.Property(
            "api_key",
            th.StringType(nullable=False),
            required=True,
            secret=True,
            title="API Key",
            description="Data API key of the community.",
        ),
        th.Property(
            "lookback_days",
            th.IntegerType(nullable=False),
            default=7,
            description=(
                "Re-read records changed this many days before the bookmark, so reaction "
                "counts, which carry no timestamp, get refreshed."
            ),
        ),
        th.Property(
            "request_interval_seconds",
            th.NumberType(nullable=False),
            default=0.5,
            description="Minimum gap between HTTP attempts, retries included.",
        ),
    ).to_dict()

    @cached_property
    def throttle(self) -> Throttle:
        """Shared request throttle for all streams of this run."""
        return Throttle()

    @override
    def discover_streams(self) -> list[streams.EngagentlyStream]:
        return [
            streams.DiscussionsStream(self),
            streams.CommentariesStream(self),
        ]


if __name__ == "__main__":
    TapEngagently.cli()
