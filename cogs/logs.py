import discord
from discord.ext import commands
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

class Logs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.LOG_CHANNEL_ID = 1255221212519596184  # ID канала логов
        self.admin_actions = defaultdict(list)  # Хранилище действий администраторов
        self.action_timeout = timedelta(seconds=10)  # Временной интервал для отслеживания
        self.move_requests = {}  # Отслеживание запросов на перемещение
        self._processed_events = {}  # Кэш для предотвращения дублирования событий
        self._cache_ttl = 2.0  # Время жизни кэша (сек)
        from utils.logs_manager import LogsManager
        self.local_logs = LogsManager()

    def _is_duplicate(self, event_key: str) -> bool:
        """Проверяет, не было ли это событие уже обработано (для предотвращения дублирования)."""
        now = datetime.now().timestamp()
        if event_key in self._processed_events:
            if now - self._processed_events[event_key] < self._cache_ttl:
                return True
        self._processed_events[event_key] = now
        # Очистка старых записей
        for key in list(self._processed_events.keys()):
            if now - self._processed_events[key] > self._cache_ttl:
                del self._processed_events[key]
        return False

    # Вспомогательная функция для отправки лога с указанием исполнителя
    async def send_log(self, title, description, executor=None, color=discord.Color.gold()):
        try:
            channel = await self.bot.fetch_channel(self.LOG_CHANNEL_ID)
        except discord.NotFound:
            print(f"[ОШИБКА] Канал с ID {self.LOG_CHANNEL_ID} не найден на сервере.")
            return
        except discord.Forbidden:
            print(f"[ОШИБКА] У бота нет прав доступа к каналу с ID {self.LOG_CHANNEL_ID}.")
            return


        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.utcnow()
        )
        if executor:
            embed.add_field(name="Исполнитель", value=executor.mention, inline=True)
        embed.set_footer(text="Система логов")

        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            print(f"[ОШИБКА ЛОГОВ] У бота нет прав на отправку сообщений в канал.")
        except Exception as e:
            print(f"[ОШИБКА ЛОГОВ] Не удалось отправить лог: {e}")

    async def send_log_local(self, log_type, title, description, executor=None, color=None, attachments=None):
        """Дублирует лог в локальный файл"""
        if color is None:
            color = 0xf1c40f
        author_id = str(executor.id) if executor else ''
        author_name = executor.display_name if executor else ''
        self.local_logs.add_log(
            log_type=log_type,
            title=title,
            description=description,
            author_id=author_id,
            author_name=author_name,
            color=color,
            attachments=attachments or [],
        )


    # Логирование выполненных команд
    @commands.Cog.listener()
    async def on_command_completion(self, ctx):
        # Создаем уникальный ключ: команда + ID сообщения + ID автора
        event_key = f"cmd_complete:{ctx.message.id}:{ctx.author.id}"
        if self._is_duplicate(event_key):
            return
        await self.send_log(
            title=f"Выполнена команда: `{ctx.command}`",
            description=f"Автор: {ctx.author.mention}\n"
                       f"Сервер: {ctx.guild.name}\n"
                       f"Канал: {ctx.channel.mention}\n"
                       f"Команда: `{ctx.message.content}`",
            executor=ctx.author,
            color=discord.Color.green()
        )
        # Дублируем в локальный лог
        await self.send_log_local(
            log_type='command',
            title=f"Выполнена команда: {ctx.command}",
            description=f"Автор: {ctx.author}\nКоманда: {ctx.message.content}",
            executor=ctx.author,
            color=0x28a745
        )

    # Логирование ошибок команд
    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        event_key = f"cmd_error:{ctx.message.id}:{type(error).__name__}"
        if self._is_duplicate(event_key):
            return
        await self.send_log(
            title=f"Ошибка команды: `{ctx.command}`",
            description=f"Автор: {ctx.author.mention}\n"
                       f"Ошибка: {error}\n"
                       f"Команда: `{ctx.message.content}`",
            executor=ctx.author,
            color=discord.Color.red()
        )
        await self.send_log_local(
            log_type='command',
            title=f"Ошибка команды: {ctx.command}",
            description=f"Автор: {ctx.author}\nОшибка: {error}\nКоманда: {ctx.message.content}",
            executor=ctx.author,
            color=0xdc3545
        )

    # Логирование удаления сообщений
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.author.bot:
            return  # Не логируем ботов
        
        # Собираем URL вложений (изображения)
        attachments = []
        for att in message.attachments:
            attachments.append(att.url)
        
        # Формируем описание для Discord embed
        desc = f"Автор: {message.author.mention}\n"
        desc += f"Сервер: {message.guild.name}\n"
        desc += f"Канал: {message.channel.mention}\n"
        if message.content:
            desc += f"Сообщение: {message.content}"
        
        # Отправляем в Discord (с изображением если есть)
        embed = discord.Embed(
            title="Удалено сообщение",
            description=desc,
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )
        if attachments:
            embed.set_image(url=attachments[0])
        try:
            channel = await self.bot.fetch_channel(self.LOG_CHANNEL_ID)
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[ОШИБКА ЛОГОВ] {e}")
        
        # Дублируем в локальный лог (с изображениями)
        await self.send_log_local(
            log_type='delete',
            title='Удалено сообщение',
            description=f"Автор: {message.author}\nКанал: {message.channel.name}\nСообщение: {message.content[:200]}",
            executor=message.author,
            color=0x9b59b6,
            attachments=attachments
        )

    # Логирование редактирования сообщений
    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or before.content == after.content:
            return  # Не логируем ботов и пустые правки
        
        # Собираем URL вложений (изображения)
        attachments = []
        for att in after.attachments:
            attachments.append(att.url)
        
        await self.send_log(
            title="Отредактировано сообщение",
            description=f"Автор: {before.author.mention}\n"
                       f"Сервер: {before.guild.name}\n"
                       f"Канал: {before.channel.mention}\n"
                       f"**Было:** {before.content}\n"
                       f"**Стало:** {after.content}",
            color=discord.Color.blurple()
        )
        await self.send_log_local(
            log_type='edit',
            title='Отредактировано сообщение',
            description=f"Автор: {before.author}\nКанал: {before.channel.name}\nБыло: {before.content[:200]}\nСтало: {after.content[:200]}",
            executor=before.author,
            color=0x3498db,
            attachments=attachments
        )

    # Логирование подключения пользователя (с определением источника приглашения)
    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Пытаемся получить информацию о приглашении
        invites_before = await member.guild.invites()
        await asyncio.sleep(2)  # Ждём обновления списка приглашений
        invites_after = await member.guild.invites()

        invite_used = None
        for inv_before in invites_before:
            for inv_after in invites_after:
                if inv_before.code == inv_after.code and inv_before.uses != inv_after.uses:
                    invite_used = inv_after
                    break
            if invite_used:
                break

        if invite_used:
            source = f"По приглашению от {invite_used.inviter.mention} (ссылка: `{invite_used.code}`)"
        else:
            source = "По прямой ссылке или через поиск сервера"


        desc = f"Пользователь: {member.mention} ({member.id})\n" \
               f"Никнейм: {member.display_name}\n" \
               f"Аккаунт создан: {member.created_at.strftime('%d.%m.%Y %H:%M')}\n" \
               f"Источник вступления: {source}"
        await self.send_log(
            title="НОВЫЙ УЧАСТНИК",
            description=desc,
            color=discord.Color.green()
        )

    # Логирование кика и покидания сервера
    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Проверяем, был ли это кик
        async for entry in member.guild.audit_logs(limit=1, action=discord.AuditLogAction.kick):
            if entry.target == member:
                executor = entry.user
                reason = entry.reason or "Причина не указана"
                desc = f"Пользователь: {member.mention} ({member.id})\n" \
                       f"Никнейм: {member.display_name}\n" \
                       f"Причина кика: {reason}"
                await self.send_log(
                    title="ПОЛЬЗОВАТЕЛЬ БЫЛ КИКНУТ",
            description=desc,
            executor=executor,
            color=discord.Color.orange()
        )
                return

        # Если не кик, а обычное покидание
        desc = f"Пользователь: {member.mention} ({member.id})\n" \
               f"Никнейм: {member.display_name}"
        await self.send_log(
            title="ПОЛЬЗОВАТЕЛЬ ПОКИНУЛ СЕРВЕР",
            description=desc,
            color=discord.Color.light_orange()
        )

    # Логирование изменения ника, дискриминатора и ролей пользователя
    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Проверка изменения отображаемого имени
        if before.display_name != after.display_name:
            desc = f"Пользователь: {after.mention} ({after.id})\n" \
                   f"Было: {before.display_name}\n" \
                   f"Стало: {after.display_name}"
            await self.send_log(
                title="ИЗМЕНЕНИЕ НИКА",
                description=desc,
                color=discord.Color.blue()
            )

        # Проверка изменения дискриминатора (тега #0000)
        if before.discriminator != after.discriminator:
            desc = f"Пользователь: {after.mention} ({after.id})\n" \
                   f"Старый тег: #{before.discriminator}\n" \
                   f"Новый тег: #{after.discriminator}"
            await self.send_log(
                title="ИЗМЕНЕНИЕ ДИСКРИМИНАТОРА",
                description=desc,
                color=discord.Color.orange()
            )

        # Проверка изменения ролей
        before_roles = set(before.roles)
        after_roles = set(after.roles)

        added_roles = after_roles - before_roles
        removed_roles = before_roles - after_roles

        if added_roles or removed_roles:
            # Получаем информацию о том, кто изменил роли
            executor = None
            async for entry in before.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
                if entry.target == before:
                    executor = entry.user
                    break

            desc = f"Пользователь: {after.mention} ({after.id})\n" \
                   f"Сервер: {after.guild.name}\n"

            if added_roles:
                added_desc = []
                for role in added_roles:
                    added_desc.append(f"+ {role.mention} ({role.name})")
                desc += "**Добавленные роли:**\n" + "\n".join(added_desc) + "\n"

            if removed_roles:
                removed_desc = []
                for role in removed_roles:
                    removed_desc.append(f"- {role.mention} ({role.name})")
                desc += "**Удалённые роли:**\n" + "\n".join(removed_desc)

            await self.send_log(
                title="ИЗМЕНЕНИЕ РОЛЕЙ ПОЛЬЗОВАТЕЛЯ",
                description=desc.strip(),
                executor=executor,
                color=discord.Color.teal()
            )

    # Логирование бана пользователя
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        # Получаем информацию из аудита
        executor = None
        reason = "Причина не указана"
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target == user:
                executor = entry.user
                reason = entry.reason or "Причина не указана"
                break

        desc = f"Сервер: {guild.name}\n" \
               f"Заблокированный: {user.mention} ({user.id})\n" \
               f"Причина: {reason}"
        await self.send_log(
            title="ВЫДАЧА БАНА",
            description=desc,
            executor=executor,
            color=discord.Color.dark_red()
        )

    # Логирование разбана пользователя
    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        # Получаем информацию из аудита
        executor = None
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
            if entry.target == user:
                executor = entry.user
                break

        desc = f"Сервер: {guild.name}\n" \
               f"Разблокированный: {user.mention} ({user.id})"
        await self.send_log(
            title="РАЗБАН",
            description=desc,
            executor=executor,
            color=discord.Color.dark_green()
        )

    # Логирование создания канала
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        # Получаем информацию о создателе
        executor = None
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if entry.target == channel:
                executor = entry.user
                break

        desc = f"Канал: {channel.mention} ({channel.name})\n" \
               f"Тип: {type(channel).__name__}\n" \
               f"Категория: {channel.category.name if channel.category else 'Нет категории'}"
        await self.send_log(
            title="СОЗДАН КАНАЛ",
            description=desc,
            executor=executor,
            color=discord.Color.green()
        )

    # Логирование удаления канала
    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        # Получаем информацию об удалителе
        executor = None
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if entry.target == channel:
                executor = entry.user
                break

        desc = f"Канал: {channel.name}\n" \
               f"Тип: {type(channel).__name__}\n" \
               f"Категория: {channel.category.name if channel.category else 'Нет категории'}"
        await self.send_log(
            title="УДАЛЁН КАНАЛ",
            description=desc,
            executor=executor,
            color=discord.Color.red()
        )

    # Логирование изменения канала
    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []

        if before.name != after.name:
            changes.append(f"Название: `{before.name}` → `{after.name}`")
        if before.position != after.position:
            changes.append(f"Позиция: `{before.position}` → `{after.position}`")
        if before.category != after.category:
            old_cat = before.category.name if before.category else "Нет категории"
            new_cat = after.category.name if after.category else "Нет категории"
            changes.append(f"Категория: `{old_cat}` → `{new_cat}`")


        # Проверяем изменения разрешений канала
        if before.overwrites != after.overwrites:
            changes.append("Изменены разрешения доступа")

        if changes:
            # Получаем информацию о том, кто изменил канал
            executor = None
            async for entry in before.guild.audit_logs(limit=5, action=discord.AuditLogAction.channel_update):
                if entry.target == before:
                    executor = entry.user
                    break

            desc = f"Канал: {after.mention} ({after.name})\n" \
                   f"Изменения:\n" + "\n".join(changes)
            await self.send_log(
                title="ИЗМЕНЕНИЕ КАНАЛА",
                description=desc,
                executor=executor,
                color=discord.Color.blurple()
            )

    # Логирование создания категории
    @commands.Cog.listener()
    async def on_category_create(self, category):
        # Получаем информацию о создателе
        executor = None
        async for entry in category.guild.audit_logs(limit=1, action=discord.AuditLogAction.category_create):
            if entry.target == category:
                executor = entry.user
                break

        desc = f"Категория: {category.name}\n" \
               f"Позиция: {category.position}"
        await self.send_log(
            title="СОЗДАНА КАТЕГОРИЯ",
            description=desc,
            executor=executor,
            color=discord.Color.teal()
        )

    # Логирование удаления категории
    @commands.Cog.listener()
    async def on_category_delete(self, category):
        # Получаем информацию об удалителе
        executor = None
        async for entry in category.guild.audit_logs(limit=1, action=discord.AuditLogAction.category_delete):
            if entry.target == category:
                executor = entry.user
                break

        desc = f"Категория: {category.name}\n" \
               f"Позиция: {category.position}"
        await self.send_log(
            title="УДАЛЕНА КАТЕГОРИЯ",
            description=desc,
            executor=executor,
            color=discord.Color.dark_red()
        )

    # Логирование изменения категории
    @commands.Cog.listener()
    async def on_category_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"Название: `{before.name}` → `{after.name}`")
        if before.position != after.position:
            changes.append(f"Позиция: `{before.position}` → `{after.position}`")

        if changes:
            # Получаем информацию о том, кто изменил категорию
            executor = None
            async for entry in before.guild.audit_logs(limit=5, action=discord.AuditLogAction.category_update):
                if entry.target == before:
                    executor = entry.user
                    break

            desc = f"Категория: {after.name}\n" \
                   f"Изменения:\n" + "\n".join(changes)
            await self.send_log(
                title="ИЗМЕНЕНИЕ КАТЕГОРИИ",
                description=desc,
                executor=executor,
                color=discord.Color.gold()
            )


    # Логирование действий в голосовых каналах
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return  # Пропускаем ботов

        # Проверка на перемещение между каналами
        if before.channel and after.channel:
            if before.channel != after.channel:
                desc = (
                    f"Пользователь: {member.mention}\n"
                    f"Переместился из канала: {before.channel.name}\n"
                    f"В канал: {after.channel.name}\n"
                    f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                )
                await self.send_log(
                    title="ПЕРЕМЕЩЕНИЕ МЕЖДУ ГОЛОСОВЫМИ КАНАЛАМИ",
                    description=desc,
                    color=discord.Color.blue()
                )
                return

        # Вход в голосовой канал
        if not before.channel and after.channel:
            desc = (
                f"Пользователь: {member.mention}\n"
                f"Подключился к каналу: {after.channel.name}\n"
                f"Время подключения: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
            await self.send_log(
                title="ПОДКЛЮЧЕНИЕ К ГОЛОСОВОМУ КАНАЛУ",
                description=desc,
                color=discord.Color.green()
            )
            return

        # Выход из голосового канала
        if before.channel and not after.channel:
            desc = (
                f"Пользователь: {member.mention}\n"
                f"Покинул канал: {before.channel.name}\n"
                f"Время отключения: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
            )
            await self.send_log(
                title="ОТКЛЮЧЕНИЕ ОТ ГОЛОСОВОГО КАНАЛА",
                description=desc,
                color=discord.Color.red()
            )
            return
        
                # Проверка на подключение к AFK
        if before.channel and after.channel:
            if before.channel.id != after.channel.id:
                if after.channel.id == self.bot.get_guild(member.guild.id).afk_channel.id:
                    desc = (
                        f"Пользователь: {member.mention}\n"
                        f"Перемещен в AFK-канал\n"
                        f"Время: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                    )
                    await self.send_log(
                        title="ПЕРЕМЕЩЕНИЕ В AFK-КАНАЛ",
                        description=desc,
                        color=discord.Color.dark_grey()
                    )
# Функция для загрузки кога
async def setup(bot):
    await bot.add_cog(Logs(bot))

