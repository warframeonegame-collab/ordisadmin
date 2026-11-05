import discord
import discord.app_commands as app_commands
from discord.ext import commands
import logging
import traceback
import config
from utils.database import Database
from utils import cards
from utils.bot_errors import BotErrorsManager
from datetime import datetime
import random
import time


# ==================== Бренд-палитра Ордиса ====================
BRAND_GOLD = discord.Color.from_str('#F0C96A')   # Orokin gold
BRAND_CYAN = discord.Color.from_str('#00E5FF')   # неон


def build_xp_bar(xp, level, length=10):
    """Прогресс-бар до следующего уровня: ▰▰▰▱▱ — 40% (1234 XP)."""
    next_xp = config.LEVEL_MULTIPLIER * (level + 1) ** 2
    frac = max(0.0, min(1.0, (xp or 0) / next_xp)) if next_xp else 0.0
    filled = round(frac * length)
    pct = int(frac * 100)
    return "▰" * filled + "▱" * (length - filled), pct, next_xp


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


# ==================== HELP 2.0 (селект-меню) ====================

HELP_CATEGORIES = {
    'profile': {
        'emoji': '👤', 'name': 'Профиль',
        'commands': (
            "`.profile [@user]` — ваш профиль или профиль другого участника\n"
            "`.help` — показать это меню\n"
            "**Слэш:** то же самое через `/profile`, `/help` (с автодополнением)"
        ),
    },
    'moderation': {
        'emoji': '🛡️', 'name': 'Модерация', 'mod_only': True,
        'commands': (
            "`.warn @user <причина>` — выдать предупреждение (3/3 → штраф)\n"
            "`.unwarn @user <причина>` — снять предупреждение\n"
            "`.mute @user --chat/--voice <причина>` — заблокировать чат/голос\n"
            "`.unmute @user` — снять блокировку\n"
            "`.ban @user <причина>` — выдать штрафную роль (4 Tier)\n"
            "`.unban @user` — снять штрафную роль\n"
            "**Слэш:** `/warn`, `/unwarn`, `/mute`, `/unmute`, `/ban`, `/unban`"
        ),
    },
    'admin': {
        'emoji': '🛠️', 'name': 'Административные', 'admin_only': True,
        'commands': (
            "**Управление пользователями:**\n"
            "`.setprofile @user --position \"текст\"` — полная настройка профиля\n"
            "`.setprofile @user --level N` — установить уровень\n"
            "`.setprofile @user --xp N` — установить опыт\n\n"
            "**Очистка чата:**\n\n"
            "`.clear <период>` — удалить сообщения за период (1m, 5h, 1d)\n"
            "`.clear @user [период]` — удалить сообщения участника\n"
            "**Слэш:** `/setprofile`, `/clear`, `/setsubdivision`"
        ),
    },
    'system': {
        'emoji': '⚙️', 'name': 'Система', 'admin_only': True,
        'commands': (
            "`.update` — обновить все данные (Warframe + лидерборд)\n"
            "`.updatetable` — обновить таблицу лидеров\n"
            "`.sendquestionnaire` — отправить анкеты всем участникам\n"
            "**Слэш:** `/update`, `/updatetable`, `/sendquestionnaire`"
        ),
    },
}


