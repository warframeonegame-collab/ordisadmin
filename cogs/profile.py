import discord
from discord.ext import commands
import config
from utils.database import Database
from datetime import datetime
import random

class ProfileView(discord.ui.View):
    """View с динамическими кнопками для достижений и варнов."""

    def __init__(self, member: discord.Member, user_data: dict, profile_embed: discord.Embed,
                 achievements_embed: discord.Embed, warns_embed: discord.Embed, author: discord.Member):
        super().__init__(timeout=60)
        self.member = member
        self.user_data = user_data
        self.profile_embed = profile_embed
        self.achievements_embed = achievements_embed
        self.warns_embed = warns_embed
        self.author = author
        self.showing_achievements = False
        self.showing_warns = False

        # Динамически показываем кнопки
        achievements = user_data.get('achievements', {})
        has_achievements = any(achievements.values())
        warns = user_data.get('warns', [])
        has_warns = len(warns) > 0

        if has_achievements:
            self.achievements_button.label = "🏆 Достижения"
        else:
            self.achievements_button.label = "🏆 Достижения"
            self.achievements_button.disabled = True

        if has_warns:
            self.warns_button.label = "⚠️ Варны"
        else:
            self.warns_button.label = "⚠️ Варны"
            self.warns_button.disabled = True

    @discord.ui.button(label="🏆 Достижения", style=discord.ButtonStyle.primary, row=0)
    async def achievements_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Вы не можете управлять этим профилем.", ephemeral=True)
            return

        if self.showing_warns:
            self.showing_warns = False

        if self.showing_achievements:
            await interaction.response.edit_message(embed=self.profile_embed, view=self)
            button.label = "🏆 Достижения"
            self.showing_achievements = False
        else:
            await interaction.response.edit_message(embed=self.achievements_embed, view=self)
            button.label = "👤 Профиль"
            self.showing_achievements = True

    @discord.ui.button(label="⚠️ Варны", style=discord.ButtonStyle.secondary, row=0)
    async def warns_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Вы не можете управлять этим профилем.", ephemeral=True)
            return

        if self.showing_achievements:
            self.showing_achievements = False

        if self.showing_warns:
            await interaction.response.edit_message(embed=self.profile_embed, view=self)
            button.label = "⚠️ Варны"
            self.showing_warns = False
        else:
            await interaction.response.edit_message(embed=self.warns_embed, view=self)
            button.label = "👤 Профиль"
            self.showing_warns = True

    async def on_timeout(self):
        self.stop()


class ProfileSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.excluded_commands = ['profile', 'help', 'setprofile', 'setsubdivision', 'updatetable']
        self.forbidden_channels = [
            1257267587432058993,
            1501029076478201896,
            1498928154415468584,
            1494776417546666106,
            1494765342369517568
        ]
        self.bot_profile = {
            'nickname': '🤖 Ордис [ERROR_404]',
            'position': 'В процессе... [LOADING...]',
            'joined_at': datetime.now().strftime('%d.%m.%Y'),
            'xp': "∞ [OVERLOW_ERROR]",
            'level': 1,
            'description': (
                'Я ваш помощник и администратор сервера!\n'
                '⚠️ Система работает в режиме отладки...\n'
                '⚠️ Система работает в режиме отладки...\n'
                '🛠️ Процессы инициализации: 75%\n'
                '🔍 База данных: CHECKING...\n'
                '📊 Статистика: UPDATING...'
            ),
            'features': [
                'Моментальная реакция на команды [BUGGED]',
                'Бесконечный запас энергии [OVERLOAD]',
                'Абсолютная память [LOADING...]',
                'Непревзойденная точность [CALIBRATING]',
                'Секретный режим разработчика [UNLOCK WITH BOOST]',
                'Расширенная аналитика клана [UNLOCK WITH BOOST]',
                'Прогнозирование событий [UNLOCK WITH BOOST]',
                'Автоматическое исправление багов [UNLOCK WITH BOOST]'
            ]
        }

    # Метод, который будет выполняться перед каждой командой
    async def cog_before_invoke(self, ctx):
        """Проверяет, разрешена ли команда в данном канале."""
        if ctx.channel.id in self.forbidden_channels:
            raise commands.CommandError("Command not allowed in this channel")

    # --- Логика профиля (РАБОТАЕТ ВСЕГДА) ---

    @commands.command(name="profile")
    async def profile(self, ctx, member: discord.Member = None):
        if not member:
            member = ctx.author

        if member.id == self.bot.user.id:  # Проверка на профиль бота
            return await self.show_bot_profile(ctx)

        try:
            self.db.refresh(member.id)
            real_joined = member.joined_at.strftime('%d.%m.%Y') if member.joined_at else None
            user = self.db.get_user(member.id, joined_at=real_joined)

            if not user:
                await ctx.send("Пользователь не найден в базе данных")
                return

        except Exception as e:
            await ctx.send(f"Ошибка при получении данных профиля: {str(e)}")
            return

        # Определяем текущий Tier пользователя по ID роли
        user_tier = "Не назначен"
        for role_id, display_name in config.TIER_ROLES.items():
            if discord.utils.get(member.roles, id=role_id):
                user_tier = display_name
                break

        xp_into_level = user['xp']
        next_level_xp = config.LEVEL_MULTIPLIER * (user['level'] + 1) ** 2
        remaining_xp = next_level_xp - xp_into_level

        embed = discord.Embed(
            title=f"Профиль {member.display_name}",
            color=discord.Color.blue()
        )
        embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text=f"Запрошено {ctx.author.display_name}", icon_url=ctx.author.avatar.url)

        embed.add_field(name="📋 Никнейм", value=user['nickname'] or member.display_name, inline=False)
        embed.add_field(name="🥉 Тир", value=user_tier, inline=False)
        if user.get('position'):
            embed.add_field(name="🏷️ Должность", value=user['position'], inline=False)
        if user.get('subdivision'):
            embed.add_field(name="📁 Подразделение", value=user['subdivision'], inline=False)

        embed.add_field(
            name="📅 Дата вступления",
            value=f"{user['joined_at']}\n"
                  f"🏆 Уровень: {user['level']}",
            inline=False
        )

        embed.add_field(
            name="📊 До следующего уровня",
            value=f"Осталось {remaining_xp} XP",
            inline=False
        )
        await ctx.message.delete()

        # Создаём embed достижений
        achievements_cog = self.bot.get_cog("Achievements")
        achievements_embed = None
        if achievements_cog:
            achievements_embed = await achievements_cog.get_achievements_embed(member, ctx.author)

        # Создаём embed варнов
        warns_embed = self._build_warns_embed(member, ctx.author, user)

        view = ProfileView(member, user, embed, achievements_embed, warns_embed, ctx.author)

        await ctx.send(embed=embed, view=view, delete_after=60)

    def _build_warns_embed(self, member: discord.Member, author: discord.Member, user_data: dict) -> discord.Embed:
        """Создаёт embed с варнами пользователя."""
        warns = user_data.get('warns', [])

        desc_lines = []
        for i, warn in enumerate(warns, start=1):
            reason = warn.get('reason', 'Не указана')
            date = warn.get('date', 'Нет даты')
            mod_id = warn.get('moderator', None)
            mod_text = f"Модератор: <@{mod_id}>" if mod_id else ""
            desc_lines.append(f"**{i}. warn** | {date}\nПричина: {reason}\n{mod_text}")

        remaining = max(0, 3 - len(warns))
        if remaining > 0:
            desc_lines.append(f"\n⚠️ **До получения штрафной роли осталось {remaining} / 3**")
        else:
            desc_lines.append(f"\n⛔ **Штрафная роль выдана!**")

        if not desc_lines:
            desc_lines.append("Нет варнов.")

        emb = discord.Embed(
            title=f"⚠️ Варны {member.display_name}",
            description="\n\n".join(desc_lines),
            color=discord.Color.orange()
        )
        emb.set_thumbnail(url=member.avatar.url)
        emb.set_footer(text=f"Запрошено {author.display_name}", icon_url=author.avatar.url)
        return emb

    async def show_bot_profile(self, ctx):
        embed = discord.Embed(
            title=self.bot_profile['nickname'],
            description=self.bot_profile['description'],
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url)

        embed.add_field(name="🎯 Статус", value=self.bot_profile['position'], inline=False)
        embed.add_field(name="📅 Дата создания", value=self.bot_profile['joined_at'], inline=True)
        embed.add_field(name="🌟 Уровень", value=self.bot_profile['level'], inline=True)
        embed.add_field(name="⭐ Опыт", value=self.bot_profile['xp'], inline=True)
        embed.add_field(name="Возможности", value="\n".join(self.bot_profile['features']), inline=False)

        await ctx.message.delete()
        await ctx.send(embed=embed, delete_after=60)

    # --- Административные команды (РАБОТАЮТ ВСЕГДА) ---
    @commands.command(name="help")
    async def help_command(self, ctx):
        embed = discord.Embed(
            title="📣 Система помощи",
            description="Список доступных команд",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🔍 Основные команды",
            value=(
                "`.profile` - просмотр вашего профиля\n"
                "`.help` - показать это сообщение\n"
            ),
            inline=False
        )

        # Команды модерации видны только authorised roles
        is_mod = (discord.utils.get(ctx.author.roles, id=1493218079528976414) is not None or 
                  discord.utils.get(ctx.author.roles, id=1492100129342357534) is not None)

        # Раздел Модерация (для authorised roles)
        if is_mod:
            mod_parts = [
                "`.warn @user <причина>` - выдать предупреждение (3/3 → штраф)",
                "`.unwarn @user <причина>` - снять предупреждение",
                "`.mute @user --chat/--voice <причина>` - заблокировать чат/голос",
                "`.unmute @user` - снять блокировку",
                "`.ban @user <причина>` - выдать штрафную роль (4 Tier)",
                "`.unban @user` - снять штрафную роль"
            ]
            embed.add_field(
                name="🛡️ Модерация",
                value="\n".join(mod_parts),
                inline=False
            )

        if ctx.author.guild_permissions.administrator:
            admin_cmds = (
                "**Управление пользователями:**\n"
                "`.setprofile @user --position \"текст\"` - полная настройка профиля\n"
                "`.setprofile @user --level N` - установить уровень\n"
                "`.setprofile @user --xp N` - установить опыт\n\n"
                "**Очистка чата:**\n"
                "`.clear <период>` - удалить все сообщения за период (1m, 5h, 1d)\n"
                "`.clear @user` - удалить все сообщения пользователя\n"
                "`.clear @user <период>` - удалить сообщения пользователя за период"
            )
            embed.add_field(
                name="🛠️ Административные команды",
                value=admin_cmds,
                inline=False
            )

        if discord.utils.get(ctx.author.roles, id=config.SUBDIVISION_ROLE_ID) or ctx.author.guild_permissions.administrator:
            embed.add_field(
                name="📁 Управление подразделениями",
                value="`.setsubdivision @user <название>` - установить подразделение\n`.setsubdivision @user remove` - удалить подразделение",
                inline=False
            )

        # Раздел Система (только для администраторов)
        system_parts = []
        if ctx.author.guild_permissions.administrator:
            system_parts.append("`.update` - обновить все данные (Warframe + лидерборд)")
            system_parts.append("`.updatetable` - обновить таблицу лидеров")
            system_parts.append("`.sendquestionnaire` - отправить анкеты всем участникам")
        if system_parts:
            embed.add_field(
                name="⚙️ Система",
                value="\n".join(system_parts),
                inline=False
            )

        embed.set_footer(text="Для использования команд введите префикс '.' перед командой")
        try:
            await ctx.message.delete()
            await ctx.send(embed=embed, delete_after=60)
        except discord.Forbidden:
            await ctx.send("У меня нет прав на удаление сообщений!", delete_after=20)
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {str(e)}")

    @commands.command(name="setprofile")
    @commands.has_permissions(administrator=True)
    async def setprofile(self, ctx, member: discord.Member, *, args: str = ""):
        """Устанавливает профиль пользователя.
        Формат: .setprofile @user --position "текст" --level 5 --xp 100 --subdivision "название" """
        try:
            await ctx.message.delete()

            if not args:
                await ctx.send("Укажите хотя бы один параметр. Формат: `.setprofile @user --position \"текст\" --level 5 --xp 100 --subdivision \"название\"`", ephemeral=True, delete_after=10)
                return

            import re
            update_data = {}

            pos_match = re.search(r'--position\s+"([^"]*)"', args)
            if pos_match:
                update_data['position'] = pos_match.group(1)

            sub_match = re.search(r'--subdivision\s+"([^"]*)"', args)
            if sub_match:
                update_data['subdivision'] = sub_match.group(1)

            lvl_match = re.search(r'--level\s+(\d+)', args)
            if lvl_match:
                level = int(lvl_match.group(1))
                if level < 1:
                    raise ValueError("Уровень не может быть меньше 1")
                update_data['level'] = level

            xp_match = re.search(r'--xp\s+(\d+)', args)
            if xp_match:
                xp_val = int(xp_match.group(1))
                if xp_val < 0:
                    raise ValueError("Опыт не может быть отрицательным")
                update_data['xp'] = xp_val

            if not update_data:
                await ctx.send("Не распознаны параметры. Используйте: `--position \"текст\"`, `--subdivision \"текст\"`, `--level число`, `--xp число`", ephemeral=True, delete_after=10)
                return

            if 'xp' in update_data and 'level' not in update_data:
                temp_xp = update_data['xp']
                new_level = 1
                while True:
                    required = config.LEVEL_MULTIPLIER * new_level ** 2
                    if temp_xp < required:
                        break
                    new_level += 1
                update_data['level'] = new_level

            self.db.update_user(member.id, **update_data)

            parts = []
            if 'position' in update_data:
                parts.append(f"должность → {update_data['position']}")
            if 'subdivision' in update_data:
                parts.append(f"подразделение → {update_data['subdivision']}")
            if 'level' in update_data:
                parts.append(f"уровень → {update_data['level']}")
            if 'xp' in update_data:
                parts.append(f"опыт → {update_data['xp']}")

            await ctx.send(f"✅ Профиль {member.name} обновлён: {', '.join(parts)}", ephemeral=True, delete_after=5)
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {str(e)}")

    @commands.command(name="setsubdivision")
    async def setsubdivision(self, ctx, member: discord.Member, *, subdivision: str):
        """Устанавливает подразделение пользователю (только для ролей с правом назначения)."""
        try:
            await ctx.message.delete()

            has_permission = discord.utils.get(ctx.author.roles, id=config.SUBDIVISION_ROLE_ID) is not None or ctx.author.guild_permissions.administrator

            if not has_permission:
                await ctx.send("❌ У вас нет прав для использования этой команды.", ephemeral=True, delete_after=10)
                return

            if not subdivision.strip():
                await ctx.send("❌ Название подразделения не может быть пустым.", ephemeral=True, delete_after=5)
                return

            self.db.update_user(member.id, subdivision=subdivision.strip())
            await ctx.send(f"✅ Подразделение для {member.name} установлено: {subdivision}", ephemeral=True, delete_after=5)
        except Exception as e:
            await ctx.send(f"❌ Ошибка при установке подразделения: {str(e)}")


