from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Any
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from ctf_bot.models import CTFEvent, KCTFAnnouncement, KCTFContest, KCTFUpdateLog


class APIClientError(RuntimeError):
    """Raised when a remote API call fails."""


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


KST = timezone(timedelta(hours=9))
KCTF_RANGE_RE = re.compile(
    r"(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*(\d{2}):(\d{2})\s*-\s*(\d{4})년\s*(\d{2})월\s*(\d{2})일\s*(\d{2}):(\d{2})"
)


def _parse_kctf_range(value: str) -> tuple[datetime, datetime] | None:
    match = KCTF_RANGE_RE.search(value)
    if match is None:
        return None

    start = datetime(
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        int(match.group(4)),
        int(match.group(5)),
        tzinfo=KST,
    ).astimezone(timezone.utc)
    finish = datetime(
        int(match.group(6)),
        int(match.group(7)),
        int(match.group(8)),
        int(match.group(9)),
        int(match.group(10)),
        tzinfo=KST,
    ).astimezone(timezone.utc)
    return start, finish


class CTFTimeClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, fetch_limit: int = 100) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._fetch_limit = max(fetch_limit, 20)

    async def _fetch_events(self, limit: int | None) -> list[CTFEvent]:
        fetch_size = self._fetch_limit if limit is None else max(limit, self._fetch_limit)
        params = {"limit": str(fetch_size)}
        url = f"{self._base_url}/api/v1/events/"
        async with self._session.get(url, params=params) as response:
            if response.status != 200:
                text = await response.text()
                raise APIClientError(f"CTFtime API request failed with {response.status}: {text[:200]}")

            payload = await response.json()

        if not isinstance(payload, list):
            raise APIClientError("CTFtime API returned an unexpected response format.")

        events: list[CTFEvent] = []
        for item in payload:
            try:
                event = CTFEvent(
                    id=int(item["id"]),
                    title=str(item["title"]),
                    start=_parse_datetime(item["start"]),
                    finish=_parse_datetime(item["finish"]),
                    ctftime_url=str(item["ctftime_url"]),
                    format=str(item.get("format", "unknown")),
                    weight=float(item.get("weight", 0.0) or 0.0),
                    participants=int(item["participants"]) if item.get("participants") is not None else None,
                    onsite=bool(item.get("onsite", False)),
                    location=str(item.get("location", "") or ""),
                    organizers=tuple(
                        str(organizer.get("name", "")).strip()
                        for organizer in item.get("organizers", [])
                        if str(organizer.get("name", "")).strip()
                    ),
                    logo_url=str(item.get("logo", "")).strip() or None,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise APIClientError("Failed to parse CTFtime response payload.") from exc

            events.append(event)

        events.sort(key=lambda event: event.start)
        return events

    async def all_events(self, limit: int | None = None) -> list[CTFEvent]:
        return await self._fetch_events(limit)

    async def upcoming_events(self, limit: int | None = None) -> list[CTFEvent]:
        now = datetime.now(timezone.utc)
        fetch_limit = None if limit is None else limit * 5
        events = await self._fetch_events(fetch_limit)
        filtered = [event for event in events if event.start >= now]
        return filtered if limit is None else filtered[:limit]

    async def ongoing_events(self, limit: int | None = None) -> list[CTFEvent]:
        now = datetime.now(timezone.utc)
        fetch_limit = None if limit is None else limit * 5
        events = await self._fetch_events(fetch_limit)
        filtered = [event for event in events if event.start <= now < event.finish]
        return filtered if limit is None else filtered[:limit]

    async def search_events(self, keyword: str, limit: int | None = None) -> list[CTFEvent]:
        keyword_folded = keyword.casefold()
        fetch_limit = None if limit is None else limit * 10
        events = await self._fetch_events(fetch_limit)
        filtered = [event for event in events if keyword_folded in event.title.casefold()]
        return filtered if limit is None else filtered[:limit]


class KCTFClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    def _absolute_url(self, path: str) -> str:
        return urljoin(f"{self._base_url}/", path)

    async def _fetch_text(self, path: str, params: dict[str, str] | None = None) -> str:
        url = f"{self._base_url}{path}"
        async with self._session.get(url, params=params) as response:
            if response.status != 200:
                text = await response.text()
                raise APIClientError(f"K-CTF request failed with {response.status}: {text[:200]}")
            return await response.text()

    async def _fetch_json(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        async with self._session.get(url, params=params) as response:
            if response.status != 200:
                text = await response.text()
                raise APIClientError(f"K-CTF request failed with {response.status}: {text[:200]}")
            payload = await response.json()

        if not isinstance(payload, dict):
            raise APIClientError("K-CTF API returned an unexpected response format.")
        return payload

    async def fetch_contest_details(self, contest: KCTFContest) -> KCTFContest:
        html = await self._fetch_text(f"/contests/{contest.id}")
        soup = BeautifulSoup(html, "html.parser")

        start = contest.start
        finish = contest.finish
        location = contest.location

        schedule_heading = None
        for heading in soup.find_all(["h2", "h3"]):
            if _normalize_text(heading.get_text(" ", strip=True)) == "일정":
                schedule_heading = heading
                break

        schedule_container = None
        if schedule_heading is not None:
            schedule_container = schedule_heading.find_parent("div", class_=lambda value: isinstance(value, str) and "bg-white" in value)

        if schedule_container is not None:
            for block in schedule_container.select("div.border-l-4"):
                label_node = block.select_one("h3")
                if label_node is None:
                    continue
                label = _normalize_text(label_node.get_text(" ", strip=True))
                lines = [
                    _normalize_text(node.get_text(" ", strip=True))
                    for node in block.select("p.text-sm")
                    if _normalize_text(node.get_text(" ", strip=True))
                ]
                if not lines:
                    continue

                parsed_range = _parse_kctf_range(lines[0])
                if label in {"예선 대회", "대회"} and parsed_range is not None:
                    start, finish = parsed_range
                    if len(lines) > 1 and lines[1] not in {"온라인", "오프라인", "온/오프라인"}:
                        location = lines[1]

        return KCTFContest(
            id=contest.id,
            title=contest.title,
            detail_url=contest.detail_url,
            organizer=contest.organizer,
            contest_status=contest.contest_status,
            registration_status=contest.registration_status,
            registration_period=contest.registration_period,
            contest_period=contest.contest_period,
            finals_period=contest.finals_period,
            mode=contest.mode,
            poster_url=contest.poster_url,
            start=start,
            finish=finish,
            location=location,
        )

    def _parse_contest_card(self, card: Any) -> KCTFContest | None:
        onclick = card.get("onclick", "")
        match = re.search(r"/contests/([A-Za-z0-9]+)", onclick)
        title_node = card.select_one("h3")
        if match is None or title_node is None:
            return None

        contest_id = match.group(1)
        organizer = None
        organizer_node = card.select_one("p.text-sm.text-gray-600")
        if organizer_node is not None:
            organizer_text = _normalize_text(organizer_node.get_text(" ", strip=True))
            if ":" in organizer_text:
                organizer = organizer_text.split(":", 1)[1].strip()
            elif organizer_text:
                organizer = organizer_text

        badges = [
            _normalize_text(node.get_text(" ", strip=True))
            for node in card.select("div.flex.flex-col.gap-1.flex-shrink-0 > span")
        ]
        info_rows = [
            _normalize_text(node.get_text(" ", strip=True))
            for node in card.select("div.flex.items-center.text-sm")
        ]
        poster_node = card.select_one("img[src]")
        poster_url = None
        if poster_node is not None and poster_node.get("src"):
            poster_url = self._absolute_url(str(poster_node["src"]))

        registration_period = None
        contest_period = None
        finals_period = None
        mode = None
        for info_row in info_rows:
            if info_row.startswith("신청:"):
                registration_period = info_row
            elif info_row.startswith("대회:"):
                contest_period = info_row
            elif info_row.startswith("본선:"):
                finals_period = info_row
            else:
                mode = info_row

        return KCTFContest(
            id=contest_id,
            title=_normalize_text(title_node.get_text(" ", strip=True)),
            detail_url=self._absolute_url(f"/contests/{contest_id}"),
            organizer=organizer,
            contest_status=badges[0] if badges else None,
            registration_status=badges[1] if len(badges) > 1 else None,
            registration_period=registration_period,
            contest_period=contest_period,
            finals_period=finals_period,
            mode=mode,
            poster_url=poster_url,
        )

    async def list_contests(self, status: str = "upcoming", limit: int | None = None) -> list[KCTFContest]:
        params: dict[str, str] = {}
        if status:
            params["status"] = status
        if status == "upcoming":
            params["sort"] = "date_asc"

        html = await self._fetch_text("/contests", params=params)
        soup = BeautifulSoup(html, "html.parser")

        contests: list[KCTFContest] = []
        for card in soup.select("div[onclick^=\"location.href='/contests/\"]"):
            contest = self._parse_contest_card(card)
            if contest is not None:
                contests.append(contest)
        return contests if limit is None else contests[:limit]

    async def search_contests(self, keyword: str, limit: int | None = None) -> list[KCTFContest]:
        contests = await self.list_contests(status="all", limit=None)
        keyword_folded = keyword.casefold()
        filtered = [contest for contest in contests if keyword_folded in contest.title.casefold()]
        return filtered if limit is None else filtered[:limit]

    async def recent_updates(self, limit: int | None = None) -> list[KCTFUpdateLog]:
        updates: list[KCTFUpdateLog] = []
        page_size = 100 if limit is None else max(limit, 10)
        offset = 0

        while True:
            payload = await self._fetch_json(
                "/api/contest-update-logs",
                params={"limit": str(page_size), "offset": str(offset)},
            )
            data = payload.get("logs", [])
            if not isinstance(data, list):
                raise APIClientError("K-CTF update log response is not a list.")

            for item in data:
                try:
                    contest_id = str(item["contest_id"])
                    updates.append(
                        KCTFUpdateLog(
                            id=str(item["_id"]),
                            contest_id=contest_id,
                            contest_name=str(item["contest_name"]),
                            change_type_label=str(item.get("change_type_label", item.get("change_type", "update"))),
                            change_details=_normalize_text(str(item.get("change_details", ""))),
                            created_at_kst=str(item.get("created_at_kst", "")),
                            detail_url=self._absolute_url(f"/contests/{contest_id}"),
                        )
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise APIClientError("Failed to parse K-CTF update log response.") from exc

                if limit is not None and len(updates) >= limit:
                    return updates[:limit]

            total_count = payload.get("total_count")
            if not data:
                break
            if isinstance(total_count, int) and offset + len(data) >= total_count:
                break
            if len(data) < page_size:
                break
            offset += len(data)

        return updates

    async def latest_announcement(self) -> KCTFAnnouncement:
        payload = await self._fetch_json("/api/announcements/latest")
        return KCTFAnnouncement(
            has_announcement=bool(payload.get("has_announcement", False)),
            latest_date=str(payload.get("latest_date")) if payload.get("latest_date") else None,
            title=str(payload.get("title")) if payload.get("title") else None,
            url=self._absolute_url("/announcements"),
        )
