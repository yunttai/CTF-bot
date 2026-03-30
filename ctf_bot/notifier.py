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
from ctf_bot.storage import DEFAULT_DB_PATH, ContestRepository, StorageError


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return float(value)


def _status_label(status: str) -> str:
    labels = {
        "ongoing": "진행 중",
        "upcoming": "예정",
    }
    return labels.get(status, status)


async def notify_unnotified_contests(
    *,
    db_path: str | Path,
    webhook_url: str | None,
    timeout_seconds: float,
    dry_run: bool,
) -> int:
    repository = ContestRepository(str(db_path))
    contests = repository.list_unnotified_contests()
    if not contests:
        logging.info("No CTF contests to notify.")
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

    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        webhook = discord.Webhook.from_url(webhook_url, session=session)
        sent = 0
        for contest in contests:
            embed = build_stored_contest_embeds("CTF 알림", [contest])[0]
            try:
                await webhook.send(
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except discord.DiscordException as exc:
                logging.exception("Failed to send Discord notification for %s: %s", contest.title, exc)
                continue
            repository.mark_contests_notified([contest.contest_key], notified_at=datetime.now(timezone.utc))
            sent += 1
        return sent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Notify Discord webhook about unnotified CTF contests.")
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
        notify_unnotified_contests(
            db_path=args.current_db,
            webhook_url=os.getenv("DISCORD_WEBHOOK_URL", "").strip() or None,
            timeout_seconds=_read_float("HTTP_TIMEOUT_SECONDS", 30.0),
            dry_run=args.dry_run,
        )
    )
    logging.info("Processed %s contest notification(s).", sent)


if __name__ == "__main__":
    main()