# --- Система уровней (ОПЦИОНАЛЬНО) ---

class LevelingSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        self.forbidden_channels = [
            1509113757077475360,
            1509116456896434247
        ]
        self.excluded_commands = ['profile', 'help', 'setprofile', 'setsubdivision', 'setlvl', 'updatetable']

    def calculate_random_xp(self, message):
        base_min = config.XP_PER_MESSAGE - 2
        base_max = config.XP_PER_MESSAGE + 2
        base_xp = random.randint(base_min, base_max)
        if len(message.content) > 100:
            base_xp += random.randint(3, 7)
        if message.mentions:
            base_xp += random.randint(1, 3)
        return base_xp

    async def add_experience(self, user_id, amount):
        try:
            user_data = self.db.get_user(user_id)
            old_level = user_data['level']
            self.db.add_xp(user_id, amount)
            new_level = self.db.get_user(user_id)['level']
            if new_level > old_level:
                await self._notify_level_up(user_id, new_level)
        except Exception as e:
            print(f"Ошибка при добавлении опыта: {str(e)}")

    async def _notify_level_up(self, user_id, new_level):
        try:
            member = self.bot.get_user(user_id)
            MILESTONE_LEVELS = {15, 25, 50, 75, 100}
            if member and new_level in MILESTONE_LEVELS:
                await member.send(f"🎉 Поздравляем! Вы достигли уровня {new_level}!")
                user_achievements = self.db.get_user(user_id).get('achievements', {})
                user_achievements[str(new_level)] = True
                self.db.update_user(user_id, achievements=user_achievements)
        except Exception as e:
            print(f"Ошибка при уведомлении о повышении уровня: {str(e)}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.channel.id in self.forbidden_channels:
            return
        # Не начисляем опыт за любые команды
        if message.content.startswith(self.bot.command_prefix):
            return
        random_xp = self.calculate_random_xp(message)
        await self.add_experience(message.author.id, random_xp)


# Функция для загрузки когов
async def setup(bot):
    try:
        await bot.add_cog(ProfileSystem(bot))
        await bot.add_cog(LevelingSystem(bot))
    except Exception as e:
        print(f"Ошибка при загрузке когов: {str(e)}")