class HelpView(discord.ui.View):
    """Select-меню с разделами помощи (показываются только доступные по ролям)."""

    def __init__(self, author, available_keys):
        super().__init__(timeout=120)
        self.author = author
        self._bot_errors = BotErrorsManager()
        self.categories = {HELP_CATEGORIES[k]['name']: HELP_CATEGORIES[k] for k in available_keys}
        select = discord.ui.Select(
            placeholder="📂 Выберите раздел команд...",
            options=[
                discord.SelectOption(
                    label=HELP_CATEGORIES[k]['name'],
                    emoji=HELP_CATEGORIES[k]['emoji'],
                    value=HELP_CATEGORIES[k]['name'],
                ) for k in available_keys
            ],
        )
        select.callback = self._on_select
        self.add_item(select)
        self._category_embeds = {}

    def set_embed(self, name, embed):
        self._category_embeds[name] = embed

    async def _on_select(self, interaction: discord.Interaction):
        try:
            if interaction.user.id != self.author.id:
                await interaction.response.send_message("❌ Меню доступно только открывшему его.", ephemeral=True)
                return
            name = interaction.data['values'][0]
            embed = self._category_embeds.get(name)
            if embed is None:
                cat = self.categories[name]
                embed = discord.Embed(
                    title=f"{cat['emoji']} {name}",
                    description=cat['commands'],
                    color=BRAND_CYAN
                )
                self._category_embeds[name] = embed
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception as e:
            logger.error(f"[HelpView] Ошибка выбора раздела: {e}\n{traceback.format_exc()}")
            self._bot_errors.add_error(
                error_type=type(e).__name__,
                error_message=str(e),
                source="компонент: HelpView select",
                user_id=str(interaction.user.id),
                user_name=getattr(interaction.user, 'display_name', ''),
                details={'traceback': traceback.format_exc()[:2000]},
            )
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Не удалось переключить раздел, ошибка записана в логи.", ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        """Ловим ЛЮБЫЕ ошибки вьюхи (в т.ч. до вызова колбэка) с полным трейсбеком."""
        logger.error(f"[HelpView] on_error: {error}\n{traceback.format_exc()}")
        self._bot_errors.add_error(
            error_type=type(error).__name__,
            error_message=str(error),
            source="компонент: HelpView on_error",
            user_id=str(interaction.user.id) if interaction else '',
            user_name=getattr(interaction.user, 'display_name', '') if interaction else '',
            details={'traceback': traceback.format_exc()[:2000]},
        )
        try:
            if interaction and not interaction.response.is_done():
                await interaction.response.send_message(
                    "❌ Ошибка меню, подробности в логах.", ephemeral=True)
        except Exception:
            pass

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

    @commands.hybrid_command(name="profile", description="Показать профиль участника клана")
    @app_commands.describe(member="Участник (по умолчанию — вы)")
    async def profile(self, ctx, member: discord.Member = None):
        """Показывает профиль участника с прогрессом XP, достижениями и варнами."""
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
        bar, pct, _ = build_xp_bar(xp_into_level, user['level'])

        embed = discord.Embed(
            title=f"Профиль {member.display_name}",
            color=BRAND_GOLD
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=f"Запрошено {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)

        embed.add_field(name="📋 Никнейм", value=user['nickname'] or member.display_name, inline=False)
        embed.add_field(name="🥉 Тир", value=user_tier, inline=True)
        if user.get('position'):
            embed.add_field(name="🏷️ Должность", value=user['position'], inline=True)
        if user.get('subdivision'):
            embed.add_field(name="📁 Подразделение", value=user['subdivision'], inline=True)

        embed.add_field(
            name="📅 Дата вступления",
            value=f"{user['joined_at']}\n🏆 Уровень: {user['level']}",
            inline=False
        )

        embed.add_field(
            name="📊 Прогресс уровня",
            value=f"`{bar}` **{pct}%**\nОсталось {max(0, remaining_xp)} XP до {user['level'] + 1} уровня",
            inline=False
        )
        is_slash = isinstance(ctx.interaction, discord.Interaction)
        if not is_slash:
            await ctx.message.delete()

        # Карточка профиля (PNG) — дешёвый рендер 1 раз при вызове
        file = None
        try:
            avatar_entries = [{'user_id': str(member.id),
                               'avatar_url': member.display_avatar.with_size(96).url}]
            avatars = await cards.fetch_avatars(avatar_entries)
            card_path = cards.build_profile_card(
                member.display_name, user['level'],
                avatars.get(str(member.id)), config.PROFILE_CARD_PATH)
            if card_path:
                file = discord.File(card_path, filename="profile.png")
                embed.set_image(url="attachment://profile.png")
        except Exception as e:
            logging.debug(f"[Profile] Карточка не собралась: {e}")

        # Создаём embed достижений
        achievements_cog = self.bot.get_cog("Achievements")
        achievements_embed = None
        if achievements_cog:
            achievements_embed = await achievements_cog.get_achievements_embed(member, ctx.author)

        # Создаём embed варнов
        warns_embed = self._build_warns_embed(member, ctx.author, user)

        view = ProfileView(member, user, embed, achievements_embed, warns_embed, ctx.author)

        send_kwargs = dict(embed=embed, view=view, delete_after=60)
        if isinstance(ctx.interaction, discord.Interaction):
            send_kwargs['ephemeral'] = False
        if file is not None:
            send_kwargs['file'] = file
        await ctx.send(**send_kwargs)

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
        emb.set_thumbnail(url=member.display_avatar.url)
        emb.set_footer(text=f"Запрошено {author.display_name}", icon_url=author.display_avatar.url)
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

        is_slash = isinstance(ctx.interaction, discord.Interaction)
        if is_slash:
            await ctx.interaction.response.send_message(embed=embed, delete_after=60)
        else:
            await ctx.message.delete()
            await ctx.send(embed=embed, delete_after=60)

    # --- Help 2.0 (селект-меню) ---
    @commands.hybrid_command(name="help", description="Справка по командам бота")
    async def help_command(self, ctx):
        """Меню помощи с селектом разделов (показываются только доступные вам)."""
        available = []
        for key, cat in HELP_CATEGORIES.items():
            if cat.get('mod_only'):
                is_mod = (discord.utils.get(ctx.author.roles, id=1493218079528976414) is not None or
                          discord.utils.get(ctx.author.roles, id=1492100129342357534) is not None)
                if not is_mod:
                    continue
            if cat.get('admin_only') and not ctx.author.guild_permissions.administrator:
                continue
            available.append(key)

        view = HelpView(ctx.author, available)
        first = HELP_CATEGORIES[available[0]]
        embed = discord.Embed(
            title=f"{first['emoji']} {first['name']}",
            description=first['commands'],
            color=BRAND_CYAN
        )
        embed.set_footer(text="Выберите другой раздел через меню ниже • префикс '.' или слэш '/'")
        view.set_embed(first['name'], embed)

        is_slash = isinstance(ctx.interaction, discord.Interaction)
        if is_slash:
            await ctx.send(embed=embed, view=view, ephemeral=True)
        else:
            await ctx.message.delete()
            await ctx.send(embed=embed, view=view)

    # --- Административные команды (РАБОТАЮТ ВСЕГДА) ---
    @commands.hybrid_command(name="setprofile", description="Настройка параметров профиля участника")
    @app_commands.describe(
        member="Участник",
        args='Параметры: --position "текст" --level N --xp N --subdivision "текст"',
    )
    @commands.has_permissions(administrator=True)
    async def setprofile(self, ctx, member: discord.Member, *, args: str = ""):
        """Устанавливает профиль пользователя.
        Формат: .setprofile @user --position "текст" --level 5 --xp 100 --subdivision "название" """
        try:
            if not isinstance(ctx.interaction, discord.Interaction):
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

    @commands.hybrid_command(name="setsubdivision", description="Установить участнику подразделение")
    @app_commands.describe(member="Участник", subdivision="Название подразделения (или remove)")
    async def setsubdivision(self, ctx, member: discord.Member, *, subdivision: str):
        """Устанавливает подразделение пользователю (только для ролей с правом назначения)."""
        try:
            if not isinstance(ctx.interaction, discord.Interaction):
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
        # Кулдаун XP (анти-спам): {user_id: monotonic_ts}
        self._last_xp = {}

    def calculate_random_xp(self, message):
        base_min = config.XP_PER_MESSAGE - 2
        base_max = config.XP_PER_MESSAGE + 2
        base_xp = random.randint(base_min, base_max)
        if len(message.content) > 100:
            base_xp += random.randint(3, 7)
        if message.mentions:
            base_xp += random.randint(1, 3)
        return base_xp

    def _xp_cooldown_ok(self, user_id):
        """Проверяет и обновляет кулдаун XP; держит словарь компактным."""
        now = time.monotonic()
        last = self._last_xp.get(user_id)
        if last is not None and now - last < config.XP_COOLDOWN_SECONDS:
            return False
        self._last_xp[user_id] = now
        if len(self._last_xp) > 1000:
            cutoff = now - config.XP_COOLDOWN_SECONDS
            for uid in [u for u, t in self._last_xp.items() if t < cutoff]:
                del self._last_xp[uid]
        return True

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
        """Уведомление о повышении уровня + награда ролью при достижении порогов."""
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

        await self.maybe_award_level(user_id, new_level)

    async def maybe_award_level(self, user_id, new_level):
        """Выдаёт роли-награды за уровни (config.LEVEL_ROLE_REWARDS).

        Вызывается и из сообщений, и из голосового XP (voice_xp.py).
        """
        guild = self.bot.get_guild(config.GUILD_ID) if config.GUILD_ID else None
        if not guild:
            return
        member = guild.get_member(int(user_id))
        if member is None or member.bot:
            return

        achievements = None
        for threshold, role_name in sorted(config.LEVEL_ROLE_REWARDS.items()):
            if new_level < threshold:
                continue
            try:
                if any(r.name == role_name for r in member.roles):
                    continue
                role = discord.utils.get(guild.roles, name=role_name)
                if role is None:
                    role = await guild.create_role(
                        name=role_name,
                        reason=f"Авто-роль за {threshold} уровень"
                    )
                await member.add_roles(role, reason=f"Достигнут {threshold} уровень")
                if achievements is None:
                    achievements = self.db.get_user(user_id).get('achievements', {}) or {}
                achievements[f'role_{threshold}'] = True
                logging.info(f"[Levels] {member} получил роль '{role_name}' (уровень {new_level})")
            except discord.Forbidden:
                logging.warning(f"[Levels] Нет прав добавить роль '{role_name}' участнику {member}")
            except Exception as e:
                logging.error(f"[Levels] Ошибка выдачи роли за уровень: {e}")

        if achievements is not None:
            self.db.update_user(user_id, achievements=achievements)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        if message.channel.id in self.forbidden_channels:
            return
        # Не начисляем опыт за любые команды
        if message.content.startswith(self.bot.command_prefix):
            return
        # Кулдаун: спам не прокачивает уровень
        if not self._xp_cooldown_ok(message.author.id):
            return
        random_xp = self.calculate_random_xp(message)
        await self.add_experience(message.author.id, random_xp)


# Функция для загрузки когов
async def setup(bot):
    await bot.add_cog(ProfileSystem(bot))
    await bot.add_cog(LevelingSystem(bot))
