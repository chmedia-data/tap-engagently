# tap-engagently

Singer tap for the [Engagently Data API](https://docs.engagently.com/backend/data-api/), built with the [Meltano Singer SDK](https://sdk.meltano.com). It extracts the comments and discussions of one Engagently community.

The API reference is available from Engagently.

## Streams

| Stream | Endpoint | Key | Notes |
| --- | --- | --- | --- |
| `discussions` | `/1.0/discussions` | `id` | One per commented page. The id is the one the integrating site assigns. `stats` holds the comment and reply counts. |
| `commentaries` | `/1.0/commentaries` | `id` | Comments and replies, including author id and name. Deleted comments stay in the API with `is_deleted` and `deleted_at`, without content. |

Records are loaded as the API returns them. Nested objects (`author`, `content`, `moderation`, `visibility`, `stats`, `info`, the history arrays) stay objects. The tap names every field in the `fields` parameter, because some (`is_deleted`, `updated_at`, `labels`) are only returned when asked for.

## Sync

Both streams bookmark `changed_at`, which the tap sets to the latest change timestamp of a record:

- `commentaries`: `created_at`, `updated_at`, `moderation.status_at`, `visibility.status_at`, `deleted_at`, `featured_at`, `reported_at`. `updated_at` only moves on edits, so the other changes count separately.
- `discussions`: `created_at`, `updated_at`.

Without a bookmark the tap walks the whole entity with the cursor endpoint (`GET /1.0/<entity>?after=<id>`), starting at `after=000000000000000000000000`. Without that cursor the API starts at a community-specific default and skips objects with older ids, for example ones imported from an earlier platform. With a bookmark it calls `POST /1.0/<entity>/search` with a filter like `created_at gt '<since>' or updated_at gt '<since>' or ...`, where `since` is the bookmark minus `lookback_days`. Reaction counts have no timestamp. The lookback window refreshes them for comments with a tracked change in that window; a new reaction on an older comment stays stale until the next full run without state.

Search results come sorted by `created_at` and `id` (so ties cannot shift across a page boundary), not by `changed_at`, so the streams are unsorted and state is only final at the end of a run.

## Configuration

| Setting | Default | Description |
| --- | --- | --- |
| `api_host` | | Data API host of the community |
| `api_key` | | Data API key of the community, sent as `Authorization: Bearer`. The tap only calls read and search endpoints. |
| `lookback_days` | `7` | Re-read records changed this many days before the bookmark |
| `request_interval_seconds` | `0.5` | Minimum gap between HTTP attempts, retries and stream switches included |

Settings can come from environment variables (`TAP_ENGAGENTLY_API_HOST`, `TAP_ENGAGENTLY_API_KEY`, ...) with `--config ENV`, see `.env.example`.

## Development

```bash
just sync
just test
just lint
cp .env.example .env  # fill in the key
just run
```
