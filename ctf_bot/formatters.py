from __future__ import annotations

from datetime import datetime

import discord

from ctf_bot.models import CTFEvent, KCTFAnnouncement, KCTFContest, KCTFUpdateLog, StoredContest


def _discord_timestamp(value: datetime, style: str) -> str:
    return f"<t:{int(value.timestamp())}:{style}>"


def _truncate(text: str, limit: int = 80) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _join_lines(lines: list[str], empty_message: str) -> str:
    return "\n".join(lines) if lines else empty_message


def _stored_status_label(status: str) -> str:
    labels = {
        "upcoming": "예정",
        "ongoing": "진행 중",
    }
    return labels.get(status, status)


def build_empty_embed(title: str, description: str) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=discord.Color.blurple())
    return embed


def build_stored_contest_embeds(title: str, contests: list[StoredContest]) -> list[discord.Embed]:
    if not contests:
        return [build_empty_embed(title, "표시할 CTF가 없습니다.")]

    embeds: list[discord.Embed] = []
    for contest in contests:
        description_lines: list[str] = [
            f"출처: {contest.source_label}",
            f"📌 상태: {_stored_status_label(contest.status)}",
        ]
        if contest.organizer:
            description_lines.append(f"🏛️ 주최: {contest.organizer}")
        if contest.start:
            description_lines.append(
                f"🕒 시작: {_discord_timestamp(contest.start, 'f')} ({_discord_timestamp(contest.start, 'R')})"
            )
        if contest.finish:
            description_lines.append(f"🕒 종료: {_discord_timestamp(contest.finish, 'f')}")
        if contest.contest_period:
            description_lines.append(f"🗓️ {contest.contest_period}")
        if contest.registration_period:
            description_lines.append(f"📝 {contest.registration_period}")
        if contest.finals_period:
            description_lines.append(f"🏁 {contest.finals_period}")
        if contest.format:
            description_lines.append(f"🧩 형식: {contest.format}")
        if contest.weight is not None:
            description_lines.append(f"🏷️ 가중치: {contest.weight:.2f}")
        if contest.location:
            description_lines.append(f"📍 위치: {contest.location}")
        if contest.mode:
            description_lines.append(f"📌 형태: {contest.mode}")
        if contest.participants is not None:
            description_lines.append(f"👥 참가팀: {contest.participants}")
        if contest.onsite is not None:
            description_lines.append(f"🖥️ 온사이트: {'예' if contest.onsite else '아니오'}")
        description_lines.append(f"🔗 [자세히 보기]({contest.detail_url})")

        color = discord.Color.blurple() if contest.source == "ctftime" else discord.Color.green()
        embed = discord.Embed(
            title=contest.title,
            url=contest.detail_url,
            description="\n".join(description_lines),
            color=color,
        )
        if contest.image_url:
            embed.set_thumbnail(url=contest.image_url)
        embeds.append(embed)

    return embeds


def build_ctftime_event_embeds(title: str, events: list[CTFEvent]) -> list[discord.Embed]:
    if not events:
        return [build_empty_embed(title, "표시할 CTF가 없습니다.")]

    embeds: list[discord.Embed] = []
    for event in events:
        description_lines = [
            f"🕒 시작: {_discord_timestamp(event.start, 'f')} ({_discord_timestamp(event.start, 'R')})",
            f"🕒 종료: {_discord_timestamp(event.finish, 'f')}",
            f"🧩 형식: {event.format}",
            f"🏷️ 가중치: {event.weight:.2f}",
        ]

        if event.organizers:
            description_lines.append(f"🏛️ 주최: {', '.join(event.organizers)}")
        if event.location:
            description_lines.append(f"📍 위치: {event.location}")
        if event.participants is not None:
            description_lines.append(f"👥 참가팀: {event.participants}")
        description_lines.append(f"🖥️ 온사이트: {'예' if event.onsite else '아니오'}")
        description_lines.append(f"🔗 [자세히 보기]({event.ctftime_url})")
        description_lines.append("출처: CTFtime")

        embed = discord.Embed(
            title=event.title,
            url=event.ctftime_url,
            description="\n".join(description_lines),
            color=discord.Color.blurple(),
        )
        if event.logo_url:
            embed.set_thumbnail(url=event.logo_url)
        embeds.append(embed)

    return embeds


