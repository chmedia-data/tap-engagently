"""REST client for the Engagently Data API."""

from __future__ import annotations

import sys
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from singer_sdk.authenticators import BearerTokenAuthenticator
from singer_sdk.pagination import BaseAPIPaginator, BasePageNumberPaginator
from singer_sdk.streams import RESTStream

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterable

    import requests
    from singer_sdk import Tap
    from singer_sdk.helpers.types import Context

PAGE_SIZE = 100
# Without a cursor the iterate endpoints start at a community-specific default, not at the
# oldest object, so records with older ids (e.g. imported from an earlier platform) are skipped.
# The smallest ObjectId makes the walk start at the very beginning.
ZERO_CURSOR = "0" * 24


class CursorPaginator(BaseAPIPaginator[str | None]):
    """Cursor pagination of the iterate endpoints (`GET /1.0/<entity>?after=<id>`).

    The API returns `paging.after` with the id of the last object on the page and
    `after: null` with an empty page once the end is reached. The walk starts at
    `ZERO_CURSOR`, see there.
    """

    def __init__(self) -> None:
        super().__init__(start_value=ZERO_CURSOR)

    @override
    def get_next(self, response: requests.Response) -> str | None:
        payload = response.json()
        if not payload.get("objects"):
            return None
        return (payload.get("paging") or {}).get("after")


class SearchPaginator(BasePageNumberPaginator):
    """Page-number pagination of the search endpoints (`POST /1.0/<entity>/search`)."""

    def __init__(self, page_size: int) -> None:
        super().__init__(start_value=1)
        self._page_size = page_size

    @override
    def has_more(self, response: requests.Response) -> bool:
        return len(response.json().get("objects") or []) >= self._page_size


class Throttle:
    """Keeps a minimum gap between HTTP attempts.

    Keeps the load on the API low.
    """

    def __init__(self) -> None:
        self._last_attempt_at: float | None = None

    def wait(self, interval: float) -> None:
        """Sleep until `interval` seconds have passed since the last attempt."""
        if self._last_attempt_at is not None:
            remaining = interval - (time.monotonic() - self._last_attempt_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_attempt_at = time.monotonic()


def parse_timestamp(value: object) -> datetime | None:
    """Parse an API timestamp into an aware UTC datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_timestamp(value: datetime) -> str:
    """Format a datetime the way the API returns timestamps."""
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def get_path(row: dict[str, Any], dotted: str) -> object:
    """Read a dotted path such as `moderation.status_at` from a record."""
    value: object = row
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


class EngagentlyStream(RESTStream):
    """Base stream for one Data API entity.

    Without a bookmark the stream walks the whole entity through the iterate
    endpoint, which the docs recommend for full exports. With a bookmark it
    switches to the search endpoint and asks for everything that changed since
    the bookmark minus `lookback_days`.
    """

    entity: ClassVar[str]
    # fields to request; several (e.g. is_deleted) only come back when named
    fields: ClassVar[tuple[str, ...]]
    # timestamps that move when a record changes; they drive the search filter and changed_at
    change_timestamps: ClassVar[tuple[str, ...]]

    primary_keys: ClassVar[tuple[str, ...]] = ("id",)
    replication_key = "changed_at"
    # search results are sorted by created_at, not by changed_at
    is_sorted = False
    records_jsonpath = "$.objects[*]"
    page_size = PAGE_SIZE

    def __init__(self, tap: Tap, *args: Any, **kwargs: Any) -> None:
        super().__init__(tap, *args, **kwargs)
        self._changed_since: datetime | None = None
        # one clock for all streams of a run, so switching streams keeps the gap too
        self._throttle: Throttle = getattr(tap, "throttle", None) or Throttle()

    @override
    @property
    def url_base(self) -> str:
        host = str(self.config["api_host"]).strip().rstrip("/")
        if "://" not in host:
            host = f"https://{host}"
        return host

    @override
    @property
    def authenticator(self) -> BearerTokenAuthenticator:
        return BearerTokenAuthenticator(token=self.config["api_key"])

    @override
    @property
    def http_headers(self) -> dict[str, str]:
        return {"User-Agent": "tap-engagently"}

    @property
    def is_search(self) -> bool:
        """Whether this run reads changes through the search endpoint."""
        return self._changed_since is not None

    @override
    @property
    def http_method(self) -> str:
        return "POST" if self.is_search else "GET"

    @http_method.setter
    def http_method(self, value: str) -> None:
        # the method follows the sync mode, the SDK constructor still assigns it
        pass

    @override
    @property
    def path(self) -> str:
        return f"/1.0/{self.entity}/search" if self.is_search else f"/1.0/{self.entity}"

    @path.setter
    def path(self, value: str) -> None:
        pass

    def changed_since(self, context: Context | None) -> datetime | None:
        """Return the lower bound of the search filter, or None for a full walk."""
        bookmark = self.get_starting_timestamp(context)
        if bookmark is None:
            return None
        return bookmark - timedelta(days=int(self.config.get("lookback_days", 7)))

    def search_filter(self) -> str:
        """Build the search filter: any change timestamp after the lower bound."""
        if self._changed_since is None:
            msg = "search_filter needs a lower bound"
            raise RuntimeError(msg)
        since = format_timestamp(self._changed_since)
        return " or ".join(f"{field} gt '{since}'" for field in self.change_timestamps)

    @override
    def get_records(self, context: Context | None) -> Iterable[dict[str, Any]]:
        self._changed_since = self.changed_since(context)
        if self._changed_since is None:
            self.logger.info("No bookmark for %s, walking the full entity", self.name)
        else:
            self.logger.info("Searching %s changed since %s", self.name, self._changed_since)
        yield from super().get_records(context)

    @override
    def get_new_paginator(self) -> BaseAPIPaginator:
        if self.is_search:
            return SearchPaginator(self.page_size)
        return CursorPaginator()

    @override
    def get_url_params(
        self,
        context: Context | None,
        next_page_token: Any | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"size": self.page_size, "fields": ",".join(self.fields)}
        if self.is_search:
            params["page"] = next_page_token or 1
            # id breaks ties on created_at, so a page boundary cannot skip or repeat a record
            params["sort"] = "created_at:asc,id:asc"
        else:
            params["after"] = next_page_token or ZERO_CURSOR
        return params

    @override
    def prepare_request_payload(
        self,
        context: Context | None,
        next_page_token: Any | None,
    ) -> dict | None:
        if self.is_search:
            return {"filter": self.search_filter()}
        return None

    @override
    def _request(
        self,
        prepared_request: requests.PreparedRequest,
        context: Context | None,
    ) -> requests.Response:
        # every HTTP attempt, retries included, goes through here
        self._throttle.wait(float(self.config.get("request_interval_seconds", 0.5)))
        return super()._request(prepared_request, context)

    @override
    def post_process(
        self,
        row: dict,
        context: Context | None = None,
    ) -> dict | None:
        if not row.get("id"):
            self.logger.warning("Dropping %s record without id", self.name)
            return None
        timestamps = [parse_timestamp(get_path(row, f)) for f in self.change_timestamps]
        present = [ts for ts in timestamps if ts is not None]
        row["changed_at"] = format_timestamp(max(present)) if present else None
        return row
