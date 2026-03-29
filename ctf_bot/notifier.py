from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import logging
import os
from pathlib import Path

import aiohttp
import discord
from dotenv import load_dotenv

from ctf_bot.formatters import build_stored_contest_embeds
from ctf_bot.models import StoredContest
from ctf_bot.storage import DEFAULT_DB_PATH, ContestRepository, StorageError


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return float(value)


def _status_rank(status: str) -> int:
    order = {
        "ongoing": 0,
        "upcoming": 1,
    }
    return order.get(status, 99)


def _status_label(status: str) -> str:
    labels = {
        "ongoing": "진행 중",
        "upcoming": "예정",
    }
    return labels.get(status, status)


def _load_contests(db_path: str | Path) -> list[StoredContest]:
    repository = ContestRepository(str(db_path))
    return repository.list_contests()


def find_new_contests(previous_db_path: str | Path, current_db_path: str | Path) -> list[StoredContest]:
    current_path = Path(current_db_path)
    if not current_path.exists():
        raise StorageError(f"Current CTF DB not found: {current_path}")

    previous_path = Path(previous_db_path)
    if not previous_path.exists():
        logging.info("Previous CTF DB not found at %s. Skipping notifications for bootstrap run.", previous_path)
        return []

    previous_contests = _load_contests(previous_path)
    current_contests = _load_contests(current_path)

    previous_keys = {contest.contest_key for contest in previous_contests}
    new_contests = [contest for contest in current_contests if contest.contest_key not in previous_keys]
    new_contests.sort(
        key=lambda contest: (
            _status_rank(contest.status),
            contest.start or datetime.max.replace(tzinfo=timezone.utc),
            contest.title.casefold(),
        )
    )
    return new_contests


async def send_new_contest_notifications(
    *,
    webhook_url: str,
    contests: list[StoredContest],
    timeout_seconds: float,
) -> int:
    if not contests:
        logging.info("No new CTF contests detected.")
        return 0

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        sent = 0
        for contest in contests:
            embed = build_stored_contest_embeds("신규 CTF", [contest])[0]
            await webhook.send(
                content=f"새 CTF 감지 | {_status_label(contest.status)} | {contest.source_label}",
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            sent += 1
        return sent


async def notify_from_snapshot_diff(
    *,
    previous_db_path: str | Path,
    current_db_path: str | Path,
    webhook_url: str | None,
    timeout_seconds: float,
    dry_run: bool,
) -> int:
    contests = find_new_contests(previous_db_path, current_db_path)
    if not contests:
        return 0

    if dry_run:
        for contest in contests:
            logging.info(
                "Dry run notification: [%s] %s (%s)",
                contest.source_label,
                contest.title,
                _status_label(contest.status),
            )
        return len(contests)

    if not webhook_url:
        logging.info("DISCORD_WEBHOOK_URL is not set. Skipping webhook notifications.")
        return 0

    return await send_new_contest_notifications(
        webhook_url=webhook_url,
        contests=contests,
        timeout_seconds=timeout_seconds,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Notify Discord webhook about newly discovered CTF contests.")
    parser.add_argument(
        "--previous-db",
        default=os.getenv("PREVIOUS_CTF_DB_PATH", "data/ctf_snapshot.previous.db"),
        help="Path to the previous SQLite snapshot.",
    )
    parser.add_argument(
        "--current-db",
        default=os.getenv("CTF_DB_PATH", DEFAULT_DB_PATH),
        help="Path to the current SQLite snapshot.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the new contests that would be notified without calling Discord.",
    )
    return parser


def main() -> None:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sent = asyncio.run(
        notify_from_snapshot_diff(
            previous_db_path=args.previous_db,
            current_db_path=args.current_db,
            webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip() or None,
            timeout_seconds=_read_float("HTTP_TIMEOUT_SECONDS", 10.0),
            dry_run=args.dry_run,
        )
    )
    logging.info("Processed %s new contest notification(s).", sent)


if __name__ == "__main__":
    main()
