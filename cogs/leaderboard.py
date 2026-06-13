import discord
from discord.ext import commands, tasks
import config
from utils.database import Database

class LeaderboardSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.update_leaderboard.start()

    @commands.command(name="updatetable")
    @commands.has_permissions(administrator=True)
    async def update_leaderboard_manual(self, ctx):
        leaderboard_channel = self.bot.get_channel(config.LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            await ctx.send("Канал таблицы лидеров не найден!", ephemeral=True)
            return

        try:
            # Удаляем сообщение с обработкой ошибки 404 (уже удалено)
            try:
                await ctx.message.delete()
            except discord.NotFound:
                pass  # Сообщение уже удалено, игнорируем
            
            # Принудительно загружаем актуальные данные
            self.db.data = self.db.load_data()
            
            # Получаем отсортированный список пользователей
            users = sorted(
                self.db.data.items(), 
                key=lambda x: x[1]['level'], 
                reverse=True
            )
            
            embed = discord.Embed(
                title="Таблица лидеров Warframe",
                description="Топ-10 самых активных участников",
                color=discord.Color.gold()
            )
            
            for i, (user_id, data) in enumerate(users[:10], start=1):
                member = ctx.guild.get_member(int(user_id))
                if member:
                    embed.add_field(
                        name=f"{i}. {member.display_name}",
                        value=f"Уровень: {data['level']}",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"{i}. Пользователь не найден",
                        value=f"Уровень: {data['level']}",
                        inline=False
                    )
            
            # Очищаем канал и отправляем новое сообщение
            async with leaderboard_channel.typing():
                try:
                    await leaderboard_channel.purge()
                except discord.NotFound:
                    pass  # Канал уже пуст или сообщений нет, игнорируем
                await leaderboard_channel.send(embed=embed)
            
            await ctx.send("Таблица лидеров успешно обновлена!", ephemeral=True)
            
        except Exception as e:
            error_msg = str(e)
            # Не показываем ошибки удаления сообщений пользователю
            if "10008" in error_msg or "Unknown Message" in error_msg:
                return
            await ctx.send(f"Произошла ошибка при обновлении таблицы: {error_msg}", ephemeral=True)
            print(f"Ошибка при ручном обновлении таблицы: {error_msg}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Обнуляем профиль при выходе пользователя
        self.db.data.pop(str(member.id), None)
        self.db.save_data()

    # Автоматическое обновление
    @tasks.loop(minutes=60)  # Обновление каждые 60 минут
    async def update_leaderboard(self):
        leaderboard_channel = self.bot.get_channel(config.LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            return

        try:
            # Принудительно загружаем актуальные данные
            self.db.data = self.db.load_data()
            
            users = sorted(
                self.db.data.items(), 
                key=lambda x: x[1]['level'], 
                reverse=True
            )
            
            embed = discord.Embed(
                title="Таблица лидеров по активности",
                color=discord.Color.gold()
            )
            
            for i, (user_id, data) in enumerate(users[:10], start=1):
                member = leaderboard_channel.guild.get_member(int(user_id))
                if member:
                    embed.add_field(
                        name=f"{i}. {member.display_name}",
                        value=f"Уровень: {data['level']}",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name=f"{i}. Пользователь не найден",
                        value=f"Уровень: {data['level']}",
                        inline=False
                    )
            
            async with leaderboard_channel.typing():
                await leaderboard_channel.purge()
                await leaderboard_channel.send(embed=embed)

        except Exception as e:
            print(f"Ошибка при автоматическом обновлении таблицы лидеров: {e}")

    @update_leaderboard.before_loop
    async def before_update_leaderboard(self):
        await self.bot.wait_until_ready()
        leaderboard_channel = self.bot.get_channel(config.LEADERBOARD_CHANNEL_ID)
        if not leaderboard_channel:
            print("Канал таблицы лидеров не найден при инициализации!")
            self.update_leaderboard.cancel()

async def setup(bot):
    await bot.add_cog(LeaderboardSystem(bot))