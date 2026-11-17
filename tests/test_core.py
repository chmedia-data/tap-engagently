"""Unit tests for tap-engagently."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
import requests

from tap_engagently import client
from tap_engagently.client import CursorPaginator, SearchPaginator
from tap_engagently.tap import TapEngagently

CONFIG = {"api_host": "api.example.com", "api_key": "test-token"}


def _streams(config: dict | None = None) -> dict:
    tap = TapEngagently(config=config or CONFIG)
    return {stream.name: stream for stream in tap.discover_streams()}


def _response(payload: dict) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(payload).encode()
    return response


def test_discovers_streams() -> None:
    assert set(_streams()) == {"commentaries", "discussions"}


def test_schemas_are_strict_and_cover_requested_fields() -> None:
    for stream in _streams().values():
        properties = set(stream.schema["properties"])
        assert stream.schema["additionalProperties"] is False
        assert properties == {*stream.fields, "changed_at"}
        assert stream.replication_key == "changed_at"


def test_url_base_accepts_host_or_url() -> None:
    assert _streams()["discussions"].url_base == "https://api.example.com"
    stream = _streams({**CONFIG, "api_host": "https://api.example.org/"})["discussions"]
    assert stream.url_base == "https://api.example.org"


def test_without_bookmark_walks_iterate_endpoint() -> None:
    stream = _streams()["commentaries"]
    stream._changed_since = stream.changed_since(None)

    assert stream.http_method == "GET"
    assert stream.path == "/1.0/commentaries"
    assert isinstance(stream.get_new_paginator(), CursorPaginator)
    assert stream.prepare_request_payload(None, None) is None
    params = stream.get_url_params(None, "67883b99f0d517edfb939ac8")
    assert params["after"] == "67883b99f0d517edfb939ac8"
    assert params["size"] == 100
    assert "author" in params["fields"].split(",")


def test_with_bookmark_searches_with_lookback(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _streams({**CONFIG, "lookback_days": 3})["commentaries"]
    bookmark = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(stream, "get_starting_timestamp", lambda _context: bookmark)
    stream._changed_since = stream.changed_since(None)

    assert stream.http_method == "POST"
    assert stream.path == "/1.0/commentaries/search"
    assert isinstance(stream.get_new_paginator(), SearchPaginator)
    params = stream.get_url_params(None, None)
    assert params["page"] == 1
    assert params["sort"] == "created_at:asc,id:asc"
    since = "'2026-11-07T06:00:00.000000Z'"
    assert stream.prepare_request_payload(None, None) == {
        "filter": " or ".join(f"{field} gt {since}" for field in stream.change_timestamps)
    }


def test_changed_at_is_latest_change_timestamp() -> None:
    stream = _streams()["commentaries"]
    row = stream.post_process(
        {
            "id": "c1",
            "created_at": "2025-01-15T22:50:01.073000Z",
            "moderation": {"status": "accepted", "status_at": "2025-02-21T08:31:52.371000Z"},
            "visibility": {"status": "visible", "status_at": "2025-01-15T22:50:01.073000Z"},
        }
    )
    assert row is not None
    assert row["changed_at"] == "2025-02-21T08:31:52.371000Z"


def test_changed_at_includes_deletion() -> None:
    stream = _streams()["commentaries"]
    row = stream.post_process(
        {
            "id": "c1",
            "created_at": "2025-02-27T08:20:00.058000Z",
            "is_deleted": True,
            "deleted_at": "2025-03-05T12:32:35.174000Z",
        }
    )
    assert row is not None
    assert row["changed_at"] == "2025-03-05T12:32:35.174000Z"


def test_post_process_drops_rows_without_id() -> None:
    assert _streams()["discussions"].post_process({"created_at": "2025-01-01T00:00:00Z"}) is None


def test_full_walk_starts_at_zero_cursor() -> None:
    stream = _streams()["discussions"]
    stream._changed_since = None

    assert CursorPaginator().current_value == "0" * 24
    assert stream.get_url_params(None, None)["after"] == "0" * 24


def test_cursor_paginator_stops_on_empty_page() -> None:
    paginator = CursorPaginator()
    page = _response({"paging": {"after": "abc"}, "objects": [{"id": "1"}]})
    assert paginator.get_next(page) == "abc"
    end = _response({"paging": {"before": None, "after": None}, "objects": []})
    assert paginator.get_next(end) is None


def test_search_paginator_stops_on_short_page() -> None:
    paginator = SearchPaginator(page_size=2)
    assert paginator.has_more(_response({"objects": [{"id": "1"}, {"id": "2"}]}))
    assert not paginator.has_more(_response({"objects": [{"id": "1"}]}))


def test_featured_and_reported_count_as_changes() -> None:
    stream = _streams()["commentaries"]
    row = stream.post_process(
        {
            "id": "c1",
            "created_at": "2025-01-01T00:00:00.000000Z",
            "is_featured": True,
            "featured_at": "2025-06-01T00:00:00.000000Z",
        }
    )
    assert row is not None
    assert row["changed_at"] == "2025-06-01T00:00:00.000000Z"
    assert "featured_at" in stream.change_timestamps
    assert "reported_at" in stream.change_timestamps


def test_search_sort_has_tie_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _streams()["commentaries"]
    bookmark = datetime(2026, 11, 10, tzinfo=timezone.utc)
    monkeypatch.setattr(stream, "get_starting_timestamp", lambda _context: bookmark)
    stream._changed_since = stream.changed_since(None)
    assert stream.get_url_params(None, 2)["sort"] == "created_at:asc,id:asc"


def test_streams_share_one_throttle() -> None:
    streams = list(_streams().values())
    assert streams[0]._throttle is streams[1]._throttle


def test_throttle_waits_between_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = {"now": 100.0}
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["now"] += seconds

    monkeypatch.setattr(client.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(client.time, "sleep", fake_sleep)
    throttle = client.Throttle()

    throttle.wait(0.5)
    clock["now"] += 0.2
    throttle.wait(0.5)
    clock["now"] += 1.0
    throttle.wait(0.5)

    assert sleeps == [pytest.approx(0.3)]


def test_every_http_attempt_is_throttled(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = _streams()["discussions"]
    waits: list[float] = []
    monkeypatch.setattr(stream._throttle, "wait", waits.append)
    monkeypatch.setattr(
        stream.requests_session,
        "send",
        lambda *_args, **_kwargs: _response({"paging": {"after": None}, "objects": []}),
    )
    request = stream.prepare_request(None, None)

    stream._request(request, None)
    stream._request(request, None)

    assert waits == [0.5, 0.5]


def test_saved_state_switches_to_search(requests_mock_session: list) -> None:
    state = {
        "bookmarks": {
            "commentaries": {
                "replication_key": "changed_at",
                "replication_key_value": "2026-11-05T12:00:00.000000Z",
            }
        }
    }
    tap = TapEngagently(config={**CONFIG, "lookback_days": 2}, state=state)
    stream = tap.streams["commentaries"]
    # the SDK resolves the bookmark at sync start, before get_records runs
    stream._write_starting_replication_value(None)

    records = list(stream.get_records(None))

    assert records == [{"id": "c1", "created_at": "2026-11-04T08:00:00.000000Z"}]
    method, url, body = requests_mock_session[0]
    assert method == "POST"
    assert url.startswith("https://api.example.com/1.0/commentaries/search?")
    assert json.loads(body)["filter"].startswith("created_at gt '2026-11-03T12:00:00.000000Z'")


@pytest.fixture
def requests_mock_session(monkeypatch: pytest.MonkeyPatch) -> list:
    calls: list = []

    def fake_send(_session: object, request: requests.PreparedRequest, **_kwargs: object):
        calls.append((request.method, request.url, request.body))
        return _response(
            {
                "paging": {"page": 1, "size": 100},
                "objects": [{"id": "c1", "created_at": "2026-11-04T08:00:00.000000Z"}],
            }
        )

    monkeypatch.setattr(requests.Session, "send", fake_send)
    monkeypatch.setattr(client.time, "sleep", lambda _seconds: None)
    return calls
