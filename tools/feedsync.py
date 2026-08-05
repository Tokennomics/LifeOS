"""Refresh venue feeds on a schedule.

**Ingested content that silently stops updating is worse than less content.** A weekend
digest showing last month's listings looks identical to one showing this month's, right up
until someone turns up at a club on the wrong night — so the sync loop is not a nice-to-have
on top of the feeds feature, it is the half that makes the other half honest.

Usage on the VPS (the `feedsync` service in `deploy/vps/compose.yml` runs this):
    python -m tools.feedsync --interval 360

`--interval` is the politeness floor, not the loop period: a feed synced more recently than
that is skipped, so restarting the container in a crash loop cannot turn into a hammering of
somebody's small venue server. Running it once with `--once` is the cron-style path.

Everything it does is also reachable at `POST /v1/feeds/sync` — this exists so refreshing
does not depend on anyone having the app open.
"""

import argparse
import datetime
import sys
import time

from modules.feeds import ingest
from substrate import load_config
from substrate.bus import Bus
from substrate.graph import Graph
from substrate.migrate import migrate

DEFAULT_INTERVAL_MINUTES = 360


def _graph(cfg: dict) -> Graph:
    return Graph(migrate(cfg), Bus(), default_owner=cfg.get("owner", {}).get("id"))


def run_once(graph: Graph, min_interval_minutes: int = DEFAULT_INTERVAL_MINUTES) -> dict:
    return ingest.sync_all(graph, min_interval_minutes=min_interval_minutes)


def describe(result: dict, now: datetime.datetime | None = None) -> str:
    """One line per run, because a log nobody can skim is a log nobody reads."""
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    failed = [r for r in result.get("results", []) if r.get("status") != "ok"]
    line = (f"{stamp}  synced={result.get('feeds', 0)} "
            f"added={result.get('added', 0)} updated={result.get('updated', 0)} "
            f"skipped_recent={len(result.get('skipped_recent', []))}")
    if failed:
        line += "  FAILED=" + ",".join(str(r.get("url", "?")) for r in failed)
    return line


def main(argv=None):
    parser = argparse.ArgumentParser(description="Refresh venue feeds")
    parser.add_argument("--config", default=None)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_MINUTES,
                        help="minutes a feed must rest before it is fetched again")
    parser.add_argument("--sleep", type=int, default=0,
                        help="seconds between passes; 0 means run once and exit")
    parser.add_argument("--once", action="store_true", help="same as --sleep 0")
    args = parser.parse_args(argv)

    graph = _graph(load_config(args.config))
    sleep_for = 0 if args.once else max(0, args.sleep)
    while True:
        try:
            print(describe(run_once(graph, args.interval)), flush=True)
        except Exception as exc:        # a scheduler that dies on one bad pass is not one
            print(f"SYNC FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        if not sleep_for:
            return
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
