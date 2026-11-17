default:
    @just --list

install:
    uv tool install .

sync:
    uv sync

about:
    uv run tap-engagently --about

test:
    uv run pytest

lint:
    uvx ruff check .
    uvx ruff format --check .

# full run against the API configured in .env, records to output/
run:
    mkdir -p output
    uv run tap-engagently --config ENV > output/run.singer

meltano-run:
    meltano run tap-engagently target-jsonl
