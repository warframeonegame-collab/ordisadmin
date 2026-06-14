import discord
from discord.ext import commands, tasks
import json
import os
import logging
from datetime import datetime

class PresenceCache(commands.Cog):
    """Кэширует presence данные участников для отображения на сайте"""
    
    def __init__(self, bot):
        self.bot = bot
        self.cache_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'presence_cache.json')
        self.presence_cache = {}  # {user_id: {'status': str, 'last_seen': str, 'roles': [str]}}
        self._load_cache()
        self.save_cache_loop.start()
    
    def cog_unload(self):
        self.save_cache_loop.cancel()
    
    def _load_cache(self):
        """Загружает кэш из файла"""
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.presence_cache = json.load(f)
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка загрузки кэша: {e}")
            self.presence_cache = {}
    
    def _save_cache(self):
        """Сохраняет кэш в файл"""
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.presence_cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.warning(f"[PresenceCache] Ошибка сохранения кэша: {e}")
    
    @tasks.loop(minutes=5)
    async def save_cache_loop(self):
        """Периодически сохраняет кэш"""
        self._save_cache()
    
    @save_cache_loop.before_loop
    async def before_save(self):
        await self.bot.wait_until_ready()
    
    @commands.Cog.listener()
    async def on_presence_update(self, before, after):
        """Обновляет кэш при изменении presence"""
        if after.bot:
            return
        
        user_id = str(after.id)
        status = str(after.status)  # online, idle, dnd, offline
        
        self.presence_cache[user_id] = {
            'status': status,
            'last_seen': datetime.utcnow().isoformat(),
            'roles': [str(r.id) for r in after.roles],
            'nickname': after.display_name,
        }
    
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Обновляет кэш при изменении ролей"""
        if after.bot:
            return
        
        user_id = str(after.id)
        if user_id in self.presence_cache:
            self.presence_cache[user_id]['roles'] = [str(r.id) for r in after.roles]
            self.presence_cache[user_id]['nickname'] = after.display_name
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Добавляет участника в кэш при входе"""
        if member.bot:
            return
        
        user_id = str(member.id)
        self.presence_cache[user_id] = {
            'status': str(member.status),
            'last_seen': datetime.utcnow().isoformat(),
            'roles': [str(r.id) for r in member.roles],
            'nickname': member.display_name,
        }
    
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Удаляет участника из кэша при выходе"""
        user_id = str(member.id)
        if user_id in self.presence_cache:
            del self.presence_cache[user_id]
    
    @commands.Cog.listener()
    async def on_ready(self):
        """При запуске заполняем кэш текущими данными"""
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue
                user_id = str(member.id)
                self.presence_cache[user_id] = {
                    'status': str(member.status),
                    'last_seen': datetime.utcnow().isoformat(),
                    'roles': [str(r.id) for r in member.roles],
                    'nickname': member.display_name,
                }
        self._save_cache()
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