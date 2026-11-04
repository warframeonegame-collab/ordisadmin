import discord
from discord.ext import commands
import logging
from datetime import datetime

from utils.database import Database

class PresenceCache(commands.Cog):
    """Кэширует presence данные участников в PostgreSQL для отображения на сайте"""

    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        # Локальное зеркало таблицы presence_cache для быстрого чтения
        # {user_id: {'status': str, 'last_seen': str, 'roles': [str], 'nickname': str}}
        self.presence_cache = {}
        self._load_cache()

    def _load_cache(self):
        """Загружает кэш из PostgreSQL."""
        try:
            self.presence_cache = self.db.get_presence_cache()
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка загрузки кэша: {e}")
            self.presence_cache = {}

    def _save_entry(self, user_id, entry):
        """Сохраняет запись участника в PostgreSQL и локальное зеркало."""
        user_id = str(user_id)
        self.presence_cache[user_id] = entry
        try:
            self.db.upsert_presence(
                user_id,
                entry.get('status', 'offline'),
                entry.get('last_seen'),
                entry.get('roles', []),
                entry.get('nickname'),
            )
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка сохранения кэша: {e}")

    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        """Обновляет кэш при изменении presence"""
        if after.bot:
            return

        self._save_entry(after.id, {
            'status': str(after.status),  # online, idle, dnd, offline
            'last_seen': datetime.utcnow().isoformat(),
            'roles': [str(r.id) for r in after.roles],
            'nickname': after.display_name,
        })

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Обновляет кэш при изменении ролей"""
        if after.bot:
            return

        user_id = str(after.id)
        if user_id in self.presence_cache:
            entry = dict(self.presence_cache[user_id])
            entry['roles'] = [str(r.id) for r in after.roles]
            entry['nickname'] = after.display_name
            self._save_entry(user_id, entry)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Добавляет участника в кэш при входе"""
        if member.bot:
            return

        self._save_entry(member.id, {
            'status': str(member.status),
            'last_seen': datetime.utcnow().isoformat(),
            'roles': [str(r.id) for r in member.roles],
            'nickname': member.display_name,
        })

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Удаляет участника из кэша при выходе"""
        user_id = str(member.id)
        if user_id in self.presence_cache:
            del self.presence_cache[user_id]
            try:
                self.db.delete_presence(user_id)
            except Exception as e:
                logging.warning(f"[PresenceCache] Ошибка удаления записи: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        """При запуске заполняем кэш текущими данными"""
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                self._save_entry(member.id, {
                    'status': str(member.status),
                    'last_seen': datetime.utcnow().isoformat(),
                    'roles': [str(r.id) for r in member.roles],
                    'nickname': member.display_name,
                })
        logging.info(f"[PresenceCache] Кэш заполнен: {len(self.presence_cache)} участников")

    def get_online_members(self):
        """Возвращает список онлайн участников"""
        online = []
        for user_id, data in self.presence_cache.items():
            if data.get('status') in ('online', 'idle', 'dnd'):
                online.append(user_id)
        return online

    def get_senior_online(self, senior_role_ids):
        """Возвращает список онлайн старшего состава по ID ролей"""
        senior_online = []
        for user_id, data in self.presence_cache.items():
            if data.get('status') in ('online', 'idle', 'dnd'):
                roles = data.get('roles', [])
                if any(rid in senior_role_ids for rid in roles):
                    senior_online.append(user_id)
        return senior_online

    def get_total_online(self):
        """Возвращает количество онлайн участников"""
        return len(self.get_online_members())

async def setup(bot):
    await bot.add_cog(PresenceCache(bot))
