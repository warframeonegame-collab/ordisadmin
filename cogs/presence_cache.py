import discord
from discord.ext import commands
import logging
from datetime import datetime

from utils.database import Database


class PresenceCache(commands.Cog):
    """Кэширует presence данные участников в PostgreSQL для отображения на сайте.

    Оптимизация памяти:
    - Локального зеркала кэша в памяти больше НЕТ — сайт читает кэш напрямую
      из PostgreSQL, а дублирование только тратило RAM.
    - Запись в БД происходит только при реальном изменении статуса/ролей/ника
      (presence-события приходят постоянно, а не только при смене статуса).
    - Синхронизация при старте выполняется ОДНИМ пакетным запросом вместо
      INSERT на каждого участника.
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    def _save_member(self, member):
        """Сохраняет запись участника в PostgreSQL."""
        try:
            self.db.upsert_presence(
                member.id,
                str(member.status),
                datetime.utcnow().isoformat(),
                [str(r.id) for r in member.roles],
                member.display_name,
            )
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка сохранения кэша: {e}")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        """Обновляет кэш только при изменении того, что фактически хранится в кэше."""
        if after.bot:
            return

        # Дебаунс: наличие события ещё не значит, что изменился статус/роли/ник
        # (например, смена активности или вида на Twitch не влияет на кэш)
        if (before.status == after.status
                and [r.id for r in before.roles] == [r.id for r in after.roles]
                and before.display_name == after.display_name):
            return

        self._save_member(after)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Обновляет кэш при изменении ролей или ника."""
        if after.bot:
            return

        if ([r.id for r in before.roles] == [r.id for r in after.roles]
                and before.display_name == after.display_name):
            return

        self._save_member(after)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Добавляет участника в кэш при входе"""
        if member.bot:
            return

        self._save_member(member)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Удаляет участника из кэша при выходе"""
        try:
            self.db.delete_presence(member.id)
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка удаления записи: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """При запуске синхронизируем кэш всех участников ОДНИМ пакетным запросом."""
        try:
            rows = []
            for guild in self.bot.guilds:
                for member in guild.members:
                    if member.bot:
                        continue
                    rows.append((
                        member.id,
                        str(member.status),
                        datetime.utcnow().isoformat(),
                        [str(r.id) for r in member.roles],
                        member.display_name,
                    ))
            self.db.upsert_presence_many(rows)
            logging.info(f"[PresenceCache] Кэш синхронизирован: {len(rows)} участников (одним пакетом)")
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка синхронизации кэша: {e}")


async def setup(bot):
    await bot.add_cog(PresenceCache(bot))
