# cogs/verification.py

import discord
import discord.app_commands as app_commands
from discord.ext import commands
import re
import asyncio
import logging
from datetime import datetime
from config import (VERIFICATION_CHANNEL_ID, WELCOME_CHANNEL_ID, GUEST_ROLE_ID,
                    MEMBER_ROLE_ID, NICKNAME_MAX_LENGTH, RECRUITMENT_CHANNEL_ID,
                    GUILD_ID)
import config
from utils.database import Database

logger = logging.getLogger(__name__)

# Маркер в футере панели — по нему находим закреплённое сообщение при перезапуске
PANEL_FOOTER_MARKER = "Arasaka Plaza • Система верификации"

NICKNAME_ALLOWED = r'^[a-zA-Z0-9_\-\.\[\] ]+$'


class VerificationPanelView(discord.ui.View):
    """Постоянная панель верификации (кнопка не протухает благодаря custom_id)."""

    def __init__(self, cog: "Verification"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Верифицироваться", emoji="✅",
                       style=discord.ButtonStyle.success, custom_id="ordis:verification")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog._handle_verify_button(interaction)


# Вопросы рекрутинга (задаются по очереди через ЛС)
RECRUITMENT_QUESTIONS = [
    {
        'key': 'name',
        'question': '👋 **Как тебя зовут?**',
    },
    {
        'key': 'age',
        'question': '🎂 **Сколько тебе лет?**\n_Можно не отвечать, если не хочешь._',
    },
    {
        'key': 'subdivision_interest',
        'question': '🏗️ **Заинтересован ли ты в участии в подразделениях (строитель, рекрутер)?**\n_Если да — в каких? Если нет — просто напиши «нет»._',
    },
    {
        'key': 'expectations',
        'question': '🤔 **Что ты ожидаешь от клана?**',
    },
    {
        'key': 'contribution',
        'question': '💪 **Что ты можешь дать клану?**',
    },
]


