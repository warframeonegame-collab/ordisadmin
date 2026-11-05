import discord
import discord.app_commands as app_commands
from discord.ext import commands, tasks
import logging
import config
from utils.database import Database
from utils import cards


class LeaderboardSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.update_leaderboard.start()

    async def _build_leaderboard_payload(self, guild, top_users):
        """Собирает embed топ-10 + PNG-карточку (attachments).

        Возвращает (embed, file|None). file нужно передать в send(files=[...]).
        """
        entries = []
        for row in top_users:
            user_id = int(row['user_id'])
            member = guild.get_member(user_id)
            if member:
                name = member.display_name
                avatar_url = member.display_avatar.with_size(128).url
            elif row['nickname']:
                name = row['nickname']
                avatar_url = None
            else:
                name = "Пользователь не найден"
                avatar_url = None
            entries.append({
                'user_id': str(user_id),
                'nickname': name,
                'level': row['level'],
                'avatar_url': avatar_url,
            })

        embed = discord.Embed(
            title="Таблица лидеров Warframe",
            description="Топ-10 самых активных участников",
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Обновлено")

        file = None
        try:
            avatars = await cards.fetch_avatars(entries)
            card_path = cards.build_leaderboard_card(entries, avatars, config.LEADERBOARD_CARD_PATH)
            if card_path:
                file = discord.File(card_path, filename="leaderboard.png")
                embed.set_image(url="attachment://leaderboard.png")
        except Exception as e:
            logging.warning(f"[Leaderboard] Карточка не собралась: {e}")

        return embed, file

    @commands.hybrid_command(name="updatetable", description="Обновить таблицу лидеров в канале")
    @commands.has_permissions(administrator=True)
    async def update_leaderboard_manual(self, ctx):
        leaderboard_channel = self.bot.get_channel(config.LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            await ctx.send("Канал таблицы лидеров не найден!", ephemeral=True)
            return

        try:
            if not isinstance(ctx.interaction, discord.Interaction):
                try:
                    await ctx.message.delete()
                except discord.NotFound:
                    pass  # Сообщение уже удалено, игнорируем

            # Топ-10 прямо из PostgreSQL (не грузим всю таблицу в память)
            top_users = self.db.get_top_users(10)
            embed, file = await self._build_leaderboard_payload(ctx.guild, top_users)

            # Очищаем канал и отправляем новое сообщение
            async with leaderboard_channel.typing():
                try:
                    await leaderboard_channel.purge()
                except discord.NotFound:
                    pass  # Канал уже пуст или сообщений нет, игнорируем
                if file is not None:
                    await leaderboard_channel.send(embed=embed, file=file)
                else:
                    await leaderboard_channel.send(embed=embed)

            await ctx.send("Таблица лидеров успешно обновлена!", ephemeral=True)

        except Exception as e:
            error_msg = str(e)
            # Не показываем ошибки удаления сообщений пользователю
            if "10008" in error_msg or "Unknown Message" in error_msg:
                return
            await ctx.send(f"Произошла ошибка при обновлении таблицы: {error_msg}", ephemeral=True)
            logging.error(f"[Leaderboard] Ошибка ручного обновления таблицы: {error_msg}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Обнуляем профиль при выходе пользователя (удаляем запись из PostgreSQL)
        self.db.delete_user(str(member.id))

    # Автоматическое обновление
    @tasks.loop(minutes=60)  # Обновление каждые 60 минут
    async def update_leaderboard(self):
        leaderboard_channel = self.bot.get_channel(config.LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            return

        try:
            # Топ-10 прямо из PostgreSQL (не грузим всю таблицу в память)
            top_users = self.db.get_top_users(10)
            embed, file = await self._build_leaderboard_payload(leaderboard_channel.guild, top_users)

            async with leaderboard_channel.typing():
                await leaderboard_channel.purge()
                if file is not None:
                    await leaderboard_channel.send(embed=embed, file=file)
                else:
                    await leaderboard_channel.send(embed=embed)

        except Exception as e:
            logging.error(f"[Leaderboard] Ошибка автообновления таблицы лидеров: {e}")

    @update_leaderboard.before_loop
    async def before_update_leaderboard(self):
        await self.bot.wait_until_ready()
        leaderboard_channel = self.bot.get_channel(config.LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            logging.error("[Leaderboard] Канал таблицы лидеров не найден при инициализации!")
            self.update_leaderboard.cancel()

async def setup(bot):
    await bot.add_cog(LeaderboardSystem(bot))
