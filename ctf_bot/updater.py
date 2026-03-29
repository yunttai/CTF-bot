from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import os

import aiohttp
from dotenv import load_dotenv

from ctf_bot.api_clients import CTFTimeClient, KCTFClient
from ctf_bot.dedupe import normalize_title, titles_overlap
from ctf_bot.models import CTFEvent, KCTFContest, StoredContest
from ctf_bot.storage import ContestRepository, DEFAULT_DB_PATH


def _read_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return int(value)


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return float(value)


def _event_to_stored_contest(event: CTFEvent, status: str, scraped_at: datetime) -> StoredContest:
    return StoredContest(
        contest_key=f"ctftime:{event.id}",
        source="ctftime",
        source_label="CTFtime",
        source_id=str(event.id),
        title=event.title,
        normalized_title=normalize_title(event.title),
        status=status,
        detail_url=event.ctftime_url,
        organizer=", ".join(event.organizers) if event.organizers else None,
        start=event.start,
        finish=event.finish,
        format=event.format,
        weight=event.weight,
        participants=event.participants,
        onsite=event.onsite,
        location=event.location or None,
        image_url=event.logo_url,
        registration_period=None,
        contest_period=None,
        finals_period=None,
        mode="온사이트" if event.onsite else "온라인",
        scraped_at=scraped_at,
    )


def _kctf_to_stored_contest(contest: KCTFContest, status: str, scraped_at: datetime) -> StoredContest:
    return StoredContest(
        contest_key=f"k-ctf:{contest.id}",
        source="k-ctf",
        source_label="K-CTF",
        source_id=contest.id,
        title=contest.title,
        normalized_title=normalize_title(contest.title),
        status=status,
        detail_url=contest.detail_url,
        organizer=contest.organizer,
        start=contest.start,
        finish=contest.finish,
        format=None,
        weight=None,
        participants=None,
        onsite=None,
        location=contest.location,
        image_url=contest.poster_url,
        registration_period=contest.registration_period,
        contest_period=contest.contest_period,
        finals_period=contest.finals_period,
        mode=contest.mode,
        scraped_at=scraped_at,
    )


def _resolve_kctf_status(contest: KCTFContest, fallback_status: str, now: datetime) -> str | None:
    if contest.start is not None and contest.finish is not None:
        if contest.start <= now < contest.finish:
            return "ongoing"
        if contest.start >= now:
            return "upcoming"
        return None
    return fallback_status


def _should_keep_snapshot_contest(contest: StoredContest, now: datetime) -> bool:
    if contest.finish is not None and contest.finish <= now:
        return False
    if contest.status == "upcoming" and contest.start is not None and contest.start < now:
        return False
    if contest.status == "ongoing" and contest.start is not None and contest.start > now:
        return False
    return contest.status in {"upcoming", "ongoing"}


async def _enrich_kctf_contests(client: KCTFClient, contests: list[KCTFContest]) -> list[KCTFContest]:
    async def enrich(contest: KCTFContest) -> KCTFContest:
        try:
            return await client.fetch_contest_details(contest)
        except Exception as exc:
            logging.warning("Failed to enrich K-CTF contest %s: %s", contest.title, exc)
            return contest

    return await asyncio.gather(*(enrich(contest) for contest in contests))


async def build_snapshot_records() -> list[StoredContest]:
    load_dotenv()

    ctftime_base_url = os.getenv("CTFTIME_BASE_URL", "https://ctftime.org").strip().rstrip("/")
    ctftime_fetch_limit = _read_int("CTFTIME_FETCH_LIMIT", 100)
    kctf_base_url = os.getenv("KCTF_BASE_URL", "http://k-ctf.org").strip().rstrip("/")
    timeout_seconds = _read_float("HTTP_TIMEOUT_SECONDS", 20.0)
    scraped_at = datetime.now(timezone.utc)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_seconds)) as session:
        ctftime = CTFTimeClient(session, ctftime_base_url, ctftime_fetch_limit)
        kctf = KCTFClient(session, kctf_base_url)

        all_ctftime_events, kctf_upcoming, kctf_ongoing = await asyncio.gather(
            ctftime.all_events(limit=None),
            kctf.list_contests(status="upcoming", limit=None),
            kctf.list_contests(status="ongoing", limit=None),
        )

        now = datetime.now(timezone.utc)
        stored_contests: list[StoredContest] = []

        ctftime_titles: list[str] = []
        for event in all_ctftime_events:
            if event.start <= now < event.finish:
                stored_contests.append(_event_to_stored_contest(event, "ongoing", scraped_at))
                ctftime_titles.append(event.title)
            elif event.start >= now:
                stored_contests.append(_event_to_stored_contest(event, "upcoming", scraped_at))
                ctftime_titles.append(event.title)

        enriched_upcoming, enriched_ongoing = await asyncio.gather(
            _enrich_kctf_contests(kctf, kctf_upcoming),
            _enrich_kctf_contests(kctf, kctf_ongoing),
        )

        for fallback_status, contests in (("ongoing", enriched_ongoing), ("upcoming", enriched_upcoming)):
            for contest in contests:
                resolved_status = _resolve_kctf_status(contest, fallback_status, now)
                if resolved_status is None:
                    continue
                if any(titles_overlap(contest.title, title) for title in ctftime_titles):
                    continue
                stored_contests.append(_kctf_to_stored_contest(contest, resolved_status, scraped_at))

        stored_contests = [contest for contest in stored_contests if _should_keep_snapshot_contest(contest, now)]
        stored_contests.sort(
            key=lambda contest: (
                1 if contest.start is None else 0,
                contest.start or datetime.max.replace(tzinfo=timezone.utc),
                contest.title.casefold(),
            )
        )
        return stored_contests


async def update_snapshot(db_path: str | None = None) -> tuple[str, int]:
    repository = ContestRepository(db_path or os.getenv("CTF_DB_PATH", DEFAULT_DB_PATH))
    contests = await build_snapshot_records()
    refreshed_at = datetime.now(timezone.utc)
    repository.replace_snapshot(contests, refreshed_at=refreshed_at)
    return str(repository.db_path), len(contests)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path, count = asyncio.run(update_snapshot())
    logging.info("Updated CTF snapshot DB at %s with %s row(s)", db_path, count)


if __name__ == "__main__":
    main()
