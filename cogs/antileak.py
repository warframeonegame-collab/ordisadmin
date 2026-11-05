# cogs/antileak.py — Антилив v3 (risk-score engine, event-driven)

import discord
from discord.ext import commands, tasks
import logging
import time
from datetime import datetime, timedelta
from collections import defaultdict

import config
from utils.database import Database

logger = logging.getLogger(__name__)

# Права, считающиеся «опасными» при снимании ролей на уровне strip
DANGEROUS_PERMISSIONS = (
    'administrator', 'manage_guild', 'manage_roles', 'manage_channels',
    'manage_webhooks', 'manage_messages', 'manage_nicknames', 'ban_members',
    'kick_members', 'mention_everyone', 'view_audit_log',
)

ACTION_LABELS = {
    'member_ban_add': '🚫 Бан участника',
    'member_kick': '👢 Кик участника',
    'channel_delete': '🗑️ Удаление каналов',
    'channel_create': '📝 Создание каналов',
    'channel_overwrite_update': '🔓 Изменение прав каналов',
    'member_role_update': '👥 Изменение ролей участника',
    'guild_role_delete': '❌ Удаление роли',
    'guild_update': '⚙️ Изменение настроек сервера',
    'owner_transfer': '👑 Передача владельца',
    'bot_add': '🤖 Подключение бота',
    'message_bulk_delete': '🧹 Массовое удаление сообщений',
    'webhook_delete': '🪝 Удаление вебхуков',
}

LEVEL_LABELS = {
    'warn': ('🟡 Тревога', discord.Color.gold()),
    'strip': ('🟠 Снятие опасных ролей', discord.Color.orange()),
    'lockdown': ('🔴 LOCKDOWN', discord.Color.red()),
}

TRUSTED_ROLES = ('founder', 'cofounder')  # из site_roles — не триггерим на своих


class AntiLeakResolveView(discord.ui.View):
    """Кнопки Confirm/Reject прямо в Discord-алерте (для основателя)."""

    def __init__(self, cog, alert_id):
        # Не протухает 24 часа; после этого решать на сайте
        super().__init__(timeout=86400)
        self.cog = cog
        self.alert_id = alert_id

    def _is_founder(self, user) -> bool:
        roles = self.cog._get_site_roles()
        return roles.get(str(user.id)) in TRUSTED_ROLES

    async def _resolve(self, interaction: discord.Interaction, action: str):
        if not self._is_founder(interaction.user):
            await interaction.response.send_message(
                "❌ Решение может принять только основатель.", ephemeral=True)
            return
        from utils.postgres_db import db
        alert = self.cog._current_alerts.get(self.alert_id)
        self.cog._current_alerts.pop(self.alert_id, None)
        db.add_antileak_action(
            action,
            payload={'alert_id': self.alert_id, 'alert': alert},
            created_by=f"discord:{interaction.user.display_name}",
            alert_id=self.alert_id)
        await interaction.response.send_message(
            f"📤 Передано боту: `{action}` по алерту `{self.alert_id}`", ephemeral=True)
        self.stop()


    @discord.ui.button(label="Подтвердить (наказать)", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, 'confirm')

    @discord.ui.button(label="Отклонить (вернуть роли)", style=discord.ButtonStyle.secondary)
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._resolve(interaction, 'reject')

    async def on_timeout(self):
        self.stop()


