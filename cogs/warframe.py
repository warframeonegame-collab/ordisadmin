import discord
from discord.ext import commands, tasks
import httpx
import logging
import asyncio
from datetime import datetime, timezone

WARFRAME_API = "https://api.warframestat.us/pc/"
WARFRAME_COLOR = discord.Color.from_rgb(255, 185, 15)

BARO_NOTIFY_CHANNEL_ID = 1255444820902543380
WARFRAME_INFO_CHANNEL_ID = 1514184364941119528

CYCLE_TRANSLATIONS = {
    "day": "День",
    "night": "Ночь",
    "warm": "Тепло",
    "cold": "Холод",
    "fass": "Фэз",
    "vome": "Воум",
}

DUVIRI_STATE_TRANSLATIONS = {
    "anger": "😠 Гнев",
    "joy": "😊 Радость",
    "envy": "😒 Зависть",
    "sorrow": "😢 Печаль",
    "fear": "😨 Страх",
}

BARO_ITEM_TRANSLATIONS = {
    "Braton Prime Set": "Набор Братон Прайм",
    "Saryn Prime Set": "Набор Сарин Прайм",
    "Lex Prime Set": "Набор Лекс Прайм",
    "Mag Prime Set": "Набор Маг Прайм",
    "Frost Prime Set": "Набор Фрост Прайм",
    "Ember Prime Set": "Набор Эмбер Прайм",
    "Nova Prime Set": "Набор Нова Прайм",
    "Boltor Prime Set": "Набор Болтор Прайм",
    "Fragor Prime Set": "Набор Фрагор Прайм",
    "Dakka Prime Set": "Набор Дакка Прайм",
    "Nikana Prime Set": "Набор Никана Прайм",
    "Venka Prime Set": "Набор Венка Прайм",
    "Cernos Prime Set": "Набор Цернос Прайм",
    "Galatine Prime Set": "Набор Галатин Прайм",
    "Tigris Prime Set": "Набор Тигрис Прайм",
    "Orthos Prime Set": "Набор Ортос Прайм",
    "Kamas Prime Set": "Набор Камас Прайм",
    "Akstiletto Prime Set": "Набор Акстилетто Прайм",
    "Spira Prime Set": "Набор Спира Прайм",
    "Kavasa Prime Kubrow Collar Set": "Набор Каваса Прайм",
    "Primed Continuity": "Основная Непрерывность Прайм",
    "Primed Flow": "Основной Поток Прайм",
    "Primed Cryo Rounds": "Основные Крио Снаряды Прайм",
    "Primed Pistol Gambit": "Основной Пистолетный Гамбит Прайм",
    "Primed Target Cracker": "Основной Целевой Кракер Прайм",
    "Primed Ravage": "Основное Разрушение Прайм",
    "Primed Chamber": "Основная Камера Прайм",
    "Primed Firestorm": "Основной Огненный Шторм Прайм",
    "Primed Fever Strike": "Основной Лихорадочный Удар Прайм",
    "Primed Convulsion": "Основной Судорога Прайм",
    "Primed Expel": "Основное Изгнание Прайм",
    "Primed Bane": "Основное Проклятие Прайм",
    "Primed Sure Footed": "Основная Уверенная Стопа Прайм",
    "Primed Animal Instinct": "Основной Животный Инстинкт Прайм",
    "Primed Pack Leader": "Основной Вожак Стая Прайм",
    "Primed Reach": "Основная Досягаемость Прайм",
    "Primed Point Blank": "Основное Точное Попадание Прайм",
    "Primed Pressure Point": "Основное Боевое Давление Прайм",
    "Primed Regen": "Основная Регенерация Прайм",
    "Primed Scorch": "Основной Обжиг Прайм",
    "Primed Smite": "Основное Поражение Прайм",
    "Prisma Skana": "Призма Скана",
    "Prisma Dual Cleavers": "Призма Двойные Клинки",
    "Prisma Gorgon": "Призма Горгон",
    "Prisma Machete": "Призма Мачете",
    "Prova Vandal": "Прова Вандал",
    "Dera Vandal": "Дера Вандал",
    "Strun Vandal": "Струн Вандал",
    "Karak Wraith": "Карак Рэт",
    "Tenet Diplos": "Тенет Диплос",
    "Tenet Envoy": "Тенет Энвой",
    "Tenet Ferrox": "Тенет Феррокс",
    "Tenet Flux": "Тенет Флукс",
    "Tenet Grigori": "Тенет Григори",
    "Tenet Livia": "Тенет Ливия",
    "Tenet Spirex": "Тенет Спайрекс",
    "Tenet Tetra": "Тенет Тетра",
    "Tenet Exec": "Тенет Экзек",
    "Tenet Plinx": "Тенет Плинкс",
    "Kuva Chakkhurr": "Кува Чакхурр",
    "Kuva Bramma": "Кува Брамма",
    "Kuva Ogris": "Кува Огрис",
    "Kuva Karak": "Кува Карак",
    "Kuva Hind": "Кува Хинд",
    "Kuva Shildeg": "Кува Шилдег",
    "Kuva Seer": "Кува Сир",
    "Kuva Quartakk": "Кува Квартакк",
    "Kuva Kohm": "Кува Коум",
    "Kuva Kraken": "Кува Кракен",
    "Kuva Tonkor": "Кува Тонкор",
    "Kuva Brakk": "Кува Бракк",
    "Kuva Sobek": "Кува Собек",
    "KuvaZarr": "Кува Зарр",
    "KuvaAyanga": "Кува Аянга",
    "Arcane Energize": "Аркан Энергиз",
    "Arcane Grace": "Аркан Грейс",
    "Arcane Guardian": "Аркан Гардиан",
    "Arcane Strike": "Аркан Удар",
    "Arcane Velocity": "Аркан Скорость",
    "Arcane Agility": "Аркан Ловкость",
    "Arcane Precision": "Аркан Точность",
    "Arcane Momentum": "Аркан Импульс",
    "Arcane Rage": "Аркан Ярость",
    "Arcane Avenger": "Аркан Мститель",
    "Arcane Ultimatum": "Аркан Ультиматум",
    "Arcane Phoenix": "Аркан Феникс",
    "Noggle Statue - Teshin": "Статуэтка Ноггл - Тешин",
    "Orokin Tea Set": "Орокин Чайный Набор",
    "Crania Ephemera": "Эфемера Крания",
    "Trio Orbit Ephermera": "Эфемера Трио Орбит",
    "Veiled Riven Cipher": "Туманный Ривен Шифр",
    "Exilus Warframe Adapter": "Экзилус Адаптер Варфрейма",
    "Exilus Weapon Adapter Blueprint": "Чертёж Экзилус Адаптера Оружия",
    "Detonite Ampule": "Ампула Детонита",
    "Fieldron Sample": "Образец Филдрона",
    "Mutagen Mass": "Мутагенная Масса",
    "Stance Forma Blueprint": "Чертёж Стансы Форма",
    "Relic Pack": "Набор Реликтов",
    "Primary Arcane Adapter": "Адаптер Аркана Основного",
    "Secondary Arcane Adapter": "Адаптер Аркана Дополнительного",
    "10k Kuva": "10к Кува",
    "50,000 Kuva": "50 000 Кува",
    "30,000 Endo": "30 000 Эндо",
    "3x Forma": "3x Форма",
    "Umbra Forma Blueprint": "Чертёж Умбра Форма",
    "Kitgun Riven Mod": "Мод Ривен Китган",
    "Zaw Riven Mod": "Мод Ривен Зау",
    "Rifle Riven Mod": "Мод Ривен Винтовки",
    "Shotgun Riven Mod": "Мод Ривен Дробовика",
    "Counterbalance": "Противовес",
    "Gauss in Action Glyph": "Глиф Гаусс в Действии",
    "Grendel in Action Glyph": "Глиф Грендель в Действии",
    "Protea in Action Glyph": "Глиф Протея в Действии",
    "Xaku in Action Glyph": "Глиф Ксату в Действии",
    "Bishamo Pauldrons Blueprint": "Чертёж Наплечники Бишамо",
    "Bishamo Cuirass Blueprint": "Чертёж Куярасс Бишамо",
    "Bishamo Helmet Blueprint": "Чертёж Шлем Бишамо",
    "Bishamo Greaves Blueprint": "Чертёж Поножи Бишамо",
}


