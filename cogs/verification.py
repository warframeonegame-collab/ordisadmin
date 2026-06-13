# cogs/verification.py

import discord
from discord.ext import commands
import re
import asyncio
from datetime import datetime
from config import VERIFICATION_CHANNEL_ID, WELCOME_CHANNEL_ID, GUEST_ROLE_ID, MEMBER_ROLE_ID, NICKNAME_MAX_LENGTH, RECRUITMENT_CHANNEL_ID
from utils.database import Database


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


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()
        # Хранение состояния анкеты: {user_id: current_question_index}
        self._questionnaire_state = {}
        # Хранение ответов: {user_id: {key: answer}}
        self._questionnaire_answers = {}

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
            f"Чтобы стать участником клана, введите свой игровой ник в канале {verification_channel.mention}.", delete_after=30
        )

    @commands.Cog.listener()
    async def on_message(self, message):
        """Обработка сообщения с ником в канале верификации + ответы на вопросы анкеты."""
        if message.author == self.bot.user:
            return

        # === ОБРАБОТКА ОТВЕТОВ НА ВОПРОСЫ АНКЕТЫ (в ЛС) ===
        if isinstance(message.channel, discord.DMChannel):
            user_id = message.author.id
            if user_id in self._questionnaire_state:
                await self._handle_questionnaire_answer(message)
                return
            return

        # === ОБРАБОТКА ВЕРИФИКАЦИИ (в канале верификации) ===
        if message.channel.id == VERIFICATION_CHANNEL_ID:
            # Очищаем чат от старых сообщений (оставляем только последнее)
            await message.channel.purge(limit=100, check=lambda m: m.author != self.bot.user)

            # Валидация ника
            if len(message.content) > NICKNAME_MAX_LENGTH:
                await message.channel.send(f"Ник слишком длинный! Максимум {NICKNAME_MAX_LENGTH} символов.", delete_after=5)
                return

            if not re.match(r'^[a-zA-Z0-9_\-\.\[\] ]+$', message.content):
                await message.channel.send("Ник может содержать только латинские буквы, цифры, символы '_', '-', '.', '[', ']' и пробел.", delete_after=5)
                return

            member = message.author
            guild = message.guild

            # Получаем роли
            guest_role = guild.get_role(GUEST_ROLE_ID)
            member_role = guild.get_role(MEMBER_ROLE_ID)

            # ДИАГНОСТИКА
            print(f"\n--- ДИАГНОСТИКА ВЕРИФИКАЦИИ ---")
            print(f"Пользователь: {member.display_name} (ID: {member.id})")
            print(f"Позиция роли пользователя: {member.top_role.position}")
            print(f"Роль пользователя: {member.top_role.name}")
            print(f"Позиция роли бота: {guild.me.top_role.position}")
            print(f"Роль бота: {guild.me.top_role.name}")
            print(f"Права бота: {guild.me.guild_permissions}")

            # ПРОВЕРКА 1: Администратор
            if member.guild_permissions.administrator:
                await message.channel.send(
                    "❌ Бот не может верифицировать пользователей с правами администратора. "
                    "Обратитесь к администрации."
                )
                print("ОШИБКА: Пользователь — администратор")
                return

            # ПРОВЕРКА 2: Иерархия ролей
            if guild.me.top_role.position <= member.top_role.position:
                await message.channel.send(
                    "❌ У бота недостаточно прав для верификации этого пользователя. "
                    "Обратитесь к администратору сервера."
                )
                print("ОШИБКА: Роль бота ниже или равна роли пользователя!")
                return

            # ПРОВЕРКА 3: Существование ролей
            if not guest_role or not member_role:
                await message.channel.send(
                    "❌ Ошибка конфигурации бота. "
                    "Обратитесь к администратору."
                )
                print("ОШИБКА: Одна из ролей не найдена!")
                return

            try:
                # Меняем ник
                await member.edit(nick=message.content)

                # Убираем старую роль
                if guest_role and guest_role in member.roles:
                    await member.remove_roles(guest_role)

                # Выдаём новую роль
                if member_role:
                    await member.add_roles(member_role)

                # УДАЛЕНИЕ СООБЩЕНИЯ С ОБРАБОТКОЙ ОШИБКИ 404
                try:
                    await message.delete()
                except discord.NotFound:
                    pass

                # Отправляем подтверждение
                await message.channel.send(
                    f"✅ {member.mention}, ваш ник установлен и вы приняты в клан!",
                    delete_after=30
                )
                print("ВЕРИФИКАЦИЯ УСПЕШНА")

                # Запускаем анкету рекрутинга через ЛС
                await self._start_questionnaire(member)

            except discord.Forbidden as e:
                print(f"ОШИБКА ПРАВ: {e}")
                await message.channel.send(
                    "К сожалению, верификация не прошла из‑за ограничений прав. "
                    "Обратитесь к администратору сервера для решения проблемы."
                )
            except Exception as e:
                print(f"НЕПРЕДВИДЕННАЯ ОШИБКА: {e}")
                await message.channel.send(
                    "Произошла непредвиденная ошибка. "
                    "Пожалуйста, попробуйте позже или обратитесь к основателю клана. "
                )

    # ==================== СИСТЕМА АНКЕТЫ ====================

    async def _start_questionnaire(self, member):
        """Начинает анкету рекрутинга — отправляет первый вопрос в ЛС."""
        user_id = member.id

        # Проверяем, не заполнена ли уже анкета
        user_data = self.db.get_user(user_id)
        if user_data.get('questionnaire'):
            print(f"[Questionnaire] Анкета уже заполнена для {user_id}")
            return

        # Проверяем, не в процессе ли уже
        if user_id in self._questionnaire_state:
            return

        try:
            dm_channel = await member.create_dm()

            welcome_embed = discord.Embed(
                title="📋 Анкета рекрута",
                description=(
                    f"Привет, **{member.display_name}**! 🎉\n\n"
                    f"Добро пожаловать в **Arasaka Plaza**!\n"
                    f"Пожалуйста, заполни короткую анкету — это поможет нам лучше тебя узнать.\n\n"
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

        except discord.Forbidden:
            print(f"[Questionnaire] Не удалось отправить ЛС {member.id} (ЛС закрыты)")
        except Exception as e:
            print(f"[Questionnaire] Ошибка запуска анкеты для {member.id}: {e}")

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
        if not hasattr(self, '_questionnaire_answers'):
            self._questionnaire_answers = {}
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
            print(f"[Questionnaire] Канал рекрутинга {RECRUITMENT_CHANNEL_ID} не найден!")
            return

        embed = discord.Embed(
            title="📋 АНКЕТА РЕКРУТА",
            description=f"Новая анкета от {member.mention}",
            color=discord.Color.purple(),
            timestamp=datetime.utcnow()
        )

        # Имя
        embed.add_field(
            name="1️⃣ Имя",
            value=data.get('name', 'Не указано'),
            inline=False
        )
        # Возраст
        embed.add_field(
            name="2️⃣ Возраст",
            value=data.get('age', 'Не указано'),
            inline=False
        )
        # Подразделения
        embed.add_field(
            name="3️⃣ Интерес к подразделениям",
            value=data.get('subdivision_interest', 'Не указано'),
            inline=False
        )
        # Ожидания
        embed.add_field(
            name="4️⃣ Ожидания от клана",
            value=data.get('expectations', 'Не указано'),
            inline=False
        )
        # Вклад
        embed.add_field(
            name="5️⃣ Что может дать клану",
            value=data.get('contribution', 'Не указано'),
            inline=False
        )

        embed.set_footer(text=f"ID: {member.id} | Заполнено: {data.get('filled_at', 'N/A')}")

        try:
            await channel.send(embed=embed)
            print(f"[Questionnaire] Анкета {member.id} отправлена в канал рекрутинга")
        except Exception as e:
            print(f"[Questionnaire] Ошибка отправки анкеты: {e}")


async def setup(bot):
    await bot.add_cog(Verification(bot))