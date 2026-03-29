from __future__ import annotations

from datetime import datetime, timezone
import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from ctf_bot.api_clients import APIClientError, KCTFClient
from ctf_bot.config import Settings
from ctf_bot.formatters import (
    build_auto_update_embed,
    build_kctf_announcement_embed,
    build_kctf_contest_embeds,
    build_kctf_updates_embeds,
    build_stored_contest_embeds,
)
from ctf_bot.storage import ContestRepository, StorageError


AUTO_UPDATE_EMBED_TITLE = "CTF 자동 업데이트"


class CTFCog(commands.Cog):
    ctf = app_commands.Group(name="ctf", description="저장된 CTF 스냅샷을 조회합니다.")
    kctf = app_commands.Group(name="kctf", description="K-CTF 정보를 조회합니다.")

    def __init__(self, bot: "CTFBot") -> None:
        self.bot = bot

    def _normalize_limit(self, limit: int | None) -> int | None:
        if limit is None:
            return None
        if limit < 1:
            raise ValueError("limit은 1 이상의 정수여야 합니다.")
        return limit

    async def _send_embed_list(self, interaction: discord.Interaction, embeds: list[discord.Embed]) -> None:
        if not embeds:
            embeds = [discord.Embed(title="결과 없음", description="표시할 항목이 없습니다.")]

        first_batch = embeds[:10]
        remaining_batches = [embeds[index : index + 10] for index in range(10, len(embeds), 10)]

        if interaction.response.is_done():
            await interaction.followup.send(embeds=first_batch)
        else:
            await interaction.response.send_message(embeds=first_batch)

        for batch in remaining_batches:
            await interaction.followup.send(embeds=batch)

    async def _send_error(self, interaction: discord.Interaction, message: str) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @ctf.command(name="upcoming", description="DB에 저장된 다가오는 CTF를 조회합니다.")
    @app_commands.describe(limit="가져올 개수. 비워두면 가능한 범위 내 전체 조회")
    async def ctf_upcoming(self, interaction: discord.Interaction, limit: int | None = None) -> None:
        await interaction.response.defer(thinking=True)
        try:
            contests = self.bot.repository.list_contests(status="upcoming", limit=self._normalize_limit(limit))
        except ValueError as exc:
            await self._send_error(interaction, str(exc))
            return
        except StorageError as exc:
            await self._send_error(interaction, f"CTF DB 조회 실패: {exc}")
            return

        await self._send_embed_list(interaction, build_stored_contest_embeds("다가오는 CTF", contests))

    @ctf.command(name="ongoing", description="DB에 저장된 진행 중인 CTF를 조회합니다.")
    @app_commands.describe(limit="가져올 개수. 비워두면 가능한 범위 내 전체 조회")
    async def ctf_ongoing(self, interaction: discord.Interaction, limit: int | None = None) -> None:
        await interaction.response.defer(thinking=True)
        try:
            contests = self.bot.repository.list_contests(status="ongoing", limit=self._normalize_limit(limit))
        except ValueError as exc:
            await self._send_error(interaction, str(exc))
            return
        except StorageError as exc:
            await self._send_error(interaction, f"CTF DB 조회 실패: {exc}")
            return

        await self._send_embed_list(interaction, build_stored_contest_embeds("진행 중인 CTF", contests))

    @ctf.command(name="search", description="DB에서 이름으로 CTF를 검색합니다.")
    @app_commands.describe(keyword="검색어", limit="가져올 개수. 비워두면 가능한 범위 내 전체 조회")
    async def ctf_search(
        self,
        interaction: discord.Interaction,
        keyword: str,
        limit: int | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            contests = self.bot.repository.list_contests(
                search=keyword,
                limit=self._normalize_limit(limit),
            )
        except ValueError as exc:
            await self._send_error(interaction, str(exc))
            return
        except StorageError as exc:
            await self._send_error(interaction, f"CTF DB 조회 실패: {exc}")
            return

        await self._send_embed_list(interaction, build_stored_contest_embeds(f"검색 결과: {keyword}", contests))

    @kctf.command(name="contests", description="K-CTF 대회 목록을 조회합니다.")
    @app_commands.describe(limit="가져올 개수. 비워두면 가능한 범위 내 전체 조회", status="대회 상태")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="upcoming", value="upcoming"),
            app_commands.Choice(name="ongoing", value="ongoing"),
            app_commands.Choice(name="registering", value="registering"),
            app_commands.Choice(name="ended", value="ended"),
            app_commands.Choice(name="all", value="all"),
        ]
    )
    async def kctf_contests(
        self,
        interaction: discord.Interaction,
        limit: int | None = None,
        status: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        selected_status = status.value if status else "upcoming"

        try:
            contests = await self.bot.kctf.list_contests(status=selected_status, limit=self._normalize_limit(limit))
        except ValueError as exc:
            await self._send_error(interaction, str(exc))
            return
        except APIClientError as exc:
            await self._send_error(interaction, f"K-CTF 조회 실패: {exc}")
            return

        await self._send_embed_list(
            interaction,
            build_kctf_contest_embeds(f"K-CTF 대회 목록 ({selected_status})", contests),
        )

    @kctf.command(name="search", description="K-CTF 대회를 검색합니다.")
    @app_commands.describe(keyword="검색어", limit="가져올 개수. 비워두면 가능한 범위 내 전체 조회")
    async def kctf_search(
        self,
        interaction: discord.Interaction,
        keyword: str,
        limit: int | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            contests = await self.bot.kctf.search_contests(keyword=keyword, limit=self._normalize_limit(limit))
        except ValueError as exc:
            await self._send_error(interaction, str(exc))
            return
        except APIClientError as exc:
            await self._send_error(interaction, f"K-CTF 조회 실패: {exc}")
            return

        await self._send_embed_list(
            interaction,
            build_kctf_contest_embeds(f"K-CTF 검색 결과: {keyword}", contests),
        )

    @kctf.command(name="updates", description="K-CTF 최근 업데이트 로그를 조회합니다.")
    @app_commands.describe(limit="가져올 개수. 비워두면 가능한 범위 내 전체 조회")
    async def kctf_updates(
        self,
        interaction: discord.Interaction,
        limit: int | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            updates = await self.bot.kctf.recent_updates(limit=self._normalize_limit(limit))
        except ValueError as exc:
            await self._send_error(interaction, str(exc))
            return
        except APIClientError as exc:
            await self._send_error(interaction, f"K-CTF 조회 실패: {exc}")
            return

        await self._send_embed_list(interaction, build_kctf_updates_embeds(updates))

    @kctf.command(name="announcement", description="K-CTF 최신 공지를 조회합니다.")
    async def kctf_announcement(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            announcement = await self.bot.kctf.latest_announcement()
        except APIClientError as exc:
            await self._send_error(interaction, f"K-CTF 조회 실패: {exc}")
            return

        await interaction.followup.send(embed=build_kctf_announcement_embed(announcement))


class CTFBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.session: aiohttp.ClientSession | None = None
        self.kctf: KCTFClient
        self.repository = ContestRepository(settings.ctf_db_path)
        self._initial_auto_update_published = False

    async def setup_hook(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self.settings.http_timeout_seconds)
        self.session = aiohttp.ClientSession(timeout=timeout)
        self.kctf = KCTFClient(
            session=self.session,
            base_url=self.settings.kctf_base_url,
        )
        self.repository.initialize()

        await self.add_cog(CTFCog(self))

        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            logging.info("Synced %s command(s) to guild %s", len(synced), self.settings.discord_guild_id)
        else:
            synced = await self.tree.sync()
            logging.info("Synced %s global command(s)", len(synced))

        if self.settings.auto_update_channel_id and not self.auto_update_loop.is_running():
            self.auto_update_loop.start()

    async def on_ready(self) -> None:
        if self.user is not None:
            logging.info("Logged in as %s (%s)", self.user, self.user.id)
        if self.settings.auto_update_channel_id and not self._initial_auto_update_published:
            self._initial_auto_update_published = True
            await self.publish_auto_update()

    async def close(self) -> None:
        if self.auto_update_loop.is_running():
            self.auto_update_loop.cancel()
        if self.session is not None:
            await self.session.close()
        await super().close()

    async def _resolve_auto_update_channel(self) -> discord.TextChannel | discord.Thread | None:
        channel_id = self.settings.auto_update_channel_id
        if channel_id is None:
            return None

        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.DiscordException:
                logging.exception("Failed to fetch auto update channel %s", channel_id)
                return None

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel

        logging.error("AUTO_UPDATE_CHANNEL_ID %s is not a text channel/thread", channel_id)
        return None

    async def _find_auto_update_message(
        self, channel: discord.TextChannel | discord.Thread
    ) -> discord.Message | None:
        if self.user is None:
            return None

        async for message in channel.history(limit=50):
            if message.author.id != self.user.id:
                continue
            if message.embeds and message.embeds[0].title == AUTO_UPDATE_EMBED_TITLE:
                return message
        return None

    async def publish_auto_update(self) -> None:
        channel = await self._resolve_auto_update_channel()
        if channel is None:
            return

        warnings: list[str] = []
        try:
            ongoing_contests = self.repository.list_contests(status="ongoing")
            upcoming_contests = self.repository.list_contests(status="upcoming")
            metadata = self.repository.get_metadata()
            if "last_refreshed_at" not in metadata:
                warnings.append("DB 갱신 시각 메타데이터가 없습니다.")
        except StorageError as exc:
            logging.warning("Failed to read contest DB for auto update: %s", exc)
            ongoing_contests = []
            upcoming_contests = []
            warnings.append(f"CTF DB를 읽지 못했습니다: {exc}")

        embed = build_auto_update_embed(
            ongoing_contests=ongoing_contests,
            upcoming_contests=upcoming_contests,
            generated_at=datetime.now(timezone.utc),
            warnings=warnings,
        )

        message = await self._find_auto_update_message(channel)
        if message is None:
            await channel.send(embed=embed)
            logging.info("Created auto update message in channel %s", channel.id)
            return

        await message.edit(embed=embed)
        logging.info("Updated auto update message in channel %s", channel.id)

    @tasks.loop(hours=1)
    async def auto_update_loop(self) -> None:
        try:
            await self.publish_auto_update()
        except Exception:
            logging.exception("Hourly auto update failed")

    @auto_update_loop.before_loop
    async def before_auto_update_loop(self) -> None:
        await self.wait_until_ready()


def main() -> None:
    load_dotenv()
    settings = Settings.from_env()
    discord.utils.setup_logging()
    bot = CTFBot(settings)
    bot.run(settings.discord_token)
