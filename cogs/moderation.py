import discord
from discord.ext import commands
from utils.database import Database
from datetime import datetime, timedelta
import logging

# ID ролей, которые могут использовать команды модерации
ALLOWED_ROLES = [1493218079528976414, 1492100129342357534, 1510308913105469692]  # Добавлена роль бота
# ID штрафной роли 4 Tier
PENALTY_ROLE_ID = 1514368368180859090
# Названия создаваемых ролей
MUTED_ROLE_NAME = "Muted"
VOICE_MUTED_ROLE_NAME = "Voice-Muted"


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    def _check_permission(self, member: discord.Member) -> bool:
        """Проверяет, есть ли у пользователя доступ к командам."""
        if member.guild_permissions.administrator:
            return True
        return any(role.id in ALLOWED_ROLES for role in member.roles)

    async def _ensure_mute_roles(self, guild: discord.Guild):
        """Создаёт роли Muted и Voice-Muted, если их нет, и настраивает права в каналах."""
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
        voice_muted_role = discord.utils.get(guild.roles, name=VOICE_MUTED_ROLE_NAME)

        if not muted_role:
            muted_role = await guild.create_role(
                name=MUTED_ROLE_NAME,
                color=discord.Color.dark_gray(),
                reason="Автоматическое создание роли Muted",
                permissions=discord.Permissions.none()
            )
            logging.info(f"[Moderation] Создана роль {MUTED_ROLE_NAME} (ID: {muted_role.id})")

        if not voice_muted_role:
            voice_muted_role = await guild.create_role(
                name=VOICE_MUTED_ROLE_NAME,
                color=discord.Color.dark_gray(),
                reason="Автоматическое создание роли Voice-Muted",
                permissions=discord.Permissions.none()
            )
            logging.info(f"[Moderation] Создана роль {VOICE_MUTED_ROLE_NAME} (ID: {voice_muted_role.id})")

        # Настраиваем права в текстовых каналах для Muted
        for channel in guild.text_channels:
            try:
                overwrite = channel.overwrites_for(muted_role)
                overwrite.send_messages = False
                overwrite.add_reactions = False
                await channel.set_permissions(muted_role, overwrite=overwrite)
            except Exception as e:
                logging.warning(f"[Moderation] Не удалось настроить {channel.name} для Muted: {e}")

        # Настраиваем права в голосовых каналах для Voice-Muted
        for channel in guild.voice_channels:
            try:
                overwrite = channel.overwrites_for(voice_muted_role)
                overwrite.connect = False
                overwrite.speak = False
                overwrite.use_voice_activation = False
                overwrite.stream = False
                await channel.set_permissions(voice_muted_role, overwrite=overwrite)
            except Exception as e:
                logging.warning(f"[Moderation] Не удалось настроить {channel.name} для Voice-Muted: {e}")

        # Настраиваем права в категориях
        for category in guild.categories:
            try:
                overwrite_text = category.overwrites_for(muted_role)
                overwrite_text.send_messages = False
                overwrite_text.add_reactions = False
                await category.set_permissions(muted_role, overwrite=overwrite_text)

                overwrite_voice = category.overwrites_for(voice_muted_role)
                overwrite_voice.connect = False
                overwrite_voice.speak = False
                overwrite_voice.use_voice_activation = False
                await category.set_permissions(voice_muted_role, overwrite=overwrite_voice)
            except Exception as e:
                logging.warning(f"[Moderation] Не удалось настроить категорию {category.name}: {e}")

        return muted_role, voice_muted_role

    @commands.Cog.listener()
    async def on_ready(self):
        """При запуске создаём/настраиваем mute-роли."""
        for guild in self.bot.guilds:
            await self._ensure_mute_roles(guild)
            logging.info(f"[Moderation] Mute-роли настроены для гильдии {guild.name}")

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        """Автоматически настраивает mute-роли в новом канале."""
        guild = channel.guild
        muted_role = discord.utils.get(guild.roles, name=MUTED_ROLE_NAME)
        voice_muted_role = discord.utils.get(guild.roles, name=VOICE_MUTED_ROLE_NAME)

        if isinstance(channel, discord.TextChannel) and muted_role:
            try:
                overwrite = channel.overwrites_for(muted_role)
                overwrite.send_messages = False
                overwrite.add_reactions = False
                await channel.set_permissions(muted_role, overwrite=overwrite)
            except Exception as e:
                logging.warning(f"[Moderation] Не удалось настроить новый канал {channel.name}: {e}")

        if isinstance(channel, discord.VoiceChannel) and voice_muted_role:
            try:
                overwrite = channel.overwrites_for(voice_muted_role)
                overwrite.connect = False
                overwrite.speak = False
                overwrite.use_voice_activation = False
                await channel.set_permissions(voice_muted_role, overwrite=overwrite)
            except Exception as e:
                logging.warning(f"[Moderation] Не удалось настроить новый голосовой канал {channel.name}: {e}")

    # ==================== КОМАНДЫ ====================

    async def _apply_penalty(self, member: discord.Member, reason: str, moderator: discord.Member, is_ban: bool = False):
        """Выдаёт 4 Tier роль и снимает все остальные роли.
        Если is_ban=True — сохраняет как бан (без warn), иначе — как warn."""
        penalty_role = member.guild.get_role(PENALTY_ROLE_ID)
        if not penalty_role:
            return None

        # Сохраняем ID ролей в БД (кроме @everyone и штрафной)
        saved_roles = [r.id for r in member.roles if r.id != member.guild.default_role.id and r.id != PENALTY_ROLE_ID]

        try:
            await member.remove_roles(*[r for r in member.roles if r.id != member.guild.default_role.id and r.id != PENALTY_ROLE_ID], reason=f"Penalty: {reason}")
            await member.add_roles(penalty_role, reason=f"Penalty: {reason}")
        except Exception as e:
            logging.error(f"[Moderation] Ошибка при выдаче штрафа {member.id}: {e}")
            return None

        # Сохраняем position и subdivision
        user_bd = self.db.get_user(member.id)
        saved_position = user_bd.get('position')
        saved_subdivision = user_bd.get('subdivision')

        logging.info(f"[Moderation] Ban={is_ban} for {member.id}: position='{saved_position}', subdivision='{saved_subdivision}'")

        update_data = {"saved_roles": saved_roles, "saved_position": saved_position, "saved_subdivision": saved_subdivision}

        if is_ban:
            # Бан — без warn, просто отмечаем + сбрасываем position/subdivision
            update_data["banned"] = True
            update_data["ban_reason"] = reason
            update_data["position"] = None
            update_data["subdivision"] = None
            logging.info(f"[Moderation] Ban applied for {member.id}: position set to None, subdivision set to None")
        else:
            # warn (для команды warn и срабатывания 3/3)
            warns = self.db.get_user(member.id).get('warns', [])
            warns.append({
                "reason": reason,
                "moderator": moderator.id,
                "date": datetime.now().strftime('%d.%m.%Y %H:%M')
            })
            update_data["warns"] = warns

        self.db.update_user(member.id, **update_data)
        return penalty_role

    @commands.command(name="warn")
    async def warn(self, ctx, member: discord.Member, *, reason: str):
        """Выдаёт предупреждение пользователю. При 3 варнах — штрафная роль."""
        if not self._check_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для этой команды.", delete_after=10)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        if not reason.strip():
            await ctx.send("❌ Укажите причину.", delete_after=5)
            return

        warns = self.db.get_user(member.id).get('warns', [])
        warns.append({
            "reason": reason,
            "moderator": ctx.author.id,
            "date": datetime.now().strftime('%d.%m.%Y %H:%M')
        })
        self.db.update_user(member.id, warns=warns)

        # Если >= 3 — применяем штраф
        if len(warns) >= 3:
            await self._apply_penalty(member, f"3/3 варнов: {reason}", ctx.author)
            await ctx.send(f"✅ {member.mention} получил варн ({len(warns)}/3). Штрафная роль выдана!", delete_after=10)
        else:
            await ctx.send(f"✅ {member.mention} получил варн ({len(warns)}/3). Причина: {reason}", delete_after=10)

    @commands.command(name="unwarn")
    async def unwarn(self, ctx, member: discord.Member):
        """Снимает одно предупреждение с пользователя (последнее)."""
        if not self._check_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для этой команды.", delete_after=10)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        user_data = self.db.get_user(member.id)
        warns = user_data.get('warns', [])

        if not warns:
            await ctx.send(f"❌ У {member.mention} нет предупреждений.", delete_after=10)
            return

        # Удаляем последний warn
        removed_warn = warns.pop()
        self.db.update_user(member.id, warns=warns)

        # Если штрафная роль есть — снимаем её и возвращаем роли
        penalty_role = member.guild.get_role(PENALTY_ROLE_ID)
        if penalty_role and penalty_role in member.roles:
            saved_role_ids = user_data.get('saved_roles', [])
            restored_roles = []
            for role_id in saved_role_ids:
                role = member.guild.get_role(role_id)
                if role and role not in member.roles:
                    restored_roles.append(role)

            try:
                await member.remove_roles(penalty_role, reason="Unwarn: снятие штрафной роли")
                if restored_roles:
                    await member.add_roles(*restored_roles, reason="Unwarn: восстановление ролей")
                self.db.update_user(member.id,
                                    saved_roles=[],
                                    position=user_data.get('saved_position'),
                                    subdivision=user_data.get('saved_subdivision'))
            except Exception as e:
                logging.error(f"[Moderation] Ошибка при снятии штрафной роли для {member.id}: {e}")

        reason = removed_warn.get('reason', 'Причина не указана')
        date = removed_warn.get('date', '')
        remaining = len(warns)

        if penalty_role and penalty_role not in member.roles and remaining < 3:
            await ctx.send(
                f"✅ Снят варн с {member.mention} (было {remaining + 1}/3, осталось {remaining}/3). "
                f"Штрафная роль снята. Причина снятого варна: {reason}",
                delete_after=15
            )
        else:
            await ctx.send(
                f"✅ Снят варн с {member.mention} ({remaining}/3). Причина снятого варна: {reason}",
                delete_after=10
            )

    @commands.command(name="mute")
    async def mute(self, ctx, member: discord.Member, flag: str = "--chat", *, reason: str = "Причина не указана"):
        """Мут пользователя. Флаги: --chat (чат), --voice (голос)."""
        if not self._check_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для этой команды.", delete_after=10)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        muted_role = discord.utils.get(ctx.guild.roles, name=MUTED_ROLE_NAME)
        voice_muted_role = discord.utils.get(ctx.guild.roles, name=VOICE_MUTED_ROLE_NAME)

        if flag == "--chat":
            if not muted_role:
                muted_role, _ = await self._ensure_mute_roles(ctx.guild)
            await member.add_roles(muted_role, reason=f"Mute chat: {reason}")
            await ctx.send(f"✅ {member.mention} заблокирован в чате. Причина: {reason}", delete_after=10)

        elif flag == "--voice":
            if not voice_muted_role:
                _, voice_muted_role = await self._ensure_mute_roles(ctx.guild)
            await member.add_roles(voice_muted_role, reason=f"Mute voice: {reason}")
            # Если пользователь в голосовом канале — отключаем микро и звук
            if member.voice and member.voice.channel:
                try:
                    await member.edit(mute=True, deafen=True)
                except Exception:
                    pass
            await ctx.send(f"✅ {member.mention} заблокирован в голосовых каналах. Причина: {reason}", delete_after=10)
        else:
            await ctx.send("❌ Использование: `.mute @user --chat <причина>` или `.mute @user --voice <причина>`", delete_after=10)

    @commands.command(name="unmute")
    async def unmute(self, ctx, member: discord.Member):
        """Снимает все mute-роли с пользователя."""
        if not self._check_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для этой команды.", delete_after=10)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        muted_role = discord.utils.get(ctx.guild.roles, name=MUTED_ROLE_NAME)
        voice_muted_role = discord.utils.get(ctx.guild.roles, name=VOICE_MUTED_ROLE_NAME)

        removed = []
        if muted_role and muted_role in member.roles:
            await member.remove_roles(muted_role, reason="Unmute")
            removed.append("чат")

        if voice_muted_role and voice_muted_role in member.roles:
            await member.remove_roles(voice_muted_role, reason="Unmute")
            # Снимаем мут в голосе если был
            if member.voice and member.voice.channel:
                try:
                    await member.edit(mute=False, deafen=False)
                except Exception:
                    pass
            removed.append("голос")

        if removed:
            await ctx.send(f"✅ {member.mention} разблокирован: {', '.join(removed)}", delete_after=10)
        else:
            await ctx.send(f"❌ У {member.mention} нет активных мутов.", delete_after=10)

    @commands.command(name="ban")
    async def ban_user(self, ctx, member: discord.Member, *, reason: str = "Нарушение правил"):
        """Выдаёт штрафную роль (4 Tier) и снимает все остальные роли (без warn'ов)."""
        if not self._check_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для этой команды.", delete_after=10)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        if not reason.strip():
            reason = "Нарушение правил"

        result = await self._apply_penalty(member, reason, ctx.author, is_ban=True)
        if result:
            await ctx.send(f"✅ Пользователю {member.mention} выдана штрафная роль. Причина: {reason}", delete_after=10)
        else:
            await ctx.send("❌ Не удалось выдать штрафную роль.", delete_after=10)

    @commands.command(name="unban")
    async def unban_user(self, ctx, member: discord.Member):
        """Снимает штрафную роль (4 Tier) и возвращает сохранённые роли."""
        if not self._check_permission(ctx.author):
            await ctx.send("❌ У вас нет прав для этой команды.", delete_after=10)
            return

        try:
            await ctx.message.delete()
        except Exception:
            pass

        penalty_role = ctx.guild.get_role(PENALTY_ROLE_ID)
        if not penalty_role or penalty_role not in member.roles:
            await ctx.send(f"❌ У {member.mention} нет штрафной роли.", delete_after=10)
            return

        # Получаем сохранённые роли из БД
        user_data = self.db.get_user(member.id)
        saved_role_ids = user_data.get('saved_roles', [])

        restored_roles = []
        not_found = []
        for role_id in saved_role_ids:
            role = ctx.guild.get_role(role_id)
            if role and role not in member.roles:
                restored_roles.append(role)
            elif not role:
                not_found.append(role_id)

        try:
            # Снимаем штрафную роль
            await member.remove_roles(penalty_role, reason="Unban")
            # Возвращаем сохранённые роли
            if restored_roles:
                await member.add_roles(*restored_roles, reason="Unban: восстановление ролей")

            # Восстанавливаем position и subdivision, очищаем warns и статус бана
            self.db.update_user(member.id, 
                                saved_roles=[], 
                                warns=[], 
                                banned=False, 
                                ban_reason=None,
                                position=user_data.get('saved_position'),
                                subdivision=user_data.get('saved_subdivision'))

            msg = f"✅ Штрафная роль снята с {member.mention}."
            if restored_roles:
                msg += f" Возвращено ролей: {len(restored_roles)}."
            if not_found:
                msg += f" Не найдено ролей: {len(not_found)} (возможно, удалены)."
            await ctx.send(msg, delete_after=10)

        except Exception as e:
            logging.error(f"[Moderation] Ошибка при анбане {member.id}: {e}")
            await ctx.send("❌ Произошла ошибка при разбане.", delete_after=10)


    # ==================== CLEAR ====================

    def _parse_period(self, text: str) -> timedelta | None:
        """Парсит строку периода (например '5m', '2h', '1d') и возвращает timedelta."""
        if not text:
            return None
        text = text.strip().lower()
        if not text[-1].isdigit():
            unit = text[-1]
            num_str = text[:-1]
        else:
            return None

        try:
            num = int(num_str)
        except (ValueError, IndexError):
            return None

        if unit == 'm':
            return timedelta(minutes=num)
        elif unit == 'h':
            return timedelta(hours=num)
        elif unit == 'd':
            return timedelta(days=num)
        return None

    @commands.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def clear(self, ctx, *args):
        """
        Очищает сообщения в чате.
        Использование:
          .clear <период>           — удалить все сообщения за период
          .clear @user              — удалить все сообщения пользователя
          .clear @user <период>     — удалить сообщения пользователя за период
        Периоды: Xm (минуты), Xh (часы), Xd (дни)
        """
        try:
            await ctx.message.delete()
        except Exception:
            pass

        target_user = None
        period_str = None

        for arg in args:
            # Проверяем, является ли аргумент упоминанием пользователя
            if ctx.message.mentions:
                # arg может быть строкой вида '<@123456789>' или '<@!123456789>'
                for member in ctx.message.mentions:
                    if str(member.id) in arg:
                        target_user = member
                        break
            elif arg.startswith('<@') and arg.endswith('>'):
                # Попытка найти пользователя по ID из упоминания
                user_id = arg.strip('<@!>')
                try:
                    target_user = await ctx.guild.fetch_member(int(user_id))
                except (ValueError, discord.NotFound):
                    pass
            elif self._parse_period(arg) is not None:
                period_str = arg
            else:
                # Попробуем распознать как период без суффикса (на случай опечатки)
                if self._parse_period(arg) is not None:
                    period_str = arg

        # Если ничего не указано
        if not target_user and not period_str:
            await ctx.send(
                "❌ Укажите @user или период для использования команды",
                delete_after=10
            )
            return

        # Вычисляем время отсечки
        if period_str:
            delta = self._parse_period(period_str)
            cutoff = ctx.message.created_at - delta
        else:
            # Пользователь указан без периода — удаляем ВСЕ его сообщения (до 14-дневного лимита Discord)
            # Discord API: bulk delete доступен только для сообщений < 14 дней
            cutoff = ctx.message.created_at - timedelta(days=14)

        # Проверка на 14-дневный лимит Discord
        if (ctx.message.created_at - cutoff).days > 14:
            cutoff = ctx.message.created_at - timedelta(days=14)

        # Функция фильтрации по автору
        def check_author(message):
            if target_user:
                return message.author.id == target_user.id
            return True

        # Удаляем сообщения
        try:
            deleted = await ctx.channel.purge(
                limit=2000,
                before=ctx.message.created_at,
                after=cutoff,
                check=check_author
            )
            count = len(deleted)
        except discord.Forbidden:
            await ctx.send("❌ У меня нет прав для удаления сообщений в этом канале.", delete_after=10)
            return
        except discord.HTTPException as e:
            await ctx.send(f"❌ Ошибка при удалении сообщений: {e}", delete_after=10)
            return

        # Формируем ответ
        if target_user:
            msg = f"✅ Удалено **{count}** сообщений пользователя {target_user.mention}"
        else:
            msg = f"✅ Удалено **{count}** сообщений"

        if period_str:
            msg += f" за период {period_str}"

        sent = await ctx.send(msg, delete_after=5)


async def setup(bot):
    await bot.add_cog(Moderation(bot))
