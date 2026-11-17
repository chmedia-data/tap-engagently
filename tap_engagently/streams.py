"""Stream definitions for tap-engagently.

Records are loaded as the Data API returns them. Nested objects stay objects and
are flattened downstream.
"""

from __future__ import annotations

from typing import Any

from singer_sdk import typing as th

from tap_engagently.client import EngagentlyStream


def _schema(*properties: Any) -> dict[str, Any]:
    """Build a strict top-level schema so new upstream keys show up as drift."""
    schema = th.PropertiesList(*properties).to_dict()
    schema["additionalProperties"] = False
    return schema


def _object() -> th.ObjectType:
    return th.ObjectType(additional_properties=True)


class CommentariesStream(EngagentlyStream):
    """Comments and replies, including deleted ones (`is_deleted`, without content)."""

    name = "commentaries"
    entity = "commentaries"
    fields = (
        "id",
        "url",
        "level",
        "asset_id",
        "asset_type",
        "asset",
        "author",
        "content",
        "content_history",
        "moderation",
        "moderation_history",
        "visibility",
        "visibility_history",
        "stats",
        "feedback",
        "participation",
        "primary_parent_id",
        "direct_parent_id",
        "in_reply_to_id",
        "is_edited",
        "is_featured",
        "featured_at",
        "is_reported",
        "reported_at",
        "is_deleted",
        "deleted_at",
        "created_at",
        "updated_at",
    )
    # updated_at only moves on edits; moderation, visibility, deletion, featuring and
    # reports carry their own timestamps. Reaction counts have none, lookback_days
    # covers them for recent comments.
    change_timestamps = (
        "created_at",
        "updated_at",
        "moderation.status_at",
        "visibility.status_at",
        "deleted_at",
        "featured_at",
        "reported_at",
    )
    schema = _schema(
        th.Property("id", th.StringType, required=True),
        th.Property("url", th.StringType),
        th.Property("level", th.IntegerType),
        th.Property("asset_id", th.StringType),
        th.Property("asset_type", th.StringType),
        th.Property("asset", _object()),
        th.Property("author", _object()),
        th.Property("content", _object()),
        th.Property("content_history", th.ArrayType(_object())),
        th.Property("moderation", _object()),
        th.Property("moderation_history", th.ArrayType(_object())),
        th.Property("visibility", _object()),
        th.Property("visibility_history", th.ArrayType(_object())),
        th.Property("stats", _object()),
        th.Property("feedback", _object()),
        th.Property("participation", _object()),
        th.Property("primary_parent_id", th.StringType),
        th.Property("direct_parent_id", th.StringType),
        th.Property("in_reply_to_id", th.StringType),
        th.Property("is_edited", th.BooleanType),
        th.Property("is_featured", th.BooleanType),
        th.Property("featured_at", th.DateTimeType),
        th.Property("is_reported", th.BooleanType),
        th.Property("reported_at", th.DateTimeType),
        th.Property("is_deleted", th.BooleanType),
        th.Property("deleted_at", th.DateTimeType),
        th.Property("created_at", th.DateTimeType),
        th.Property("updated_at", th.DateTimeType),
        th.Property("changed_at", th.DateTimeType),
    )


class DiscussionsStream(EngagentlyStream):
    """Discussions, one per commented page. The id is assigned by the integrating site."""

    name = "discussions"
    entity = "discussions"
    fields = (
        "id",
        "type",
        "name",
        "info",
        "article_refs",
        "labels",
        "settings",
        "state",
        "is_live",
        "published_at",
        "stats",
        "created_at",
        "updated_at",
    )
    change_timestamps = ("created_at", "updated_at")
    schema = _schema(
        th.Property("id", th.StringType, required=True),
        th.Property("type", th.StringType),
        th.Property("name", th.StringType),
        th.Property("info", _object()),
        th.Property("article_refs", th.ArrayType(_object())),
        th.Property("labels", th.ArrayType(th.StringType)),
        th.Property("settings", _object()),
        th.Property("state", th.StringType),
        th.Property("is_live", th.BooleanType),
        th.Property("published_at", th.DateTimeType),
        th.Property("stats", _object()),
        th.Property("created_at", th.DateTimeType),
        th.Property("updated_at", th.DateTimeType),
        th.Property("changed_at", th.DateTimeType),
    )