class AntiLeak(commands.Cog):
    """
    Антилив v3 — защита клана от саботажа/рейда.

    • Event-driven: события Discord (ban/kick/каналы/роли/сервер/вебхуки/bulk-delete)
      обрабатываются мгновенно, Audit Log используется только для атрибуции виновника.
    • Risk-score: каждое действие имеет вес; скользящие окна 3 мин и 1 час.
    • 3 уровня эскалации: warn → strip (опасные роли) → lockdown (полная блокировка).
    • Whitelist: founder/cofounder из site_roles + config.ANTILEAK_TRUSTED_IDS.
    • Оркестрация через БД: сайт ставит confirm/reject в очередь antileak_actions,
      бот исполняет сам (никакого REST из Flask).
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

        # Риск-трекер: {user_id: [(timestamp, weight, action_type)]}
        self._risk = defaultdict(list)
        # ID недавних банов (чтобы on_member_remove не задублировал бан как кик)
        self._recent_bans = {}
        # Кулдаун алертов на пользователя: user_id -> {'ts': float, 'level': str}
        self._alert_cooldown = {}
        # Кулдаун атрибуции по типам событий (анти-race при пачке событий)
        self._last_attributed = defaultdict(float)
        # Кэш site_roles для whitelist
        self._trusted_cache = {'ids': None, 'ts': 0.0}
        # Кэш ролей сайта (для кнопок xác nhận)
        self._site_roles_cache = {'map': {}, 'ts': 0.0}
        # Алерты за текущую сессию (для кнопок в Discord)
        self._current_alerts = {}
        # Состояние lockdown (восстанавливается из БД после рестартов)
        self._lockdown_mode = False
        self._lockdown_backup = {}
        # Момент старта (grace period)
        self._started_at = time.monotonic()

        # Загружаем незавершённый lockdown после рестарта
        try:
            saved = self.db.get_antileak_state('lockdown')
            if saved and saved.get('guild_id') and saved.get('channels'):
                self._lockdown_mode = True
                self._lockdown_backup = saved.get('channels', {})
                logger.warning(f"[AntiLeak] Незавершённый lockdown восстановлен "
                               f"(затрагивает {len(self._lockdown_backup)} каналов)")
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка загрузки состояния lockdown: {e}")

        if not self.action_executor.is_running():
            self.action_executor.start()

    def cog_unload(self):
        self.action_executor.cancel()

    # ==================== WHITELIST ====================

    def _get_site_roles(self) -> dict:
        """Кэш соответствий user_id -> site_role (60 сек)."""
        now = time.monotonic()
        if now - self._site_roles_cache['ts'] > 60:
            try:
                self._site_roles_cache['map'] = {str(k): str(v) for k, v in
                                                 (self.db.get_site_roles() or {}).items()}
            except Exception as e:
                logger.debug(f"[AntiLeak] Не удалось получить site_roles: {e}")
                self._site_roles_cache['map'] = {}
            self._site_roles_cache['ts'] = now
        return self._site_roles_cache['map']

    def _get_trusted_ids(self) -> set:
        """Whitelist: сайт-роли founder/cofounder + ручной список из config."""
        now = time.monotonic()
        if self._trusted_cache['ids'] is None or now - self._trusted_cache['ts'] > 60:
            roles = self._get_site_roles()
            ids = {uid for uid, role in roles.items() if role in TRUSTED_ROLES}
            ids.update(str(i) for i in (getattr(config, 'ANTILEAK_TRUSTED_IDS', []) or []))
            self._trusted_cache['ids'] = ids
            self._trusted_cache['ts'] = now
        return self._trusted_cache['ids']

    # ==================== RISK ENGINE ====================

    def _risk_add(self, user_id, action_type, weight):
        """Добавляет действие в трекер и возвращает (score_short, score_long)."""
        now = time.time()
        self._risk[user_id].append((now, weight, action_type))
        # Чистим окна
        short_cut = now - config.ANTILEAK_WINDOW_SHORT
        long_cut = now - config.ANTILEAK_WINDOW_LONG
        fresh = [(ts, w, t) for (ts, w, t) in self._risk[user_id] if ts > long_cut]
        self._risk[user_id] = fresh
        if not fresh:
            self._risk.pop(user_id, None)
            return 0, 0
        short = sum(w for (ts, w, t) in fresh if ts > short_cut)
        long = sum(w for (ts, w, t) in fresh)
        return short, long

    def _score_to_level(self, short, long, action_type):
        """Уровень эскалации по score (max из двух окон) + критические одиночные."""
        if action_type in getattr(config, 'ANTILEAK_CRITICAL_SINGLE', ()):
            return 'lockdown'
        score = max(short, long)
        level = None
        for name, threshold in config.ANTILEAK_LEVELS:
            if score >= threshold:
                level = name
        return level

    # ==================== АТРИБУЦИЯ ЧЕРЕЗ AUDIT LOG ====================

    async def _attribute(self, guild, audit_action, max_age_sec=20, exclude_ids=()):
        """Находит автора последнего действия в Audit Log (event-driven атрибуция)."""
        try:
            async for entry in guild.audit_logs(limit=6, action=audit_action):
                if entry.created_at and \
                        (datetime.now(entry.created_at.tzinfo) - entry.created_at).total_seconds() > max_age_sec:
                    break
                if entry.user is None or entry.user.bot:
                    continue
                if entry.user.id in exclude_ids or entry.user.id == self.bot.user.id:
                    continue
                return entry
        except discord.Forbidden:
            logger.warning(f"[AntiLeak] Нет прав View Audit Log ({guild.name})")
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка атрибуции {audit_action}: {e}")
        return None

    def _attrib_rate_ok(self, key, min_gap=3):
        """Защита от повторной атрибуции одного события (пачка событий Discord)."""
        now = time.monotonic()
        if now - self._last_attributed[key] < min_gap:
            return False
        self._last_attributed[key] = now
        return True

    async def _user_of(self, guild, entry):
        """Member/User объекта автора; при отсутствии в кэше — fetch."""
        if entry and entry.user:
            try:
                if isinstance(entry.user, discord.Member):
                    return entry.user
                return await guild.fetch_member(entry.user.id)
            except Exception:
                return None
        return None

    # ==================== ДЕТЕКЦИЯ (СОБЫТИЯ DISCORD) ====================

    async def _in_grace(self):
        return time.monotonic() - self._started_at < config.ANTILEAK_GRACE_SECONDS

    def _remember_ban(self, user_id):
        self._recent_bans[user_id] = time.time()
        if len(self._recent_bans) > 200:
            cutoff = time.time() - 300
            for uid in list(self._recent_bans.keys()):
                if self._recent_bans[uid] < cutoff:
                    del self._recent_bans[uid]

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        """Бан через Discord API/меры модерации."""
        if not config.ANTILEAK_ENABLED or guild is None:
            return
        if not await self._attrib_rate_ok(f'ban:{guild.id}'):
            return
        entry = await self._attribute(guild, discord.AuditLogAction.ban)
        member = await self._user_of(guild, entry)
        if member is None or member.bot:
            return
        self._remember_ban(user.id)
        victims = []
        if entry and entry.target and hasattr(entry.target, 'id'):
            victims = [str(entry.target.id)]
        await self._process(guild, member, 'member_ban_add', victim_ids=victims,
                            target_name=str(entry.target) if entry.target else '')

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        """Кик: выход участника + свежий kick в Audit Log."""
        if not config.ANTILEAK_ENABLED:
            return
        if member.id in self._recent_bans:  # это был бан, не кик
            return
        if not self._attrib_rate_ok(f'kick:{member.guild.id}', min_gap=5):
            return
        entry = await self._attribute(member.guild, discord.AuditLogAction.kick)
        if entry is None:
            return
        # Проверяем, что речь именно об этом участнике
        if not (entry.target and getattr(entry.target, 'id', None) == member.id):
            return
        actor = await self._user_of(member.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(member.guild, actor, 'member_kick', victim_ids=[str(member.id)],
                            target_name=member.display_name)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not config.ANTILEAK_ENABLED:
            return
        if not self._attrib_rate_ok(f'chdel:{channel.guild.id}'):
            return
        entry = await self._attribute(channel.guild, discord.AuditLogAction.channel_delete)
        actor = await self._user_of(channel.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(channel.guild, actor, 'channel_delete',
                            target_name=channel.name, target_id=str(channel.id))

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not config.ANTILEAK_ENABLED:
            return
        if not self._attrib_rate_ok(f'chcreate:{channel.guild.id}'):
            return
        entry = await self._attribute(channel.guild, discord.AuditLogAction.channel_create)
        actor = await self._user_of(channel.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(channel.guild, actor, 'channel_create',
                            target_name=channel.name, target_id=str(channel.id))

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Подключение бота — критическое событие (CRITICAL_SINGLE)."""
        if not config.ANTILEAK_ENABLED:
            return
        if not member.bot:
            return
        if not self._attrib_rate_ok(f'botadd:{member.guild.id}'):
            return
        entry = await self._attribute(member.guild, discord.AuditLogAction.bot_add)
        actor = await self._user_of(member.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(member.guild, actor, 'bot_add',
                            target_name=member.name, target_id=str(member.id))

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        """Отслеживаем только изменение ПРАВ канала (overwrites)."""
        if not config.ANTILEAK_ENABLED or before.overwrites == after.overwrites:
            return
        if not self._attrib_rate_ok(f'chmod:{after.guild.id}', min_gap=5):
            return
        entry = await self._attribute(after.guild, discord.AuditLogAction.channel_update)
        actor = await self._user_of(after.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(after.guild, actor, 'channel_overwrite_update',
                            target_name=after.name, target_id=str(after.id))

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if not config.ANTILEAK_ENABLED:
            return
        if not self._attrib_rate_ok(f'roldel:{role.guild.id}'):
            return
        entry = await self._attribute(role.guild, discord.AuditLogAction.role_delete)
        actor = await self._user_of(role.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(role.guild, actor, 'guild_role_delete',
                            target_name=role.name, target_id=str(role.id))

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        """Изменение ролей участника (добавление/снятие ролей модератором)."""
        if not config.ANTILEAK_ENABLED:
            return
        if before.roles == after.roles:
            return
        if not self._attrib_rate_ok(f'memupd:{after.guild.id}', min_gap=5):
            return
        entry = await self._attribute(after.guild, discord.AuditLogAction.member_role_update)
        actor = await self._user_of(after.guild, entry)
        if actor is None or actor.bot:
            return
        added = [r.name for r in after.roles if r not in before.roles]
        removed = [r.name for r in before.roles if r not in after.roles]
        await self._process(after.guild, actor, 'member_role_update',
                            target_name=after.display_name, target_id=str(after.id),
                            extra={'roles_added': added, 'roles_removed': removed})

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        if not config.ANTILEAK_ENABLED:
            return
        if before.owner_id != after.owner_id:
            if not self._attrib_rate_ok(f'owner:{after.id}'):
                return
            entry = await self._attribute(after, discord.AuditLogAction.guild_update)
            actor = await self._user_of(after, entry)
            if actor is None or actor.bot:
                return
            await self._process(after, actor, 'owner_transfer',
                                extra={'old_owner_id': str(before.owner_id),
                                       'new_owner_id': str(after.owner_id)})
        elif before.name != after.name or before.icon != after.icon:
            if not self._attrib_rate_ok(f'guildupd:{after.id}'):
                return
            entry = await self._attribute(after, discord.AuditLogAction.guild_update)
            actor = await self._user_of(after, entry)
            if actor is None or actor.bot:
                return
            changes = {}
            if before.name != after.name:
                changes['name'] = {'old': before.name, 'new': after.name}
            if before.icon != after.icon:
                changes['icon'] = {'old': 'иконка изменена', 'new': ''}
            await self._process(after, actor, 'guild_update', extra={'guild_changes': changes})

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        """Удаление вебхуков — лазейка для сливов через интеграции (создание игнорируем)."""
        if not config.ANTILEAK_ENABLED:
            return
        if not self._attrib_rate_ok(f'webhook:{channel.guild.id}', min_gap=5):
            return
        entry = await self._attribute(channel.guild, discord.AuditLogAction.webhook_delete)
        if entry is None:
            return
        actor = await self._user_of(channel.guild, entry)
        if actor is None or actor.bot:
            return
        await self._process(channel.guild, actor, 'webhook_delete',
                            target_name=channel.name, target_id=str(channel.id))

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        """Массовое удаление сообщений (очистка следов рейда)."""
        if not config.ANTILEAK_ENABLED or payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None or not self._attrib_rate_ok(f'bulkdel:{payload.guild_id}'):
            return
        entry = await self._attribute(guild, discord.AuditLogAction.message_bulk_delete)
        actor = await self._user_of(guild, entry)
        if actor is None or actor.bot:
            return
        msg_count = len(payload.message_ids or ())
        await self._process(guild, actor, 'message_bulk_delete',
                            extra={'message_count': msg_count})

    # ==================== ОБРАБОТКА / ЭСКАЛАЦИЯ ====================

    @staticmethod
    def _dangerous_roles(member: discord.Member):
        """Роли участника с опасными правами (tier-роли + manage-права)."""
        result = []
        for role in member.roles:
            if role == member.guild.default_role:
                continue
            if any(getattr(role.permissions, p, False) for p in DANGEROUS_PERMISSIONS):
                result.append(role)
        return result

    async def _process(self, guild, actor, action_type, victim_ids=None,
                       target_name='', target_id='', extra=None):
        """Главный пайплайн: score → уровень эскалации → реакция."""
        user_id = str(actor.id)

        # Белый список: своих не трогаем
        if user_id in self._get_trusted_ids():
            logger.debug(f"[AntiLeak] {action_type} от доверенного {actor} — игнор")
            return

        weight = config.ANTILEAK_WEIGHTS.get(action_type, 10)
        short, long = self._risk_add(user_id, action_type, weight)
        level = self._score_to_level(short, long, action_type)

        in_grace = await self._in_grace()
        if in_grace:
            logger.info(
                f"[AntiLeak] GRACE: {actor} — {action_type}, score={short}/{long}, "
                f"уровень={level or '—'}. Только лог (grace {config.ANTILEAK_GRACE_SECONDS}с)")
            return
        if level is None:
            logger.debug(f"[AntiLeak] {actor} — {action_type} (score {short}/{long}) ниже порога")
            return

        # Кулдаун алертов (эскалация на более высокий уровень его обходит)
        level_index = next((i for i, (n, _) in enumerate(config.ANTILEAK_LEVELS) if n == level), 0)
        cd = self._alert_cooldown.get(user_id)
        now = time.monotonic()
        prev_level = (cd or {}).get('level')
        prev_ts = (cd or {}).get('ts', 0)
        prev_index = next((i for i, (n, _) in enumerate(config.ANTILEAK_LEVELS) if n == prev_level), -1)
        within_cooldown = (cd is not None and now - prev_ts < config.ANTILEAK_ALERT_COOLDOWN)
        escalation = level_index > prev_index

        if within_cooldown and not (config.ANTILEAK_ESCALATION_BYPASS and escalation):
            logger.info(f"[AntiLeak] Кулдаун алерта {actor} ({level}) — пропускаю")
            return
        if within_cooldown and not escalation:
            # Тот же уровень в кулдауне — дедупликация
            return

        score = max(short, long)
        logger.warning(f"[AntiLeak] 🚨 ЭСКАЛАЦИЯ {level.upper()} — {actor} ({action_type}), "
                       f"score={round(score)}, action {action_type}")

        # Реакции по уровню
        saved_roles = []
        if level == 'warn':
            pass  # только уведомление
        elif level == 'strip':
            saved_roles = await self._strip_dangerous_roles(guild, actor)
        elif level == 'lockdown':
            saved_roles = await self._strip_all_roles(guild, actor)
            if not self._lockdown_mode:
                await self._lockdown(guild)

        # Собираем жертв для банов/киков
        if victim_ids is None and action_type in ('member_ban_add', 'member_kick'):
            victim_ids = await self._collect_recent_victims(guild, actor, action_type)

        details = {
            'action_type': action_type,
            'target': target_name,
            'target_id': target_id,
            'score': round(score),
            'short_window': round(short),
            'long_window': round(long),
        }
        if extra:
            details.update(extra)

        create_alert = escalation or cd is None
        alert_id = None
        if create_alert:
            alert_id = datetime.utcnow().strftime('%Y%m%d%H%M%S') + str(actor.id)[-4:]
            alert_data = {
                'id': alert_id,
                'user_id': user_id,
                'username': actor.display_name,
                'user_avatar': str(actor.display_avatar.url) if actor.display_avatar else '',
                'action_type': action_type,
                'action_count': len(self._risk.get(user_id, [])),
                'threshold': dict((n, t) for n, t in config.ANTILEAK_LEVELS)[level],
                'details': details,
                'saved_roles': saved_roles,
                'victim_ids': victim_ids or [],
                'timestamp': datetime.utcnow().isoformat(),
                'status': 'pending',
                'guild_id': str(guild.id),
                'response_level': level,
                'score': int(score),
            }
            try:
                self.db.add_antileak_alert(alert_data)
            except Exception as e:
                logger.error(f"[AntiLeak] Ошибка сохранения алерта: {e}")

            self._alert_cooldown[user_id] = {'ts': now, 'level': level}
            self._current_alerts[alert_id] = alert_data
            if len(self._current_alerts) > 50:
                for k in list(self._current_alerts.keys())[:-25]:
                    self._current_alerts.pop(k, None)

        # Уведомления
        await self._send_discord_alert(guild, actor, action_type, level, score,
                                       victim_ids or [], details, alert_id)
        await self._notify_actor(guild, actor, action_type, level, score)

    # ==================== РЕАКЦИИ ====================

    async def _strip_dangerous_roles(self, guild, actor):
        """Снимает только опасные роли (manage/админ/ tier). Возвращает снятые ID."""
        roles = self._dangerous_roles(actor)
        if not roles:
            logger.info(f"[AntiLeak] У {actor} нет опасных ролей — снимать нечего (strip)")
            return []
        try:
            await actor.remove_roles(*roles, reason="🛡️ Антилив v3: снятие опасных ролей (strip)")
            logger.warning(f"[AntiLeak] Снято {len(roles)} опасных ролей с {actor}")
            return [r.id for r in roles]
        except discord.Forbidden:
            logger.error(f"[AntiLeak] Нет прав снять опасные роли с {actor}")
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка снятия опасных ролей: {e}")
        return []

    async def _strip_all_roles(self, guild, actor):
        """Снимает ВСЕ роли (кроме @everyone). Возвращает ID для восстановления."""
        saved = [r.id for r in actor.roles if r != guild.default_role]
        to_remove = [r for r in (guild.get_role(rid) for rid in saved) if r is not None]
        if not to_remove:
            return saved
        try:
            await actor.remove_roles(*to_remove, reason="🛡️ Антилив v3: LOCKDOWN, снятие ролей")
            return saved
        except discord.Forbidden:
            logger.error(f"[AntiLeak] Нет прав снять все роли с {actor}")
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка снятия ролей: {e}")
        return saved

    async def _collect_recent_victims(self, guild, actor, action_type):
        """Жертвы из audit log за последние минуты (ban+kbick generic)."""
        audit_action = (discord.AuditLogAction.ban if action_type == 'member_ban_add'
                        else discord.AuditLogAction.kick)
        victims = []
        try:
            cutoff = discord.utils.utcnow() - timedelta(minutes=10)
            async for entry in guild.audit_logs(limit=50, action=audit_action):
                if entry.created_at < cutoff:
                    break
                if entry.user and entry.user.id == actor.id:
                    if entry.target and hasattr(entry.target, 'id'):
                        victims.append(str(entry.target.id))
        except Exception as e:
            logger.debug(f"[AntiLeak] Не удалось собрать жертв: {e}")
        return victims

    # ==================== LOCKDOWN ====================

    async def _lockdown(self, guild):
        """Режим блокировки: @everyone теряет отправку сообщений; slowmode 3600."""
        backup = {}
        try:
            everyone = guild.default_role
            for channel in guild.channels:
                try:
                    overwrites = channel.overwrites_for(everyone)
                    # Сохраняем исходное состояние прав @everyone
                    backup[channel.id] = {
                        'overwrite_raw': {str(k): v for k, v in overwrites._values.items()}
                        if hasattr(overwrites, '_values') else {},
                        'complete': overwrites.is_complete(),
                    }
                    perms = channel.permissions_for(guild.me)
                    if perms.manage_channels:
                        overwrite = channel.overwrites_for(everyone)
                        overwrite.send_messages = False
                        overwrite.add_reactions = False
                        overwrite.send_messages_in_threads = False
                        await channel.set_permissions(everyone, overwrite=overwrite,
                                                      reason="🛡️ Антилив v3: LOCKDOWN")
                        if isinstance(channel, discord.TextChannel) and perms.manage_channels:
                            backup[channel.id]['slowmode'] = channel.slowmode_delay
                            await channel.edit(slowmode_delay=3600, reason="🛡️ Антилив LOCKDOWN")
                except Exception as e:
                    logger.debug(f"[AntiLeak] Lockdown: канал {channel.name}: {e}")
            self._lockdown_backup = backup
            self._lockdown_mode = True
            self.db.set_antileak_state('lockdown', {
                'guild_id': str(guild.id), 'channels': backup,
                'locked_at': datetime.utcnow().isoformat(),
            })
            logger.warning(f"[AntiLeak] 🔴 LOCKDOWN включён ({len(backup)} каналов)")
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка lockdown: {e}")

    async def _unlock(self, guild):
        """Снимает lockdown и восстанавливает исходные права."""
        backup = self._lockdown_backup
        try:
            everyone = guild.default_role
            restored = 0
            for channel in guild.channels:
                info = backup.get(channel.id)
                if not info:
                    continue
                try:
                    overwrite = channel.overwrites_for(everyone)
                    overwrite.send_messages = None
                    overwrite.add_reactions = None
                    overwrite.send_messages_in_threads = None
                    await channel.set_permissions(everyone, overwrite=overwrite,
                                                  reason="🛡️ Антилив: снятие LOCKDOWN")
                    if 'slowmode' in info and isinstance(channel, discord.TextChannel):
                        await channel.edit(slowmode_delay=info['slowmode'])
                    restored += 1
                except Exception as e:
                    logger.debug(f"[AntiLeak] Unlock: канал {channel.name}: {e}")
            self._lockdown_mode = False
            self._lockdown_backup = {}
            self.db.set_antileak_state('lockdown', {})
            logger.warning(f"[AntiLeak] 🟢 LOCKDOWN снят (восстановлено {restored} каналов)")
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка unlock: {e}")

    # ==================== ОЧЕРЕДЬ ДЕЙСТВИЙ (бот ← сайт) ====================

    @tasks.loop(seconds=8)
    async def action_executor(self):
        """Бот исполняет решения сайта (confirm/reject) и ручные команды."""
        try:
            actions = self.db.get_pending_antileak_actions()
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка чтения очереди: {e}")
            return
        for act in actions:
            try:
                ok = await self._execute_action(act)
                self.db.mark_antileak_action_done(act['id'], success=ok)
            except Exception as e:
                logger.error(f"[AntiLeak] Ошибка исполнения действия #{act.get('id')}: {e}")
                self.db.mark_antileak_action_done(act['id'], success=False)

    async def _execute_action(self, act):
        """Исполнение одного действия из очереди: confirm / reject / lockdown / unlock."""
        action = act.get('action')
        payload = act.get('payload') or {}
        alert = payload.get('alert') or {}
        guild = self.bot.get_guild(int(config.GUILD_ID)) if config.GUILD_ID else None
        user_id = alert.get('user_id')

        if action == 'reject':
            # Ложное срабатывание: вернуть роли + снять lockdown
            if guild and user_id:
                member = guild.get_member(int(user_id))
                if member:
                    saved_role_ids = alert.get('saved_roles')
                    if saved_role_ids is None:
                        # Fallback: берём данные алерта из БД
                        try:
                            db_alert = self.db.get_antileak_alert(act.get('alert_id'))
                            saved_role_ids = (db_alert or {}).get('saved_roles') or []
                        except Exception:
                            saved_role_ids = []
                    saved = [guild.get_role(r) for r in (saved_role_ids or [])]
                    saved = [r for r in saved if r is not None]
                    if saved:
                        try:
                            await member.add_roles(*saved, reason="🛡️ Антилив: алерт отклонён, роли восстановлены")
                        except Exception as e:
                            logger.error(f"[AntiLeak] Восстановление ролей {member}: {e}")
                    else:
                        logger.debug(f"[AntiLeak] Нечего восстанавливать для {member}")
                    try:
                        await member.send("✅ Режим Антилива: алерт отклонён, ваши роли возвращены.")
                    except Exception:
                        pass
            if self._lockdown_mode and guild:
                await self._unlock(guild)
            return True

        if action == 'confirm':
            # Подтверждённый саботаж: бан виновника + откат жертв
            if guild and user_id:
                member = guild.get_member(int(user_id))
                try:
                    if member:
                        await member.ban(reason=f"🛡️ Антилив: подтверждённый саботаж "
                                                f"(решение: {act.get('created_by')})")
                    else:
                        await guild.ban(discord.Object(id=int(user_id)),
                                        reason="🛡️ Антилив: подтверждённый саботаж")
                except Exception as e:
                    logger.error(f"[AntiLeak] Бан виновника {user_id}: {e}")
            # Откат жертв: unban забаненных + инвайт в ЛС кикнутым
            victim_ids = alert.get('victim_ids')
            if victim_ids is None:
                try:
                    db_alert = self.db.get_antileak_alert(act.get('alert_id'))
                    victim_ids = (db_alert or {}).get('victim_ids') or []
                except Exception:
                    victim_ids = []
            for vid in (victim_ids or []):
                try:
                    await guild.unban(discord.Object(id=int(vid)), reason="🛡️ Антилив: откат банов жертв")
                except Exception:
                    pass
            await self._dm_recovery_to_victims(guild, victim_ids or [])
            if self._lockdown_mode and guild:
                await self._unlock(guild)
            return True

        if action == 'lockdown' and guild:
            if not self._lockdown_mode:
                await self._lockdown(guild)
            return True

        if action == 'unlock' and guild:
            if self._lockdown_mode:
                await self._unlock(guild)
            return True

        logger.warning(f"[AntiLeak] Неизвестное действие в очереди: {action}")
        return False

    async def _dm_recovery_to_victims(self, guild, victim_ids):
        """Создаёт одноразовый инвайт и приглашает кикнутых жертв вернуться."""
        try:
            channel = discord.utils.get(guild.text_channels, name='основной') or guild.system_channel \
                      or (guild.text_channels[0] if guild.text_channels else None)
            if channel is None:
                return
            invite = await channel.create_invite(max_uses=len(victim_ids) or 1,
                                                 max_age=86400, unique=True,
                                                 reason="🛡️ Антилив: возвращение жертв")
        except Exception as e:
            logger.debug(f"[AntiLeak] Не удалось создать инвайт для жертв: {e}")
            return
        for vid in victim_ids:
            try:
                user = await self.bot.fetch_user(int(vid))
                await user.send(
                    "🔄 Это была ошибка или результат атаки на клан — вас восстановили.\n"
                    f"Вернуться в клан: {invite.url}")
            except Exception:
                pass

    # ==================== УВЕДОМЛЕНИЯ ====================

    async def _send_discord_alert(self, guild, actor, action_type, level, score,
                                  victim_ids, details, alert_id=None):
        """Rich-embed уведомление в лог-канал (+ кнопки Confirm/Reject для нового алерта)."""
        try:
            log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
            if not log_channel:
                return
            response_label, response_color = LEVEL_LABELS[level]
            action_label = ACTION_LABELS.get(action_type, action_type)

            status_map = {
                'warn': '🟡 Только уведомление',
                'strip': '🟠 Опасные роли сняты',
                'lockdown': '🔴 ВСЕ РОЛИ СНЯТЫ + LOCKDOWN',
            }
            lines = [
                f"Уровень: **{response_label}**",
                f"Реакция: {status_map[level]}",
                "",
                f"Score: **{int(score)}** (3 мин / 1 ч окна)",
            ]
            if victim_ids:
                lines.append(f"Жертвы: {len(victim_ids)} шт.")
            embed = discord.Embed(
                title=f"🛡️ АНТИЛИВ v3 — {response_label}",
                description="\n".join(lines),
                color=response_color,
                timestamp=datetime.utcnow(),
            )
            embed.add_field(name="Кто", value=f"<@{actor.id}> (`{actor.id}`)", inline=True)
            embed.add_field(name="Действие", value=action_label, inline=True)
            extra = []
            if details.get('target'):
                extra.append(f"цель: {details['target']}")
            if details.get('message_count'):
                extra.append(f"сообщений: {details['message_count']}")
            if details.get('old_owner_id'):
                extra.append(f"владелец: {details['old_owner_id']} → {details['new_owner_id']}")
            if extra:
                embed.add_field(name="Детали", value=('\n'.join(extra))[:1024], inline=False)
            if self._lockdown_mode:
                embed.add_field(name="🔒 LOCKDOWN", value="Включён: каналы заблокированы, slowmode 1ч", inline=False)
            embed.set_footer(text="Антилив v3 • решайте кнопками ниже или на сайте")

            view = None
            if alert_id:
                view = AntiLeakResolveView(self, alert_id)
            await log_channel.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"[AntiLeak] Ошибка отправки Discord-алерта: {e}")

    async def _notify_actor(self, guild, actor, action_type, level, score):
        """ЛС нарушителю с описанием уровня и что делать."""
        response_label, _ = LEVEL_LABELS[level]
        action_label = ACTION_LABELS.get(action_type, action_type)
        consequences = {
            'warn': "Пока ваши роли не тронуты, но активности за вами следят.",
            'strip': "С вас сняты роли с правами управления до проверки основателем.",
            'lockdown': "ВСЕ ваши роли сняты, сервер заблокирован. Основатель проверит это.",
        }
        embed = discord.Embed(
            title=f"🛡️ Антилив — {response_label}",
            description=(
                f"Ваше действие **{action_label}** было замечено системой защиты клана.\n\n"
                f"{consequences[level]}"
            ),
            color=LEVEL_LABELS[level][1],
            timestamp=datetime.utcnow(),
        )
        embed.set_footer(text="Если это ошибка — свяжитесь с администрацией клана")
        try:
            await actor.send(embed=embed)
        except discord.Forbidden:
            logger.debug(f"[AntiLeak] ЛС закрыты у {actor}")
        except Exception as e:
            logger.debug(f"[AntiLeak] Ошибка ЛС нарушителю: {e}")

    # ==================== РУЧНЫЕ КОМАНДЫ ====================

    @commands.hybrid_command(name='panic', description='АВАРИЙНЫЙ рубильник: ручной lockdown сервера')
    @commands.has_permissions(manage_guild=True)
    async def panic(self, ctx, reason: str = "Ручная активация основателем"):
        if self._lockdown_mode:
            await ctx.send("⚠️ Lockdown уже активен. Используйте `.unlock`.", ephemeral=True)
            return
        self.db.add_antileak_alert({
            'id': datetime.utcnow().strftime('%Y%m%d%H%M%S') + 'panic',
            'user_id': str(ctx.author.id), 'username': ctx.author.display_name,
            'user_avatar': '', 'action_type': 'manual_lockdown',
            'details': {'reason': reason}, 'saved_roles': [], 'victim_ids': [],
            'guild_id': str(ctx.guild.id), 'response_level': 'lockdown', 'score': 999,
        })
        await self._lockdown(ctx.guild)
        await ctx.send("🔴 **LOCKDOWN включён вручную.** Каналы заблокированы. `.unlock` — снять.", ephemeral=False)

    @commands.hybrid_command(name='unlock', description='Снять lockdown и восстановить права каналов')
    @commands.has_permissions(manage_guild=True)
    async def unlock(self, ctx):
        if not self._lockdown_mode:
            await ctx.send("✅ Lockdown не активен.", ephemeral=True)
            return
        await self._unlock(ctx.guild)
        await ctx.send("🟢 **LOCKDOWN снят.** Права каналов восстановлены.", ephemeral=False)

    @commands.hybrid_command(name='antileakstatus', description='Статус системы Антилив')
    async def antileakstatus(self, ctx):
        if not await self._in_grace():
            grace_left = 0
        else:
            grace_left = int(config.ANTILEAK_GRACE_SECONDS - (time.monotonic() - self._started_at))
        risk_lines = []
        for uid, entries in list(self._risk.items())[:10]:
            risk_lines.append(f"<@{uid}>: score {sum(w for _, w, _ in entries)} ({len(entries)} действ.)")
        if not risk_lines:
            risk_lines = ["—"]
        embed = discord.Embed(
            title="🛡️ Антилив v3 — статус",
            color=discord.Color.orange() if self._lockdown_mode else discord.Color.green(),
        )
        embed.add_field(name="Режим", value="🔴 LOCKDOWN активен" if self._lockdown_mode else "🟢 Обычный", inline=True)
        embed.add_field(name="Grace period", value=f"{grace_left} сек" if grace_left > 0 else "Завершён", inline=True)
        embed.add_field(name="Отслеживается", value=f"{len(self._risk)} участников", inline=True)
        embed.add_field(name="Активные окна риска (кратко)",
                        value="\n".join(risk_lines)[:1024], inline=False)
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(name='antileaktest',
                             description='Тестовое событие антислива (синтетика, без последствий)')
    @commands.has_permissions(manage_guild=True)
    async def antileaktest(self, ctx, action_type: str = 'member_ban_add'):
        """Показывает, как система оценит событие, НЕ создавая реальных последствий."""
        if action_type not in AUDIT_TEST_TYPES:
            allowed = ', '.join(AUDIT_TEST_TYPES)
            await ctx.send(f"❌ Неизвестный тип. Доступны: `{allowed}`", ephemeral=True)
            return
        weight = config.ANTILEAK_WEIGHTS.get(action_type, 10)
        # Чистая симуляция: трекер риска НЕ мутируем (вес 0 в реальный трекер не пишем)
        current_entries = self._risk.get(str(ctx.author.id), [])
        sim_short = weight  # как если бы это было единственное действие
        sim_long = sum(w for _, w, _ in current_entries) + weight
        level = self._score_to_level(sim_short, sim_long, action_type)
        label = LEVEL_LABELS[level][0] if level else "ниже порога (без реакции)"
        await ctx.send(
            f"🧪 **Симуляция** `{action_type}` (вес {weight}):\n"
            f"• Если бы это было единственное действие: score {sim_short} → {label}\n"
            f"• Ваш текущий score за час: {sim_long} (реальные действия с весом)\n"
            f"⚠️ Тест ничего не сделал — это только расчёт.", ephemeral=True)


AUDIT_TEST_TYPES = tuple(config.ANTILEAK_WEIGHTS.keys())


async def setup(bot):
    await bot.add_cog(AntiLeak(bot))