async def fetch_warframe_data(retries=3):
    """Получает данные Warframe API с повторными попытками."""
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.get(WARFRAME_API, headers={"User-Agent": "OrdisBot/1.0"})
                r.raise_for_status()
                return r.json()
        except httpx.ReadTimeout:
            print(f"[Warframe] API таймаут (попытка {attempt + 1}/{retries})")
            if attempt < retries - 1:
                import asyncio as _aio
                await _aio.sleep(5)
            else:
                raise


def translate_item(name):
    return BARO_ITEM_TRANSLATIONS.get(name, name)


class WarframeView(discord.ui.View):
    """View с кнопкой для переключения между таймерами и ротацией Дувири."""

    def __init__(self, main_embed: discord.Embed, rotation_embed: discord.Embed):
        super().__init__(timeout=300)
        self.main_embed = main_embed
        self.rotation_embed = rotation_embed
        self.showing_rotation = False

    @discord.ui.button(label="🔄 Цепи Дувирии", style=discord.ButtonStyle.primary)
    async def toggle_rotation(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.showing_rotation:
            await interaction.response.edit_message(embed=self.main_embed, view=self)
            button.label = "🔄 Цепи Дувирии"
            self.showing_rotation = False
        else:
            await interaction.response.edit_message(embed=self.rotation_embed, view=self)
            button.label = "🌍 Таймеры"
            self.showing_rotation = True

    async def on_timeout(self):
        self.stop()


class Warframe(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._baro_notified = False
        self._main_message_id = None
        self._last_main_embed = None
        self._last_rotation_embed = None
        print("[Warframe] Ког инициализирован")

    @commands.Cog.listener()
    async def on_ready(self):
        print("[Warframe] on_ready — очистка канала и первая отправка...")
        info_channel = self.bot.get_channel(WARFRAME_INFO_CHANNEL_ID)
        if info_channel:
            # Очищаем канал
            try:
                await info_channel.purge()
                print("[Warframe] Канал таймеров очищен")
            except Exception as e:
                print(f"[Warframe] Ошибка очистки канала: {e}")

        try:
            data = await fetch_warframe_data()
            print(f"[Warframe] API отвечает, info_channel найден: {info_channel is not None}")
            if info_channel:
                await self._handle_baro(data.get("voidTrader", {}))
                await self._build_and_send_main_embed(data, info_channel)
                print("[Warframe] Начальное обновление выполнено!")
            else:
                print(f"[Warframe] ОШИБКА: Канал {WARFRAME_INFO_CHANNEL_ID} не найден!")
            # Запускаем цикл обновлений
            if not self.warframe_update_loop.is_running():
                self.warframe_update_loop.start()
                print("[Warframe] Цикл обновлений запущен!")
        except Exception as e:
            print(f"[Warframe] ОШИБКА: {e}")
            import traceback
            traceback.print_exc()

    # ==================== ЦИКЛ ====================

    @tasks.loop(minutes=5)
    async def warframe_update_loop(self):
        try:
            data = await fetch_warframe_data()
        except Exception as e:
            logging.error(f"[Warframe] Ошибка API: {e}")
            return

        info_channel = self.bot.get_channel(WARFRAME_INFO_CHANNEL_ID)
        if not info_channel:
            logging.warning("[Warframe] Канал таймеров не найден!")
            return

        await self._handle_baro(data.get("voidTrader", {}))
        await self._build_and_send_main_embed(data, info_channel)

    @warframe_update_loop.before_loop
    async def before_warframe_loop(self):
        await self.bot.wait_until_ready()

    @warframe_update_loop.error
    async def warframe_loop_error(self, error):
        logging.error(f"[Warframe] Ошибка в цикле: {error}")

    # ==================== БАРО КИ'ТИР ====================

    async def _handle_baro(self, vt):
        """Отправляет уведомление о прибытии Баро в канал уведомлений (только 1 раз)."""
        if not vt:
            return

        now = datetime.now(timezone.utc)
        activation = vt.get("activation", "")
        expiry = vt.get("expiry", "")
        location = vt.get("location", "Неизвестно")
        inventory = vt.get("inventory", [])

        is_here = False
        if activation:
            try:
                act_dt = datetime.fromisoformat(activation.replace("Z", "+00:00"))
                is_here = now >= act_dt
            except Exception:
                pass

        if is_here and inventory and not self._baro_notified:
            self._baro_notified = True
            notify_channel = self.bot.get_channel(BARO_NOTIFY_CHANNEL_ID)
            if notify_channel:
                items_text = []
                for item in inventory:
                    name = translate_item(item.get("item", "?"))
                    ducats = item.get("ducats", 0)
                    credits = item.get("credits", 0)
                    items_text.append(f"• **{name}** — <:OldDucats:1512114394094502050> {ducats} | <:Credits:1514175092035424319> {credits}")
                desc = "\n".join(items_text[:20])
                if len(items_text) > 20:
                    desc += f"\n... и ещё {len(items_text) - 20}"
                embed = discord.Embed(
                    title="🛒 Баро Ки'Тир прибыл!",
                    description=desc,
                    color=WARFRAME_COLOR,
                    timestamp=datetime.now(timezone.utc)
                )
                embed.add_field(name="📍 Локация", value=location, inline=True)
                if expiry:
                    try:
                        exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                        diff = exp_dt - now
                        hours = int(diff.total_seconds() // 3600)
                        mins = int((diff.total_seconds() % 3600) // 60)
                        embed.add_field(name="⏳ Улетает через", value=f"~{hours}ч {mins}м", inline=True)
                    except Exception:
                        pass
                embed.set_footer(text="Данные с warframestat.us")
                await notify_channel.send(embed=embed)

        if not is_here and self._baro_notified:
            self._baro_notified = False

    # ==================== СБОРКА ОДНОГО EMBED'А ====================

    async def _build_and_send_main_embed(self, data, info_channel):
        """Собирает один общий embed со всеми таймерами + состояние цепи и отправляет/редактирует."""
        now = datetime.now(timezone.utc)
        all_lines = []

        # --- Баро ---
        vt = data.get("voidTrader", {})
        if vt:
            activation = vt.get("activation", "")
            expiry = vt.get("expiry", "")
            location = vt.get("location", "Неизвестно")

            is_here = False
            if activation:
                try:
                    act_dt = datetime.fromisoformat(activation.replace("Z", "+00:00"))
                    is_here = now >= act_dt
                except Exception:
                    pass

            if not is_here and activation:
                try:
                    act_dt = datetime.fromisoformat(activation.replace("Z", "+00:00"))
                    diff = act_dt - now
                    if diff.total_seconds() > 0:
                        days = int(diff.total_seconds() // 86400)
                        hours = int((diff.total_seconds() % 86400) // 3600)
                        mins = int((diff.total_seconds() % 3600) // 60)
                        all_lines.append(f"🕐 **Баро Ки'Тир** прибудет через: **{days}д {hours}ч {mins}м**")
                    else:
                        all_lines.append("🕐 **Баро Ки'Тир** только что прибыл!")
                except Exception:
                    pass
            elif is_here and expiry:
                try:
                    exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    diff = exp_dt - now
                    if diff.total_seconds() > 0:
                        hours = int(diff.total_seconds() // 3600)
                        mins = int((diff.total_seconds() % 3600) // 60)
                        all_lines.append(f"🕐 **Баро Ки'Тир** улетает через: **{hours}ч {mins}м**")
                    else:
                        all_lines.append("🕐 **Баро Ки'Тир** улетел!")
                except Exception:
                    pass
            all_lines.append(f"📍 **Локация**: {location}")
            all_lines.append("")

        # --- Циклы мира ---
        cetus = data.get("cetusCycle", {})
        if cetus:
            state = CYCLE_TRANSLATIONS.get(cetus.get("state", ""), cetus.get("state", "?"))
            emoji = "☀️" if cetus.get("isDay", True) else "🌙"
            try:
                exp_dt = datetime.fromisoformat(cetus.get("expiry", "").replace("Z", "+00:00"))
                diff = exp_dt - now
                total_mins = max(0, int(diff.total_seconds() // 60))
                hours = total_mins // 60
                mins = total_mins % 60
                all_lines.append(f"{emoji} **Равнины Эйдолона**: {state} (до смены: {hours}ч {mins}м)")
            except Exception:
                all_lines.append(f"{emoji} **Равнины Эйдолона**: {state}")

        vallis = data.get("vallisCycle", {})
        if vallis:
            state = CYCLE_TRANSLATIONS.get(vallis.get("state", ""), vallis.get("state", "?"))
            emoji = "🔥" if vallis.get("isWarm", False) else "❄️"
            try:
                exp_dt = datetime.fromisoformat(vallis.get("expiry", "").replace("Z", "+00:00"))
                diff = exp_dt - now
                total_mins = max(0, int(diff.total_seconds() // 60))
                hours = total_mins // 60
                mins = total_mins % 60
                all_lines.append(f"{emoji} **Долина Сфер**: {state} (до смены: {hours}ч {mins}м)")
            except Exception:
                all_lines.append(f"{emoji} **Долина Сфер**: {state}")

        cambion = data.get("cambionCycle", {})
        if cambion:
            state = CYCLE_TRANSLATIONS.get(cambion.get("state", ""), cambion.get("state", "?"))
            emoji = "🦠" if cambion.get("state", "") == "fass" else "🐛"
            try:
                exp_dt = datetime.fromisoformat(cambion.get("expiry", "").replace("Z", "+00:00"))
                diff = exp_dt - now
                total_mins = max(0, int(diff.total_seconds() // 60))
                hours = total_mins // 60
                mins = total_mins % 60
                all_lines.append(f"{emoji} **Камбионский Дрейф**: {state} (до смены: {hours}ч {mins}м)")
            except Exception:
                all_lines.append(f"{emoji} **Камбионский Дрейф**: {state}")

        all_lines.append("")

        # --- Состояние цепи Дувири ---
        duviri = data.get("duviriCycle", {})
        if duviri:
            state_raw = duviri.get("state", "")
            state_display = DUVIRI_STATE_TRANSLATIONS.get(state_raw, state_raw)
            all_lines.append(f"⚔️ **Цепь Дувири**: {state_display}")

            # Время до смены состояния (цикл 2 часа)
            try:
                exp_dt = datetime.fromisoformat(duviri.get("expiry", "").replace("Z", "+00:00"))
                diff = exp_dt - now
                total_mins = max(0, int(diff.total_seconds() // 60))
                hours = total_mins // 60
                mins = total_mins % 60
                all_lines.append(f"⏳ до смены состояния: {hours}ч {mins}м")
            except Exception:
                pass

        # --- Сборка embed ---
        description = "\n".join(all_lines).strip()
        embed = discord.Embed(
            title="🌌 Warframe — Таймеры и циклы",
            description=description,
            color=WARFRAME_COLOR,
            timestamp=now
        )
        embed.set_footer(text="warframestat.us • обновляется каждые 5 мин")

        # --- Сборка embed с ротацией Дувири ---
        rotation_embed = await self._build_rotation_embed(data)

        # --- Отправка/редактирование ---
        if self._main_message_id:
            try:
                msg = await info_channel.fetch_message(self._main_message_id)
                await msg.edit(embed=embed, view=WarframeView(embed, rotation_embed))
                self._last_main_embed = embed
                self._last_rotation_embed = rotation_embed
                return
            except (discord.NotFound, discord.HTTPException):
                self._main_message_id = None
            except Exception as e:
                logging.error(f"[Warframe] Ошибка редактирования сообщения: {e}")

        try:
            sent = await info_channel.send(embed=embed, view=WarframeView(embed, rotation_embed))
            self._main_message_id = sent.id
            self._last_main_embed = embed
            self._last_rotation_embed = rotation_embed
            logging.info(f"[Warframe] Отправлено главное сообщение в {info_channel.name}")
        except Exception as e:
            logging.error(f"[Warframe] Ошибка отправки: {e}")

    async def _build_rotation_embed(self, data):
        """Создаёт embed с информацией о ротации цепи Дувири."""
        duviri = data.get("duviriCycle", {})
        if not duviri:
            return discord.Embed(
                title="🔄 Ротация цепи Дувири",
                description="Нет данных о ротации.",
                color=WARFRAME_COLOR
            )

        choices = duviri.get("choices", [])
        normal_choices = []
        hard_choices = []
        for choice in choices:
            category = choice.get("categoryKey", "")
            items = choice.get("choices", [])
            if category == "EXC_NORMAL":
                normal_choices = items
            elif category == "EXC_HARD":
                hard_choices = items

        description_parts = []
        if normal_choices:
            description_parts.append(
                "**🌀 Обычная цепь (Варфреймы):**\n" +
                "\n".join(f"• {name}" for name in normal_choices)
            )
        if hard_choices:
            description_parts.append(
                "\n**💀 Стальной путь (Оружие):**\n" +
                "\n".join(f"• {name}" for name in hard_choices)
            )

        if not description_parts:
            description_parts.append("Нет данных о текущей ротации.")

        embed = discord.Embed(
            title="🔄 Ротация цепи Дувири",
            description="\n".join(description_parts),
            color=WARFRAME_COLOR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_footer(text="warframestat.us • обновляется каждые 5 мин")
        return embed

    # ==================== КОМАНДЫ ====================

    @commands.command(name="testbaro")
    @commands.has_permissions(administrator=True)
    async def test_baro(self, ctx):
        """Тест: отправляет уведомление о приходе Баро Ки'Тира."""
        try:
            await ctx.message.delete()
        except Exception:
            pass

        notify_channel = self.bot.get_channel(BARO_NOTIFY_CHANNEL_ID)
        if not notify_channel:
            await ctx.send("❌ Канал уведомлений не найден!", delete_after=10)
            return

        test_items = [
            ("Набор Братон Прайм", 450, 175000),
            ("Набор Сарин Прайм", 500, 200000),
            ("Основная Непрерывность Прайм", 300, 150000),
            ("Аркан Энергиз", 0, 250000),
            ("Призма Скана", 150, 50000),
            ("Чертёж Умбра Форма", 150, 0),
            ("Туманный Ривен Шифр", 20, 75000),
        ]

        items_text = []
        for name, ducats, credits in test_items:
            items_text.append(f"• **{name}** — <:OldDucats:1512114394094502050> {ducats} | <:Credits:1514175092035424319> {credits}")

        embed = discord.Embed(
            title="🛒 Баро Ки'Тир прибыл! (ТЕСТ)",
            description="\n".join(items_text),
            color=WARFRAME_COLOR,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="📍 Локация", value="Kronia Relay (Saturn)", inline=True)
        embed.add_field(name="⏳ Улетает через", value="~24ч 0м", inline=True)
        embed.set_footer(text="ТЕСТОВОЕ СООБЩЕНИЕ")

        try:
            await notify_channel.send(embed=embed)
            await ctx.send("✅ Тестовое уведомление Баро отправлено!", delete_after=10)
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}", delete_after=10)

    @commands.command(name="wf")
    @commands.has_permissions(administrator=True)
    async def wf_manual(self, ctx):
        """Принудительно обновляет Warframe-данные (только для администраторов)."""
        print(f"[Warframe] .wf команда от {ctx.author}")
        try:
            await ctx.message.delete()
        except Exception:
            pass

        try:
            data = await fetch_warframe_data()
            print("[Warframe] .wf: API данные получены")
        except Exception as e:
            print(f"[Warframe] .wf: Ошибка API: {e}")
            await ctx.send(f"❌ Ошибка API: {e}", delete_after=15)
            return

        info_channel = self.bot.get_channel(WARFRAME_INFO_CHANNEL_ID)
        if info_channel:
            await self._handle_baro(data.get("voidTrader", {}))
            await self._build_and_send_main_embed(data, info_channel)
            await ctx.send("✅ Warframe-данные обновлены!", delete_after=10)
        else:
            await ctx.send("❌ Канал таймеров не найден!", delete_after=10)

    @commands.command(name="testwf")
    async def test_wf(self, ctx):
        """Тест: отправляет тестовое сообщение в канал таймеров."""
        info_channel = self.bot.get_channel(WARFRAME_INFO_CHANNEL_ID)
        if not info_channel:
            await ctx.send(f"❌ Канал {WARFRAME_INFO_CHANNEL_ID} не найден!", delete_after=10)
            return
        try:
            msg = await info_channel.send("🔧 Тестовое сообщение от Ордиса...")
            await ctx.send(f"✅ Тестовое сообщение отправлено в {info_channel.mention}!", delete_after=10)
        except Exception as e:
            await ctx.send(f"❌ Ошибка: {e}", delete_after=10)


async def setup(bot):
    await bot.add_cog(Warframe(bot))