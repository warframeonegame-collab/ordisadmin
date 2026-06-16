import discord
from discord.ext import commands, tasks
import json
import os
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import sys

# Добавляем корень проекта в путь для импорта config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import config


class AntiLeak(commands.Cog):
    """
    Система защиты от саботажа ("слива") Discord сервера.
    Отслеживает массовые деструктивные действия через Audit Log
    и автоматически снимает роли с нарушителя.
    """

    # Типы действий из Discord Audit Log
    AUDIT_ACTIONS = {
        'member_ban_add': discord.AuditLogAction.ban,
        'member_kick': discord.AuditLogAction.kick,
        'channel_delete': discord.AuditLogAction.channel_delete,
        'channel_create': discord.AuditLogAction.channel_create,
        'channel_overwrite_update': discord.AuditLogAction.channel_update,
        'member_role_update': discord.AuditLogAction.member_role_update,
        'guild_update': discord.AuditLogAction.guild_update,
        'bot_add': discord.AuditLogAction.bot_add,
    }

    def __init__(self, bot):
        self.bot = bot
        self.alerts_file = os.path.join(config.DATA_DIR, 'antileak_alerts.json')
        self._ensure_alerts_file()

        # Счётчик действий: {user_id: {action_type: [timestamps]}}
        self.action_tracker = defaultdict(lambda: defaultdict(list))

        # Последний обработанный ID записи audit log
        self._last_audit_entry_id = None

        # Запускаем polling
        if not self.audit_log_polling.is_running():
            self.audit_log_polling.start()

    def cog_unload(self):
        self.audit_log_polling.cancel()

    def _ensure_alerts_file(self):
        """Создаёт файл алертов, если его нет."""
        os.makedirs(os.path.dirname(self.alerts_file), exist_ok=True)
        if not os.path.exists(self.alerts_file):
            with open(self.alerts_file, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)

    # ==================== ЗАГРУЗКА/СОХРАНЕНИЕ АЛЕРТОВ ====================

    def _load_alerts(self):
        """Загружает алерты из файла."""
        try:
            with open(self.alerts_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def _save_alerts(self, alerts):
        """Сохраняет алерты в файл."""
        os.makedirs(os.path.dirname(self.alerts_file), exist_ok=True)
        with open(self.alerts_file, 'w', encoding='utf-8') as f:
            json.dump(alerts, f, ensure_ascii=False, indent=2)

    def _add_alert(self, alert_data):
        """Добавляет новый алерт."""
        alerts = self._load_alerts()
        alerts.insert(0, alert_data)  # Новые сверху
        self._save_alerts(alerts)

    # ==================== ОЧИСТКА ТРЕКЕРА ====================

    def _clean_tracker(self):
        """Удаляет записи старше окна мониторинга."""
        now = datetime.utcnow()
        window = timedelta(seconds=config.ANTILEAK_WINDOW)
        for user_id in list(self.action_tracker.keys()):
            for action_type in list(self.action_tracker[user_id].keys()):
                timestamps = self.action_tracker[user_id][action_type]
                self.action_tracker[user_id][action_type] = [
                    t for t in timestamps if now - t < window
                ]
                if not self.action_tracker[user_id][action_type]:
                    del self.action_tracker[user_id][action_type]
            if not self.action_tracker[user_id]:
                del self.action_tracker[user_id]

    # ==================== ПОРОГОВЫЕ ЗНАЧЕНИЯ ====================

    def _get_threshold(self, action_type):
        """Возвращает порог для типа действия."""
        thresholds = {
            'member_ban_add': config.ANTILEAK_BAN_THRESHOLD,
            'member_kick': config.ANTILEAK_KICK_THRESHOLD,
            'channel_delete': config.ANTILEAK_CHANNEL_DELETE_THRESHOLD,
            'channel_create': config.ANTILEAK_CHANNEL_CREATE_THRESHOLD,
            'channel_overwrite_update': config.ANTILEAK_PERMISSION_THRESHOLD,
            'member_role_update': config.ANTILEAK_ROLE_THRESHOLD,
            'guild_update': config.ANTILEAK_GUILD_CHANGE_THRESHOLD,
            'bot_add': config.ANTILEAK_BOT_ADD,
        }
        return thresholds.get(action_type, 999)

    # ==================== POLLING AUDIT LOG ====================

    @tasks.loop(seconds=5)
    async def audit_log_polling(self):
        """Периодически проверяет Audit Log на подозрительные действия."""
        try:
            for guild in self.bot.guilds:
                await self._check_guild_audit_log(guild)
        except Exception as e:
            logging.error(f"[AntiLeak] Ошибка polling: {e}")

    @audit_log_polling.before_loop
    async def before_polling(self):
        await self.bot.wait_until_ready()

    async def _check_guild_audit_log(self, guild):
        """Проверяет последние записи Audit Log гильдии."""
        try:
            # Получаем последние записи (ограничиваем чтобы не спамить API)
            entry_count = 0
            max_entries = 20  # Проверяем последние 20 записей

            async for entry in guild.audit_logs(limit=max_entries):
                # Пропускает уже обработанные записи
                if self._last_audit_entry_id and entry.id <= self._last_audit_entry_id:
                    break

                entry_count += 1

                # Пропускает записи от бота
                if entry.user and entry.user.bot:
                    continue

                # Пропускает записи от самого бота
                if entry.user and entry.user.id == self.bot.user.id:
                    continue

                # Определяем тип действия
                action_type = self._classify_action(entry)
                if action_type:
                    await self._process_action(guild, entry, action_type)

                # Запоминаем ID последней обработанной записи
                if self._last_audit_entry_id is None or entry.id > self._last_audit_entry_id:
                    self._last_audit_entry_id = entry.id

            # Если это первый запуск — просто запоминаем текущую позицию
            if self._last_audit_entry_id is None:
                async for entry in guild.audit_logs(limit=1):
                    self._last_audit_entry_id = entry.id

        except discord.Forbidden:
            logging.warning(f"[AntiLeak] Нет прав для чтения Audit Log в {guild.name}")
        except Exception as e:
            logging.error(f"[AntiLeak] Ошибка проверки Audit Log для {guild.name}: {e}")

    def _classify_action(self, entry):
        """Определяет тип действия из записи Audit Log."""
        action_map = {
            discord.AuditLogAction.ban: 'member_ban_add',
            discord.AuditLogAction.kick: 'member_kick',
            discord.AuditLogAction.channel_delete: 'channel_delete',
            discord.AuditLogAction.channel_create: 'channel_create',
            discord.AuditLogAction.channel_update: 'channel_overwrite_update',
            discord.AuditLogAction.member_role_update: 'member_role_update',
            discord.AuditLogAction.guild_update: 'guild_update',
            discord.AuditLogAction.bot_add: 'bot_add',
        }
        return action_map.get(entry.action)

    # ==================== ОБРАБОТКА ДЕЙСТВИЙ ====================

    async def _process_action(self, guild, entry, action_type):
        """Обрабатывает действие и проверяет пороги."""
        user = entry.user
        if not user:
            return

        user_id = str(user.id)
        now = datetime.utcnow()

        # Записываем действие в трекер
        self.action_tracker[user_id][action_type].append(now)

        # Очищаем старые записи
        self._clean_tracker()

        # Проверяем порог
        threshold = self._get_threshold(action_type)
        count = len(self.action_tracker[user_id][action_type])

        # Особые случаи: изменение сервера, передача владельца, добавление бота
        is_critical_single = action_type in ('guild_update', 'bot_add')

        # Проверяем передачу владельца
        if action_type == 'guild_update' and entry.changes:
            if hasattr(entry.changes, 'owner_id') and entry.changes.owner_id:
                old_owner, new_owner = entry.changes.owner_id
                if old_owner and new_owner and old_owner != new_owner:
                    action_type = 'owner_transfer'
                    is_critical_single = True

        # Проверяем добавление бота с правами
        if action_type == 'bot_add':
            is_critical_single = True

        triggered = False
        if is_critical_single and count >= 1:
            triggered = True
        elif count >= threshold:
            triggered = True

        if triggered:
            # Собираем информацию
            details = self._collect_details(entry, action_type, guild)
            details['action_count'] = count
            details['threshold'] = threshold

            # Запускаем защиту
            await self._trigger_protection(guild, user, action_type, details)

    def _collect_details(self, entry, action_type, guild):
        """Собирает подробную информацию о действии."""
        details = {
            'action_type': action_type,
            'user_id': str(entry.user.id),
            'username': entry.user.display_name if entry.user else 'Unknown',
            'user_avatar': str(entry.user.avatar.url) if entry.user and entry.user.avatar else '',
            'timestamp': datetime.utcnow().isoformat(),
            'target': '',
            'target_id': '',
        }

        # Информация о цели действия
        if entry.target:
            if hasattr(entry.target, 'name'):
                details['target'] = entry.target.name
            if hasattr(entry.target, 'id'):
                details['target_id'] = str(entry.target.id)

        # Дополнительные детали по типу
        if action_type == 'member_ban_add':
            details['victim'] = details['target']
            details['victim_id'] = details['target_id']

        elif action_type == 'member_kick':
            details['victim'] = details['target']
            details['victim_id'] = details['target_id']

        elif action_type == 'channel_delete':
            details['channel_name'] = details['target']
            details['channel_id'] = details['target_id']

        elif action_type == 'channel_create':
            details['channel_name'] = details['target']
            details['channel_id'] = details['target_id']

        elif action_type == 'member_role_update':
            if entry.changes and hasattr(entry.changes, 'roles'):
                added = [r.name for r in entry.changes.after.roles if r not in entry.changes.before.roles]
                removed = [r.name for r in entry.changes.before.roles if r not in entry.changes.after.roles]
                details['roles_added'] = added
                details['roles_removed'] = removed
                details['target'] = entry.target.name if entry.target else ''
                details['target_id'] = str(entry.target.id) if entry.target else ''

        elif action_type == 'guild_update':
            if entry.changes:
                changes = {}
                for attr in ['name', 'icon', 'owner_id']:
                    if hasattr(entry.changes, attr):
                        val = getattr(entry.changes, attr)
                        if val:
                            if isinstance(val, tuple) and len(val) == 2:
                                changes[attr] = {'old': str(val[0]), 'new': str(val[1])}
                            else:
                                changes[attr] = str(val)
                details['guild_changes'] = changes

        elif action_type == 'owner_transfer':
            if entry.changes and hasattr(entry.changes, 'owner_id'):
                old_owner, new_owner = entry.changes.owner_id
                details['old_owner_id'] = str(old_owner) if old_owner else ''
                details['new_owner_id'] = str(new_owner) if new_owner else ''

        elif action_type == 'bot_add':
            details['bot_name'] = details['target']
            details['bot_id'] = details['target_id']

        return details

    # ==================== ТРИГГЕР ЗАЩИТЫ ====================

    async def _trigger_protection(self, guild, user, action_type, details):
        """Запускает защитные действия при обнаружении подозрительной активности."""
        logging.warning(
            f"[AntiLeak] 🚨 ТРИГГЕР! Пользователь {user.display_name} ({user.id}) — "
            f"действие: {action_type}, кол-во: {details.get('action_count', 1)}"
        )

        # 1. Снимаем все роли с нарушителя (кроме @everyone)
        saved_roles = await self._strip_all_roles(guild, user)

        # 2. Собираем список жертв (для банов/киков — собираем из трекера)
        victim_ids = await self._collect_victims(user, action_type, guild)

        # 3. Создаём алерт
        alert_data = {
            'id': datetime.utcnow().strftime('%Y%m%d%H%M%S') + str(user.id)[-4:],
            'user_id': str(user.id),
            'username': user.display_name,
            'user_avatar': str(user.avatar.url) if user.avatar else '',
            'action_type': action_type,
            'action_count': details.get('action_count', 1),
            'threshold': details.get('threshold', 0),
            'details': details,
            'saved_roles': saved_roles,
            'victim_ids': victim_ids,
            'timestamp': datetime.utcnow().isoformat(),
            'status': 'pending',  # pending / confirmed / rejected
            'resolved_by': None,
            'resolved_at': None,
            'guild_id': str(guild.id),
        }

        self._add_alert(alert_data)

        # 4. Логируем в logs.json
        try:
            from utils.logs_manager import LogsManager
            lm = LogsManager()
            lm.log_site_action(
                action='🛡️ Антилив — ТРИГГЕР',
                description=(
                    f'Пользователь {user.display_name} ({user.id}) — '
                    f'Действие: {action_type}, Количество: {details.get("action_count", 1)}. '
                    f'Все роли сняты. Ожидает подтверждения основателя.'
                ),
                user_id=str(user.id),
                user_name=user.display_name
            )
        except Exception as e:
            logging.error(f"[AntiLeak] Ошибка логирования: {e}")

        # 5. Отправляем embed в лог-канал Discord
        await self._send_discord_alert(guild, alert_data)

        # 6. Уведомляем нарушителя в ЛС
        await self._warn_user(user, action_type, details)

    # ==================== СНЯТИЕ РОЛЕЙ ====================

    async def _strip_all_roles(self, guild, user):
        """Снимает все роли с пользователя (кроме @everyone). Сохраняет для восстановления."""
        saved_role_ids = [r.id for r in user.roles if r.id != guild.default_role.id]

        if not saved_role_ids:
            return []

        roles_to_remove = [guild.get_role(rid) for rid in saved_role_ids if guild.get_role(rid)]
        roles_to_remove = [r for r in roles_to_remove if r is not None]

        if roles_to_remove:
            try:
                await user.remove_roles(
                    *roles_to_remove,
                    reason="🛡️ Антилив: автоматическое снятие ролей при подозрительной активности"
                )
                logging.info(f"[AntiLeak] Снято {len(roles_to_remove)} ролей с {user.display_name}")
            except discord.Forbidden:
                logging.error(f"[AntiLeak] Нет прав для снятия ролей с {user.display_name}")
            except Exception as e:
                logging.error(f"[AntiLeak] Ошибка снятия ролей: {e}")

        return saved_role_ids

    # ==================== СБОР ЖЕРТВ ====================

    async def _collect_victims(self, user, action_type, guild):
        """Собирает список ID пострадавших участников."""
        victim_ids = []
        tracker = self.action_tracker.get(str(user.id), {}).get(action_type, [])

        # Для банов и киков — пытаемся получить цели из audit log
        if action_type in ('member_ban_add', 'member_kick'):
            try:
                audit_action = self.AUDIT_ACTIONS.get(action_type)
                if audit_action:
                    async for entry in guild.audit_logs(limit=50, action=audit_action):
                        if entry.user and entry.user.id == user.id:
                            if entry.target and hasattr(entry.target, 'id'):
                                victim_ids.append(str(entry.target.id))
            except Exception:
                pass

        return victim_ids

    # ==================== ОТПРАВКА АЛЕРТА В DISCORD ====================

    async def _send_discord_alert(self, guild, alert_data):
        """Отправляет embed-уведомление в лог-канал."""
        try:
            log_channel = guild.get_channel(config.LOG_CHANNEL_ID)
            if not log_channel:
                return

            # Цвет embed по типу действия
            color = discord.Color.red()
            action_labels = {
                'member_ban_add': '🚫 Массовый бан',
                'member_kick': '👢 Массовый кик',
                'channel_delete': '🗑️ Удаление каналов',
                'channel_create': '📝 Создание каналов',
                'channel_overwrite_update': '🔓 Изменение прав каналов',
                'member_role_update': '👥 Изменение ролей',
                'guild_update': '⚙️ Изменение сервера',
                'owner_transfer': '👑 Передача владельца',
                'bot_add': '🤖 Подключение бота',
            }

            action_label = action_labels.get(alert_data['action_type'], alert_data['action_type'])

            embed = discord.Embed(
                title="🛡️ Антилив — ТРИГГЕР!",
                description=f"Обнаружена подозрительная активность!",
                color=color,
                timestamp=datetime.utcnow()
            )

            embed.add_field(
                name="Пользователь",
                value=f"{alert_data['username']} ({alert_data['user_id']})",
                inline=True
            )
            embed.add_field(
                name="Действие",
                value=action_label,
                inline=True
            )
            embed.add_field(
                name="Количество",
                value=f"{alert_data.get('action_count', 1)} (порог: {alert_data.get('threshold', '?')})",
                inline=True
            )

            # Детали
            details = alert_data.get('details', {})
            if alert_data['action_type'] in ('member_ban_add', 'member_kick'):
                victim_count = len(alert_data.get('victim_ids', []))
                embed.add_field(
                    name="Пострадавшие",
                    value=f"{victim_count} участников" if victim_count else "Н/Д",
                    inline=True
                )
            elif alert_data['action_type'] == 'channel_delete':
                embed.add_field(
                    name="Канал",
                    value=details.get('channel_name', 'Н/Д'),
                    inline=True
                )
            elif alert_data['action_type'] == 'guild_update':
                changes = details.get('guild_changes', {})
                change_text = '\n'.join([f"**{k}**: {v}" for k, v in changes.items()])
                if change_text:
                    embed.add_field(name="Изменения", value=change_text[:1024], inline=False)

            embed.add_field(
                name="Статус",
                value="⏳ Ожидает подтверждения основателя",
                inline=False
            )
            embed.set_footer(text="🛡️ Система Антилива — Arasaka Plaza")

            await log_channel.send(embed=embed)

        except Exception as e:
            logging.error(f"[AntiLeak] Ошибка отправки Discord алерта: {e}")

    # ==================== ПРЕДУПРЕЖДЕНИЕ НАРУШИТЕЛЯ ====================

    async def _warn_user(self, user, action_type, details):
        """Отправляет предупреждение нарушителю в ЛС."""
        try:
            embed = discord.Embed(
                title="🛡️ Антилив — Предупреждение",
                description=(
                    "Ваши действия были расценены как подозрительная активность. "
                    "Все ваши роли сняты до проверки основателем."
                ),
                color=discord.Color.orange(),
                timestamp=datetime.utcnow()
            )

            action_labels = {
                'member_ban_add': 'массовый бан участников',
                'member_kick': 'массовый кик участников',
                'channel_delete': 'массовое удаление каналов',
                'channel_create': 'массовое создание каналов',
                'channel_overwrite_update': 'массовое изменение прав каналов',
                'member_role_update': 'массовое изменение ролей',
                'guild_update': 'изменение настроек сервера',
                'owner_transfer': 'передача прав владельца',
                'bot_add': 'подключение нового бота',
            }

            embed.add_field(
                name="Причина",
                value=action_labels.get(action_type, action_type),
                inline=True
            )
            embed.add_field(
                name="Количество",
                value=str(details.get('action_count', 1)),
                inline=True
            )
            embed.add_field(
                name="Что дальше",
                value=(
                    "Основатель проверит действие и решит: "
                    "подтвердить или отклонить. "
                    "Ваши роли будут восстановлены после проверки."
                ),
                inline=False
            )
            embed.set_footer(text="🛡️ Система Антилива — Arasaka Plaza")

            await user.send(embed=embed)
        except discord.Forbidden:
            logging.warning(f"[AntiLeak] Не удалось отправить ЛС {user.display_name} (ЛС закрыты)")
        except Exception as e:
            logging.error(f"[AntiLeak] Ошибка отправки ЛС: {e}")

    # ==================== API ДЛЯ САЙТА ====================

    @staticmethod
    def get_all_alerts():
        """Возвращает все алерты (для сайта)."""
        alerts_file = os.path.join(config.DATA_DIR, 'antileak_alerts.json')
        try:
            with open(alerts_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    @staticmethod
    def get_alert_by_id(alert_id):
        """Возвращает алерт по ID."""
        alerts = AntiLeak.get_all_alerts()
        for a in alerts:
            if a['id'] == alert_id:
                return a
        return None

    @staticmethod
    def resolve_alert(alert_id, status, resolved_by):
        """Подтверждает или отклоняет алерт."""
        alerts_file = os.path.join(config.DATA_DIR, 'antileak_alerts.json')
        try:
            with open(alerts_file, 'r', encoding='utf-8') as f:
                alerts = json.load(f)
            for a in alerts:
                if a['id'] == alert_id:
                    a['status'] = status
                    a['resolved_by'] = resolved_by
                    a['resolved_at'] = datetime.utcnow().isoformat()
                    break
            with open(alerts_file, 'w', encoding='utf-8') as f:
                json.dump(alerts, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            logging.error(f"[AntiLeak] Ошибка resolve_alert: {e}")
            return False


async def setup(bot):
    await bot.add_cog(AntiLeak(bot))