def build_kctf_contest_embeds(title: str, contests: list[KCTFContest]) -> list[discord.Embed]:
    if not contests:
        return [build_empty_embed(title, "표시할 K-CTF 대회가 없습니다.")]

    embeds: list[discord.Embed] = []
    for contest in contests:
        description_lines: list[str] = []
        if contest.organizer:
            description_lines.append(f"🏛️ 주최: {contest.organizer}")
        if contest.contest_status:
            description_lines.append(f"📌 상태: {contest.contest_status}")
        if contest.registration_status:
            description_lines.append(f"📝 신청 상태: {contest.registration_status}")
        if contest.registration_period:
            description_lines.append(f"🗓️ {contest.registration_period}")
        if contest.contest_period:
            description_lines.append(f"🗓️ {contest.contest_period}")
        if contest.finals_period:
            description_lines.append(f"🏁 {contest.finals_period}")
        if contest.mode:
            description_lines.append(f"📍 형태: {contest.mode}")
        description_lines.append(f"🔗 [자세히 보기]({contest.detail_url})")
        description_lines.append("출처: K-CTF")

        embed = discord.Embed(
            title=contest.title,
            url=contest.detail_url,
            description="\n".join(description_lines),
            color=discord.Color.green(),
        )
        if contest.poster_url:
            embed.set_thumbnail(url=contest.poster_url)
        embeds.append(embed)

    return embeds


def build_kctf_updates_embeds(updates: list[KCTFUpdateLog]) -> list[discord.Embed]:
    if not updates:
        return [discord.Embed(title="K-CTF 업데이트 로그", description="표시할 업데이트가 없습니다.", color=discord.Color.orange())]

    embeds: list[discord.Embed] = []
    embed = discord.Embed(title="K-CTF 업데이트 로그", color=discord.Color.orange())
    fields_in_current_embed = 0
    for update in updates:
        detail = update.change_details
        if len(detail) > 220:
            detail = f"{detail[:217]}..."

        value_lines = [
            f"유형: {update.change_type_label}",
            f"시각(KST): {update.created_at_kst}",
            detail,
            f"[대회 페이지]({update.detail_url})",
        ]
        embed.add_field(name=update.contest_name, value="\n".join(value_lines), inline=False)
        fields_in_current_embed += 1
        if fields_in_current_embed == 25:
            embeds.append(embed)
            embed = discord.Embed(title="K-CTF 업데이트 로그", color=discord.Color.orange())
            fields_in_current_embed = 0

    if fields_in_current_embed or not embeds:
        embeds.append(embed)
    return embeds


def build_kctf_announcement_embed(announcement: KCTFAnnouncement) -> discord.Embed:
    embed = discord.Embed(title="K-CTF 최신 공지", color=discord.Color.gold())
    if not announcement.has_announcement:
        embed.description = f"표시할 공지가 없습니다.\n[공지사항 페이지]({announcement.url})"
        return embed

    lines = []
    if announcement.latest_date:
        lines.append(f"날짜: {announcement.latest_date}")
    if announcement.title:
        lines.append(f"제목: {announcement.title}")
    lines.append(f"[공지사항 페이지]({announcement.url})")
    embed.description = "\n".join(lines)
    return embed


def build_auto_update_embed(
    ongoing_contests: list[StoredContest],
    upcoming_contests: list[StoredContest],
    generated_at: datetime,
    warnings: list[str],
) -> discord.Embed:
    embed = discord.Embed(
        title="CTF 자동 업데이트",
        description="1시간마다 자동으로 갱신됩니다. DB 스냅샷 기준으로 표시됩니다.",
        color=discord.Color.teal(),
        timestamp=generated_at,
    )

    ongoing_lines = [
        f"• [{_truncate(contest.title)}]({contest.detail_url}) | {contest.source_label} | "
        f"{_discord_timestamp(contest.finish, 'R') if contest.finish else (contest.contest_period or contest.mode or '일정 정보 없음')}"
        for contest in ongoing_contests
    ]

    upcoming_lines = [
        f"• [{_truncate(contest.title)}]({contest.detail_url}) | {contest.source_label} | "
        f"{_discord_timestamp(contest.start, 'R') if contest.start else (contest.contest_period or contest.registration_period or contest.mode or '일정 정보 없음')}"
        for contest in upcoming_contests
    ]

    embed.add_field(
        name="진행 중인 CTF",
        value=_join_lines(ongoing_lines, "표시할 진행 중 대회가 없습니다."),
        inline=False,
    )
    embed.add_field(
        name="다가오는 CTF",
        value=_join_lines(upcoming_lines, "표시할 예정 대회가 없습니다."),
        inline=False,
    )

    if warnings:
        embed.add_field(name="참고", value="\n".join(f"• {warning}" for warning in warnings), inline=False)

    embed.set_footer(text="다음 자동 갱신은 약 1시간 뒤")
    return embed
