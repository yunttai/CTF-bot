from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class CTFEvent:
    id: int
    title: str
    start: datetime
    finish: datetime
    ctftime_url: str
    format: str
    weight: float
    participants: int | None
    onsite: bool
    location: str
    organizers: tuple[str, ...]
    logo_url: str | None

    @property
    def is_ongoing(self) -> bool:
        now = datetime.now(timezone.utc)
        return self.start <= now < self.finish


@dataclass(frozen=True)
class KCTFContest:
    id: str
    title: str
    detail_url: str
    organizer: str | None
    contest_status: str | None
    registration_status: str | None
    registration_period: str | None
    contest_period: str | None
    finals_period: str | None
    mode: str | None
    poster_url: str | None
    start: datetime | None = None
    finish: datetime | None = None
    location: str | None = None


@dataclass(frozen=True)
class KCTFUpdateLog:
    id: str
    contest_id: str
    contest_name: str
    change_type_label: str
    change_details: str
    created_at_kst: str
    detail_url: str


@dataclass(frozen=True)
class KCTFAnnouncement:
    has_announcement: bool
    latest_date: str | None
    title: str | None
    url: str


@dataclass(frozen=True)
class StoredContest:
    contest_key: str
    source: str
    source_label: str
    source_id: str
    title: str
    normalized_title: str
    status: str
    detail_url: str
    organizer: str | None
    start: datetime | None
    finish: datetime | None
    format: str | None
    weight: float | None
    participants: int | None
    onsite: bool | None
    location: str | None
    image_url: str | None
    registration_period: str | None
    contest_period: str | None
    finals_period: str | None
    mode: str | None
    scraped_at: datetime