def _build_panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="✅ Верификация в клан",
        description=(
            "Добро пожаловать в **Arasaka Plaza**!\n\n"
            "Нажмите кнопку ниже — бот напишет вам в **ЛС** и попросит указать "
            "ваш игровой ник.\n\n"
            "**Требования к нику:**\n"
            f"• Максимум **{NICKNAME_MAX_LENGTH}** символов\n"
            "• Только латинские буквы, цифры, `_`, `-`, `.`, `[`, `]` и пробел\n"
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=PANEL_FOOTER_MARKER)
    return embed


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        # Хранение состояния анкеты: {user_id: current_question_index}
        self._questionnaire_state = {}
        # Хранение ответов: {user_id: {key: answer}}
        self._questionnaire_answers = {}
        # Пользователи, которые ждут запроса ника в ЛС
        self._nick_state = set()
        # Регистрируем постоянную панель (кнопки работают после рестартов)
        bot.add_view(VerificationPanelView(self))

    # ==================== ПАНЕЛЬ ВЕРИФИКАЦИИ ====================

    @commands.Cog.listener()
    async def on_ready(self):
        await self._ensure_panel()

    async def _ensure_panel(self):
        """Ищет закреплённую панель верификации; редактирует или создаёт её."""
        channel = self.bot.get_channel(VERIFICATION_CHANNEL_ID)
        if not channel:
            logger.warning("[Verification] Канал верификации не найден!")
            return

        embed = _build_panel_embed()

        target = None
        try:
            for msg in await channel.pins():
                if msg.embeds and msg.embeds[0].footer.text == PANEL_FOOTER_MARKER:
                    target = msg
                    break
        except discord.HTTPException as e:
            logger.debug(f"[Verification] Не удалось получить закреплённые сообщения: {e}")

        try:
            if target:
                if not (target.embeds and target.embeds[0].description == embed.description
                        and target.embeds[0].title == embed.title):
                    await target.edit(embed=embed)
                logger.debug("[Verification] Панель верификации на месте")
            else:
                # Панели нет — чистим чат (кроме сообщений бота) и создаём новую
                try:
                    await channel.purge(limit=100, check=lambda m: m.author != self.bot.user)
                except discord.HTTPException:
                    pass
                new_msg = await channel.send(embed=embed)
                try:
                    await new_msg.pin()
                except discord.HTTPException:
                    logger.debug("[Verification] Не удалось закрепить панель")
                logger.info("[Verification] Создана новая панель верификации")
        except discord.Forbidden:
            logger.warning("[Verification] Нет прав для обновления панели верификации")
        except Exception as e:
            logger.error(f"[Verification] Ошибка панели верификации: {e}")

    async def _handle_verify_button(self, interaction: discord.Interaction):
        """Кнопка «Верифицироваться» — ephemeral-ответ + запрос ника в ЛС."""
        member = interaction.user
        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Команда доступна только на сервере.", ephemeral=True)
            return

        member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
        guest_role = interaction.guild.get_role(GUEST_ROLE_ID)

        if member_role and member_role in member.roles:
            await interaction.response.send_message(
                "✅ Вы уже верифицированы!", ephemeral=True)
            return
        if guest_role and guest_role not in member.roles:
            await interaction.response.send_message(
                "❌ Верификация доступна только гостям сервера.", ephemeral=True)
            return

        bot_member = interaction.guild.me
        if member.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Бот не может верифицировать пользователей с правами администратора. "
                "Обратитесь к администрации.", ephemeral=True)
            return
        if bot_member.top_role.position <= member.top_role.position:
            await interaction.response.send_message(
                "❌ У бота недостаточно прав для верификации этого пользователя. "
                "Обратитесь к администратору сервера.", ephemeral=True)
            return
        if not guest_role or not member_role:
            await interaction.response.send_message(
                "❌ Ошибка конфигурации бота. Обратитесь к администратору.", ephemeral=True)
            return

        # Ephemeral-подтверждение, дальше всё в ЛС
        await interaction.response.send_message(
            "📨 Я отправил вам в **ЛС** — напишите там свой игровой ник. "
            "Если ЛС от бота закрыты, разрешите их в настройках приватности сервера.",
            ephemeral=True)
        await self._ask_nick_in_dm(member)

    async def _ask_nick_in_dm(self, member: discord.Member):
        """Просит ник в ЛС и помечает пользователя как ожидающего ввода."""
        if member.id in self._nick_state:
            return
        self._nick_state.add(member.id)
        try:
            dm = await member.create_dm()
            embed = discord.Embed(
                title="🔑 Последний шаг — верификация",
                description=(
                    f"Привет, **{member.display_name}**!\n\n"
                    f"Напишите следующим сообщением ваш **игровой ник** — он будет "
                    f"установлен на сервере.\n\n"
                    f"**Требования:**\n"
                    f"• Максимум **{NICKNAME_MAX_LENGTH}** символов\n"
                    f"• Только латинские буквы, цифры, `_`, `-`, `.`, `[`, `]` и пробел"
                ),
                color=discord.Color.blurple()
            )
            embed.set_footer(text="Напишите ник одним сообщением")
            await dm.send(embed=embed)
        except discord.Forbidden:
            self._nick_state.discard(member.id)
            logger.debug(f"[Verification] ЛС закрыты для {member.id} (запрос ника)")
        except Exception as e:
            self._nick_state.discard(member.id)
            logger.error(f"[Verification] Ошибка запроса ника у {member.id}: {e}")

    async def _handle_nick_in_dm(self, message: discord.Message):
        """Обработка ника, присланного в ЛС после нажатия кнопки."""
        user_id = message.author.id
        nick = message.content.strip()

        guild = self.bot.get_guild(GUILD_ID) if GUILD_ID else (self.bot.guilds[0] if self.bot.guilds else None)
        member = guild.get_member(user_id) if guild else None

        def dm_reply(text, color=discord.Color.red()):
            return message.channel.send(embed=discord.Embed(description=text, color=color))

        if member is None:
            await dm_reply("❌ Не могу найти вас на сервере — зайдите на сервер и попробуйте снова.")
            return

        error = self._validate_nick(nick)
        if error:
            self._try_nickname_autocorrect(nick)
            await dm_reply(error)
            return

        guest_role = guild.get_role(GUEST_ROLE_ID)
        member_role = guild.get_role(MEMBER_ROLE_ID)

        if member.guild_permissions.administrator:
            await dm_reply("❌ Бот не может верифицировать пользователей с правами администратора.")
            return
        if guild.me.top_role.position <= member.top_role.position:
            await dm_reply("❌ У бота недостаточно прав для верификации вас. Обратитесь к администратору сервера.")
            return
        if not guest_role or not member_role:
            await dm_reply("❌ Ошибка конфигурации бота. Обратитесь к администратору.")
            return

        try:
            await member.edit(nick=nick, reason="Верификация: установка ника")
            if guest_role in member.roles:
                await member.remove_roles(guest_role, reason="Верификация: снятие Guest")
            await member.add_roles(member_role, reason="Верификация: выдача Member")
        except discord.Forbidden:
            await dm_reply("К сожалению, верификация не прошла из-за ограничений прав. "
                           "Обратитесь к администратору сервера.")
            return
        except Exception as e:
            logger.error(f"[Verification] Непредвиденная ошибка верификации {user_id}: {e}")
            await dm_reply("Произошла непредвиденная ошибка. Попробуйте позже или обратитесь к основателю клана.")
            return

        self._nick_state.discard(user_id)

        await dm_reply(f"✅ Готово! Ник **{nick}** установлен — вы приняты в клан!", discord.Color.green())

        # Подтверждение в канале верификации
        channel = guild.get_channel(VERIFICATION_CHANNEL_ID)
        if channel:
            try:
                await channel.send(f"✅ {member.mention} верифицирован!", delete_after=30)
            except Exception:
                pass

        # Запускаем анкету рекрутинга через ЛС
        try:
            await self._start_questionnaire(member)
        except Exception as e:
            logger.error(f"[Verification] Не удалось запустить анкету для {user_id}: {e}")

    def _try_nickname_autocorrect(self, nick):
        """Хук на будущее: припаркованные подсказки при невалидном нике."""
        logger.debug(f"[Verification] Отклонён ник: {nick!r} (некорректный формат)")

    def _validate_nick(self, nick: str):
        """Возвращает строку ошибки или None, если ник корректен."""
        if not nick:
            return "Ник не может быть пустым. Напишите ваш игровой ник одним сообщением."
        if len(nick) > NICKNAME_MAX_LENGTH:
            return f"❌ Ник слишком длинный! Максимум {NICKNAME_MAX_LENGTH} символов."
        if not re.match(NICKNAME_ALLOWED, nick):
            return ("❌ Ник может содержать только латинские буквы, цифры, символы "
                    "`_`, `-`, `.`, `[`, `]` и пробел.")
        return None

    # ==================== ВХОД И СТАРЫЙ ПУТЬ ВЕРИФИКАЦИИ ====================

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Приветствие нового участника и выдача роли "Гость" при входе."""
        welcome_channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        verification_channel = self.bot.get_channel(VERIFICATION_CHANNEL_ID)
        guest_role = member.guild.get_role(GUEST_ROLE_ID)

        if guest_role:
            await member.add_roles(guest_role)

        # Создаём запись пользователя с реальной датой вступления из Discord
        real_joined = member.joined_at.strftime('%d.%m.%Y') if member.joined_at else None
        self.db.get_user(member.id, joined_at=real_joined)

        await welcome_channel.send(
            f"Добро пожаловать, {member.mention}! "
            f"Нажмите кнопку «✅ Верифицироваться» в канале {verification_channel.mention}.",
            delete_after=60
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        """Ответы анкеты/ника в ЛС + очистка канала верификации от посторонних сообщений."""
        if message.author == self.bot.user:
            return

        # === ОБРАБОТКА ЛС (анкета / ник) ===
        if isinstance(message.channel, discord.DMChannel):
            user_id = message.author.id
            if user_id in self._questionnaire_state:
                await self._handle_questionnaire_answer(message)
                return
            if user_id in self._nick_state:
                await self._handle_nick_in_dm(message)
                return
            return

        # === КАНАЛ ВЕРИФИКАЦИИ: чистим от посторонних сообщений ===
        if message.channel.id == VERIFICATION_CHANNEL_ID:
            # Панель бота остаётся, чужие сообщения удаляем; гостям подсказываем кнопку
            await message.channel.purge(limit=100, check=lambda m: m.author != self.bot.user)
            logger.debug(
                f"[Verification] Сообщение удалено: {message.author} — "
                f"top_role={message.author.top_role.name} "
                f"(bot top_role={message.channel.guild.me.top_role.name})"
            )

    # ==================== СИСТЕМА АНКЕТЫ ====================

    async def _start_questionnaire(self, member):
        """Начинает анкету рекрутинга — отправляет первый вопрос в ЛС."""
        user_id = member.id

        # Проверяем, не заполнена ли уже анкета
        user_data = self.db.get_user(user_id)
        if user_data.get('questionnaire'):
            logger.debug(f"[Questionnaire] Анкета уже заполнена для {user_id}")
            return

        # Проверяем, не в процессе ли уже
        if user_id in self._questionnaire_state:
            return

        dm_channel = await member.create_dm()
        welcome_embed = discord.Embed(
            title="📋 Анкета рекрута",
            description=(
                f"Привет, **{member.display_name}**! 🎉\n\n"
                f"Добро пожаловать в **Arasaka Plaza**!\n"
                f"Пожалуйста, заполни короткую анкету — это поможет нам лучше тебя узнать.\n\n"
                f"⚠️ **Важно:** Пиши адекватно и по делу. Данные анкеты проверяются администрацией!\n\n"
                f"Всего **{len(RECRUITMENT_QUESTIONS)}** вопросов. "
                f"Отвечай на каждый по очереди.\n"
                f"_Чтобы пропустить вопрос — напиши «-» или «пропустить»._"
            ),
            color=discord.Color.blurple()
        )
        await dm_channel.send(embed=welcome_embed)

        # Начинаем с вопроса 0
        self._questionnaire_state[user_id] = 0
        await self._send_current_question(member, dm_channel)

    async def _send_current_question(self, member, dm_channel):
        """Отправляет текущий вопрос из анкеты."""
        user_id = member.id
        q_index = self._questionnaire_state.get(user_id)

        if q_index is None or q_index >= len(RECRUITMENT_QUESTIONS):
            return

        question_data = RECRUITMENT_QUESTIONS[q_index]

        embed = discord.Embed(
            title=f"Вопрос {q_index + 1}/{len(RECRUITMENT_QUESTIONS)}",
            description=question_data['question'],
            color=discord.Color.gold()
        )
        embed.set_footer(text="Напиши свой ответ следующим сообщением")
        await dm_channel.send(embed=embed)

    async def _handle_questionnaire_answer(self, message):
        """Обрабатывает ответ на вопрос анкеты."""
        user_id = message.author.id
        q_index = self._questionnaire_state.get(user_id)

        if q_index is None or q_index >= len(RECRUITMENT_QUESTIONS):
            return

        answer = message.content.strip()
        question_data = RECRUITMENT_QUESTIONS[q_index]

        # Пропуск вопроса
        if answer.lower() in ['-', 'пропустить', 'skip', '']:
            answer = 'Не указано'

        # Сохраняем ответ во временное хранилище
        if user_id not in self._questionnaire_answers:
            self._questionnaire_answers[user_id] = {}

        self._questionnaire_answers[user_id][question_data['key']] = answer

        # Переходим к следующему вопросу
        next_index = q_index + 1

        if next_index >= len(RECRUITMENT_QUESTIONS):
            # Все вопросы пройдены — завершаем анкету
            await self._complete_questionnaire(message.author)
        else:
            self._questionnaire_state[user_id] = next_index
            await self._send_current_question(message.author, message.channel)

    async def _complete_questionnaire(self, member):
        """Завершает анкету — сохраняет в БД и отправляет в канал рекрутинга."""
        user_id = member.id
        answers = self._questionnaire_answers.pop(user_id, {})
        self._questionnaire_state.pop(user_id, None)

        # Сохраняем в БД
        questionnaire_data = {
            'filled_at': datetime.now().strftime('%d.%m.%Y %H:%M'),
            'user_id': str(user_id),
            'username': member.display_name,
        }
        for q in RECRUITMENT_QUESTIONS:
            questionnaire_data[q['key']] = answers.get(q['key'], 'Не указано')

        self.db.update_user(user_id, questionnaire=questionnaire_data)

        # Достижение «Первая анкета»
        try:
            ach = (self.db.get_user(user_id).get('achievements') or {})
            if not ach.get('first_questionnaire'):
                ach['first_questionnaire'] = True
                self.db.update_user(user_id, achievements=ach)
        except Exception as e:
            logger.error(f"[Questionnaire] Не удалось записать достижение first_questionnaire: {e}")

        # Если пользователь указал имя — добавляем его в скобках к нику на сервере
        real_name = (answers.get('name') or '').strip()
        if real_name and real_name.lower() not in ['не указано', '-', 'пропустить', 'skip', '']:
            try:
                current_nick = member.display_name
                # Проверяем, нет ли уже скобок с именем
                if '(' not in current_nick and ')' not in current_nick:
                    new_nick = f"{current_nick} ({real_name})"
                    # Ограничение на 32 символа
                    if len(new_nick) <= 32:
                        await member.edit(nick=new_nick)
                        logger.debug(f"[Questionnaire] Ник изменён на '{new_nick}' для {user_id}")
                    else:
                        # Обрезаем игровой ник если слишком длинный
                        max_game_nick_len = 32 - len(real_name) - 4  # 4 = " ()"
                        if max_game_nick_len > 5:
                            trimmed_nick = current_nick[:max_game_nick_len]
                            new_nick = f"{trimmed_nick} ({real_name})"
                            await member.edit(nick=new_nick)
                            logger.debug(f"[Questionnaire] Ник изменён на '{new_nick}' (обрезан) для {user_id}")
            except discord.Forbidden:
                logger.debug(f"[Questionnaire] Нет прав для изменения ника {user_id}")
            except Exception as e:
                logger.error(f"[Questionnaire] Ошибка изменения ника {user_id}: {e}")

        # Отправляем подтверждение в ЛС
        try:
            dm_channel = await member.create_dm()
            embed = discord.Embed(
                title="✅ Анкета заполнена!",
                description=(
                    "Спасибо за заполнение анкеты! 🎉\n"
                    "Твоя заявка будет рассмотрена администрацией.\n"
                    "Добро пожаловать в **Arasaka Plaza**!"
                ),
                color=discord.Color.green()
            )
            await dm_channel.send(embed=embed)
        except Exception:
            pass

        # Отправляем анкету в канал рекрутинга
        await self._send_recruitment_embed(member, questionnaire_data)

    async def _send_recruitment_embed(self, member, data):
        """Отправляет заполненную анкету в канал рекрутинга."""
        channel = self.bot.get_channel(RECRUITMENT_CHANNEL_ID)
        if not channel:
            logger.error(f"[Questionnaire] Канал рекрутинга {RECRUITMENT_CHANNEL_ID} не найден!")
            return

        embed = discord.Embed(
            title="📋 АНКЕТА РЕКРУТА",
            description=f"Новая анкета от {member.mention}",
            color=discord.Color.purple(),
            timestamp=datetime.now()
        )

        embed.add_field(name="1️⃣ Имя", value=data.get('name', 'Не указано'), inline=False)
        embed.add_field(name="2️⃣ Возраст", value=data.get('age', 'Не указано'), inline=False)
        embed.add_field(name="3️⃣ Интерес к подразделениям",
                        value=data.get('subdivision_interest', 'Не указано'), inline=False)
        embed.add_field(name="4️⃣ Ожидания от клана",
                        value=data.get('expectations', 'Не указано'), inline=False)
        embed.add_field(name="5️⃣ Что может дать клану",
                        value=data.get('contribution', 'Не указано'), inline=False)

        embed.set_footer(text=f"ID: {member.id} | Заполнено: {data.get('filled_at', 'N/A')}")

        try:
            await channel.send(embed=embed)
            logger.debug(f"[Questionnaire] Анкета {member.id} отправлена в канал рекрутинга")
        except Exception as e:
            logger.error(f"[Questionnaire] Ошибка отправки анкеты: {e}")

    # ==================== КОМАНДА МАССОВОЙ РАССЫЛКИ АНКЕТЫ ====================

    @commands.hybrid_command(name="sendquestionnaire",
                             description="Отправить анкету рекрутинга всем участникам в ЛС")
    @commands.has_permissions(administrator=True)
    async def send_questionnaire_to_all(self, ctx):
        """Отправляет анкету рекрутинга всем участникам сервера в ЛС (только для администрации)"""
        if not isinstance(ctx.interaction, discord.Interaction):
            await ctx.message.delete()

        msg = await ctx.send("⏳ Начинаю отправку анкет всем участникам...")

        sent_count = 0
        fail_count = 0
        already_filled = 0

        for member in ctx.guild.members:
            if member.bot:
                continue

            user_id = member.id

            # Проверяем, не заполнена ли уже анкета
            user_data = self.db.get_user(user_id)
            if user_data.get('questionnaire'):
                already_filled += 1
                continue

            # Проверяем, не в процессе ли уже
            if user_id in self._questionnaire_state:
                continue

            try:
                dm_channel = await member.create_dm()
                welcome_embed = discord.Embed(
                    title="📋 Анкета рекрута",
                    description=(
                        f"Привет, **{member.display_name}**! 🎉\n\n"
                        f"Добро пожаловать в **Arasaka Plaza**!\n"
                        f"Пожалуйста, заполни короткую анкету — это поможет нам лучше тебя узнать.\n\n"
                        f"⚠️ **Важно:** Пиши адекватно и по делу. Данные анкеты проверяются администрацией!\n\n"
                        f"Всего **{len(RECRUITMENT_QUESTIONS)}** вопросов. "
                        f"Отвечай на каждый по очереди.\n"
                        f"_Чтобы пропустить вопрос — напиши «-» или «пропустить»._"
                    ),
                    color=discord.Color.blurple()
                )
                await dm_channel.send(embed=welcome_embed)

                # Начинаем анкету
                self._questionnaire_state[user_id] = 0
                await self._send_current_question(member, dm_channel)
                sent_count += 1

                # Небольшая задержка, чтобы не спамить Discord API
                await asyncio.sleep(0.5)

            except discord.Forbidden:
                fail_count += 1
            except Exception as e:
                logger.error(f"[MassQuestionnaire] Ошибка для {user_id}: {e}")
                fail_count += 1

        # Отправляем отчёт
        report = (
            f"📊 **Отчёт о массовой отправке анкет:**\n"
            f"✅ Отправлено: **{sent_count}**\n"
            f"❌ Ошибок (ЛС закрыты): **{fail_count}**\n"
            f"⏭️ Уже заполнено: **{already_filled}**"
        )
        await msg.edit(content=report)


async def setup(bot):
    await bot.add_cog(Verification(bot))
