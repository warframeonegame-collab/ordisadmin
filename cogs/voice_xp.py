import discord
from discord.ext import commands, tasks
from utils.database import Database
import config
import logging


class VoiceXP(commands.Cog):
    """Система начисления опыта за нахождение в голосовых каналах."""

    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.voice_xp_loop.start()

    def cog_unload(self):
        self.voice_xp_loop.cancel()

    @tasks.loop(seconds=config.VOICE_XP_INTERVAL)
    async def voice_xp_loop(self):
        """Каждые N секунд проверяет всех участников в голосовых каналах и начисляет XP."""
        for guild in self.bot.guilds:
            afk_channel = guild.afk_channel  # Может быть None

            for member in guild.members:
                # Проверяем, что участник в голосовом канале
                if not member.voice or not member.voice.channel:
                    continue

                voice = member.voice

                # Пропускаем, если пользователь в AFK-канале
                if afk_channel and voice.channel.id == afk_channel.id:
                    continue

                # Пропускаем, если пользователь не подключён (например, роутер)
                if not voice.self_stream and not voice.channel:
                    continue

                # Проверяем микрофон: пользователь НЕ должен быть заглушен
                # self_mute = True → пользователь сам себя замутил
                # mute = True → сервер замутил пользователя
                if voice.self_mute or voice.mute:
                    continue

                # Проверяем звук (deaf): пользователь НЕ должен быть глух
                # self_deaf = True → пользователь сам себя заглушил
                # deaf = True → сервер заглушил пользователя
                if voice.self_deaf or voice.deaf:
                    continue

                # Начисляем опыт
                try:
                    self.db.add_xp(member.id, config.XP_PER_VOICE)
                except Exception as e:
                    logging.error(f"[VoiceXP] Ошибка начисления XP пользователю {member.id}: {e}")

    @voice_xp_loop.before_loop
    async def before_voice_xp(self):
        """Ждём, пока бот полностью не запустится."""
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(VoiceXP(bot))