from __future__ import annotations

from dataclasses import dataclass
import os


def _read_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    return int(value)


def _read_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    return float(value)


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    auto_update_channel_id: int | None
    ctf_db_path: str
    ctftime_base_url: str
    ctftime_fetch_limit: int
    kctf_base_url: str
    http_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        discord_token = os.getenv("DISCORD_TOKEN", "").strip()
        if not discord_token:
            raise ValueError("DISCORD_TOKEN environment variable is required.")

        return cls(
            discord_token=discord_token,
            discord_guild_id=_read_int("DISCORD_GUILD_ID"),
            auto_update_channel_id=_read_int("AUTO_UPDATE_CHANNEL_ID"),
            ctf_db_path=os.getenv("CTF_DB_PATH", "data/ctf_snapshot.db").strip() or "data/ctf_snapshot.db",
            ctftime_base_url=os.getenv("CTFTIME_BASE_URL", "https://ctftime.org").strip().rstrip("/"),
            ctftime_fetch_limit=_read_int("CTFTIME_FETCH_LIMIT") or 100,
            kctf_base_url=os.getenv("KCTF_BASE_URL", "http://k-ctf.org").strip().rstrip("/"),
            http_timeout_seconds=_read_float("HTTP_TIMEOUT_SECONDS", 10.0),
        )
