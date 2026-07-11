import discord
from discord.ext import commands, tasks
import httpx
import logging
import asyncio
import re
import hashlib
from datetime import datetime, timezone, timedelta
from playwright.async_api import async_playwright

WARFRAME_API = "https://api.warframestat.us/pc/"
WARFRAME_COLOR = discord.Color.from_rgb(255, 185, 15)
TENNOCON_DROPS_URL = "https://www.tennocon.com/en/digital-info#drops"

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

TWITCH_DROP_TRANSLATIONS = {
    "TennoCon 2026 Is Live – Watch Now!": "TennoCon 2026 — Смотрите прямой эфир!",
    "TennoCon 2026 Merch Available Now!": "Мерч TennoCon 2026 уже доступен!",
    "TennoCon 2026 Darvo Deals": "Предложения Дарво на TennoCon 2026",
    "Watch Now: Official Cosplay Contest": "Смотрите: Официальный конкурс косплея",
    "Watch Now: TennoConcert 2026": "Смотрите: TennoConcert 2026",
    "Mesa Heirloom Collection Available Now": "Коллекция Мисы «Наследие» уже доступен",
    "Baro Ki'Teer's Relay Now Open": "Реле Баро Ки'Тиира теперь открыто",
    "Mesa Heirloom: Hotfix 43.0.7": "Mesa Heirloom: Хотфикс 43.0.7",
    "TennoCon 2026 Is Live": "TennoCon 2026 в прямом эфире",
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


def translate_twitch_message(msg: str) -> str:
    """Переводит заголовок новости Twitch на русский."""
    return TWITCH_DROP_TRANSLATIONS.get(msg, msg)


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
        self._notified_news_ids = set()
        self._twitch_drops_message_id = None
        self._last_tennocon_drops_hash = None
        self._tennocon_drops_message_id = None
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
                await self._check_twitch_drops(data)
                await self._send_tennocon_drops()
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
        await self._check_twitch_drops(data)
        await self._send_tennocon_drops()

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

    # ==================== TWITCH DROPS ====================

    async def _check_twitch_drops(self, data):
        """Проверяет новости на наличие Twitch Drops и отправляет уведомления."""
        news_list = data.get("news", [])
        if not news_list:
            return

        now = datetime.now(timezone.utc)
        notify_channel = self.bot.get_channel(BARO_NOTIFY_CHANNEL_ID)
        if not notify_channel:
            return

        for news_item in news_list:
            news_id = news_item.get("id", "")
            if not news_id:
                continue

            # Проверяем, связано ли с Twitch
            link = news_item.get("link", "")
            message = news_item.get("message", "")
            is_twitch = "twitch.tv" in link.lower() or "twitch" in message.lower()

            if not is_twitch:
                continue

            # Проверяем, не отправляли ли уже
            if news_id in self._notified_news_ids:
                continue

            # Получаем перевод
            ru_translations = news_item.get("translations", {}).get("ru", "")
            title = ru_translations if ru_translations else translate_twitch_message(message)

            # Форматируем даты
            activation = news_item.get("date", "")
            expiry = news_item.get("expiry", "")

            time_str = ""
            if activation:
                try:
                    act_dt = datetime.fromisoformat(activation.replace("Z", "+00:00"))
                    act_local = act_dt.strftime("%d.%m.%Y %H:%M")
                    time_str = f"📅 **Начало:** {act_local} МСК"
                except Exception:
                    time_str = f"📅 **Начало:** {activation}"

            if expiry:
                try:
                    exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
                    exp_local = exp_dt.strftime("%d.%m.%Y %H:%M")
                    time_str += f"\n📅 **Окончание:** {exp_local} МСК"
                except Exception:
                    time_str += f"\n📅 **Окончание:** {expiry}"

            # Собираем embed
            embed = discord.Embed(
                title=f"🎮 Twitch Drops: {title}",
                description=time_str,
                color=WARFRAME_COLOR,
                timestamp=now
            )

            # Добавляем ссылку на стрим
            if link:
                embed.add_field(name="🔗 Ссылка", value=f"[Смотреть на Twitch]({link})", inline=False)

            embed.set_footer(text="warframestat.us • обновляется каждые 5 мин")

            # Отправляем
            try:
                await notify_channel.send(embed=embed)
                self._notified_news_ids.add(news_id)
                print(f"[Warframe] Отправлено уведомление о Twitch Drops: {title}")
            except Exception as e:
                logging.error(f"[Warframe] Ошибка отправки Twitch Drops: {e}")

    # ==================== TENNOCON DROPS ====================

    def _is_edt(self, date: datetime) -> bool:
        """Определяет, действует ли летнее время (EDT) в указанную дату.
        
        В США переход на летнее время: второе воскресенье марта в 2:00 AM
        Переход на зимнее время: первое воскресенье ноября в 2:00 AM
        """
        month = date.month
        day = date.day
        
        # Определяем день недели (0=понедельник, 6=воскресенье)
        weekday = date.weekday()
        
        if month == 3:
            # Второе воскресенье марта
            # Находим первое воскресенье
            first_sunday = 7 - weekday if weekday < 6 else 1
            second_sunday = first_sunday + 7
            return day >= second_sunday
        elif month == 11:
            # Первое воскресенье ноября
            first_sunday = 7 - weekday if weekday < 6 else 1
            return day < first_sunday
        elif month in [4, 5, 6, 7, 8, 9, 10]:
            # Апрель-октябрь: летнее время
            return True
        else:
            # Декабрь-февраль: зимнее время
            return False

    async def _fetch_tennocon_drops(self):
        """Парсит страницу TennoCon и возвращает список дропов с временем в МСК."""
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(TENNOCON_DROPS_URL, wait_until="domcontentloaded", timeout=30000)
                
                # Используем селекторы Playwright вместо regex
                cards = await page.query_selector_all('div.StreamCard')
                
                months_map = {"July": 7, "August": 8, "September": 9}

                drops = []
                logging.info(f"[Warframe] Найдено карточек TennoCon: {len(cards)}")

                for idx, card in enumerate(cards):
                    try:
                        # Извлекаем название
                        title_elem = await card.query_selector('h3')
                        if not title_elem:
                            logging.warning(f"[Warframe] Карточка {idx}: нет заголовка h3")
                            continue
                        name_raw = (await title_elem.inner_text()).strip()
                        logging.info(f"[Warframe] Карточка {idx}: название = '{name_raw}'")

                        # Извлекаем дату
                        date_elem = await card.query_selector('.StreamCard-datetime div')
                        if not date_elem:
                            logging.warning(f"[Warframe] Карточка {idx}: нет даты")
                            continue
                        date_text = (await date_elem.inner_text()).strip()
                        logging.info(f"[Warframe] Карточка {idx}: дата текст = '{date_text}'")
                        # Парсим "July 10"
                        parts = date_text.split()
                        if len(parts) < 2:
                            logging.warning(f"[Warframe] Карточка {idx}: недостаточно частей в дате")
                            continue
                        month_name = parts[0]
                        day = int(parts[1])

                        # Извлекаем время начала и конца
                        time_elems = await card.query_selector_all('.StreamCard-time div')
                        if len(time_elems) < 2:
                            logging.warning(f"[Warframe] Карточка {idx}: меньше 2 time div")
                            continue

                        # Первый div - дата (уже обработана), второй - диапазон времени
                        # Время в формате "7 p.m. ET – 8:30 p.m. ET"
                        time_range_text = (await time_elems[1].inner_text()).strip()
                        logging.info(f"[Warframe] Карточка {idx}: время текст = '{time_range_text}'")

                        # Парсим диапазон времени "7:00 p.m. ET – 8:30 p.m. ET" или "7 p.m. ET – 8:30 p.m. ET"
                        time_range_match = re.match(r'(\d{1,2})(?::(\d{2}))?\s*(a\.m\.|p\.m\.)\s*ET\s*[–-]\s*(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.)', time_range_text)
                        
                        if not time_range_match:
                            logging.warning(f"[Warframe] Карточка {idx}: не удалось распарсить время")
                            continue

                        start_h = int(time_range_match.group(1))
                        start_m = int(time_range_match.group(2)) if time_range_match.group(2) else 0
                        start_ampm = time_range_match.group(3)
                        end_h = int(time_range_match.group(4))
                        end_m = int(time_range_match.group(5))
                        end_ampm = time_range_match.group(6)

                        # Конвертируем в 24-часовой формат
                        if start_ampm == "p.m." and start_h != 12:
                            start_h += 12
                        elif start_ampm == "a.m." and start_h == 12:
                            start_h = 0
                        if end_ampm == "p.m." and end_h != 12:
                            end_h += 12
                        elif end_ampm == "a.m." and end_h == 12:
                            end_h = 0

                        month = months_map.get(month_name, 7)
                        year = 2026

                        try:
                            # Определяем, летнее или зимнее время
                            start_dt = datetime(year, month, day, start_h, start_m)
                            end_dt = datetime(year, month, day, end_h, end_m)
                            
                            is_edt = self._is_edt(start_dt)
                            logging.info(f"[Warframe] Карточка {idx}: дата {year}-{month}-{day}, is_edt={is_edt}")
                            
                            if is_edt:
                                # EDT (летнее время, UTC-4) → МСК (UTC+3): прибавляем 7 часов
                                ET_OFFSET = timedelta(hours=7)
                            else:
                                # EST (зимнее время, UTC-5) → МСК (UTC+3): прибавляем 8 часов
                                ET_OFFSET = timedelta(hours=8)
                            
                            start_msk = start_dt + ET_OFFSET
                            end_msk = end_dt + ET_OFFSET
                            logging.info(f"[Warframe] Карточка {idx}: ET {start_h}:{start_m:02d} → MSK {start_msk.strftime('%H:%M')} (смещение +{ET_OFFSET.total_seconds()/3600:.0f}ч)")
                        except Exception as e:
                            logging.error(f"[Warframe] Карточка {idx}: ошибка конвертации времени: {e}")
                            continue

                        # Извлекаем описание/награду
                        desc_elem = await card.query_selector('.StreamCard-description')
                        reward_text = ""
                        if desc_elem:
                            reward_text = (await desc_elem.inner_text()).strip()
                            reward_text = re.sub(r'\s+', ' ', reward_text).strip()
                            # Убираем "subject to change"
                            reward_text = re.sub(r'\*subject to change.*?\*', '', reward_text, flags=re.IGNORECASE).strip()
                            if len(reward_text) > 250:
                                reward_text = reward_text[:250] + "..."
                        logging.info(f"[Warframe] Карточка {idx}: награда = '{reward_text[:100]}'")

                        drops.append({
                            "name": name_raw,
                            "reward": reward_text,
                            "start_msk": start_msk,
                            "end_msk": end_msk,
                        })
                        logging.info(f"[Warframe] Карточка {idx}: добавлен дроп {start_msk.strftime('%H:%M')} — {end_msk.strftime('%H:%M')} МСК")
                    except Exception as e:
                        logging.error(f"[Warframe] Ошибка парсинга карточки: {e}")
                        continue
                
                await browser.close()
        except Exception as e:
            logging.error(f"[Warframe] Ошибка загрузки TennoCon страницы: {e}")
            return []

        logging.info(f"[Warframe] Успешно спарсено дропов: {len(drops)}")
        drops.sort(key=lambda d: d["start_msk"])
        return drops

    async def _send_tennocon_drops(self):
        """Парсит TennoCon страницу и отправляет/редактирует embed с дропами."""
        drops = await self._fetch_tennocon_drops()
        if not drops:
            return

        # Хеш для проверки изменений
        drops_hash = hashlib.md5(str(drops).encode()).hexdigest()
        if drops_hash == self._last_tennocon_drops_hash:
            return
        self._last_tennocon_drops_hash = drops_hash

        # Отправляем в канал уведомлений (как и Баро)
        notify_channel = self.bot.get_channel(BARO_NOTIFY_CHANNEL_ID)
        if not notify_channel:
            logging.warning(f"[Warframe] Канал уведомлений {BARO_NOTIFY_CHANNEL_ID} не найден!")
            return

        # Группируем по дням
        day_data = {}
        month_ru = {"July": "июля", "August": "августа", "September": "сентября"}
        day_names = {4: "Пятница", 5: "Суббота", 6: "Воскресенье"}

        for d in drops:
            date_key = d["start_msk"].strftime("%d.%m.%Y")
            if date_key not in day_data:
                day_data[date_key] = []
            day_data[date_key].append(d)

        now = datetime.now(timezone.utc)
        description_parts = []

        for date_key in sorted(day_data.keys()):
            day_drops = day_data[date_key]
            day_dt = datetime.strptime(date_key, "%d.%m.%Y")
            day_name = day_names.get(day_dt.weekday(), "")
            month_en = day_dt.strftime("%B")

            # Заголовок дня
            description_parts.append(
                f"**🗓 {day_dt.day} {month_ru.get(month_en, month_en)} {day_dt.year} ({day_name})**\n"
            )

            for d in day_drops:
                start_str = d["start_msk"].strftime("%H:%M")
                end_str = d["end_msk"].strftime("%H:%M")
                description_parts.append(f"🕐 **{start_str} — {end_str} МСК** → {d['name']}")
                if d["reward"]:
                    description_parts.append(f"  • {d['reward']}")
                description_parts.append("")

        description = "\n".join(description_parts).strip()

        embed = discord.Embed(
            title="🎮 Twitch Drops TennoCon 2026",
            description=description,
            color=WARFRAME_COLOR,
            timestamp=now
        )
        embed.add_field(
            name="🔗 Ссылка",
            value="[Смотреть на Twitch](https://www.twitch.tv/warframe)",
            inline=False
        )
        embed.set_footer(text="tennocon.com • время указано в МСК")

        # Отправляем или редактируем
        if self._tennocon_drops_message_id:
            try:
                msg = await notify_channel.fetch_message(self._tennocon_drops_message_id)
                await msg.edit(embed=embed)
                return
            except (discord.NotFound, discord.HTTPException):
                self._tennocon_drops_message_id = None
            except Exception as e:
                logging.error(f"[Warframe] Ошибка редактирования TennoCon дропов: {e}")

        try:
            sent = await notify_channel.send(embed=embed)
            self._tennocon_drops_message_id = sent.id
            print("[Warframe] Отправлены TennoCon дропы")
        except Exception as e:
            logging.error(f"[Warframe] Ошибка отправки TennoCon дропов: {e}")

    # ==================== КОМАНДЫ ====================

    @commands.command(name="update")
    @commands.has_permissions(administrator=True)
    async def update_command(self, ctx):
        """Принудительно обновляет все данные (Warframe, лидерборд)."""
        try:
            await ctx.message.delete()
        except Exception:
            pass

        await ctx.send("🔄 Запускаю обновление всех данных...", delete_after=5)
        
        try:
            # Обновляем Warframe данные
            data = await fetch_warframe_data()
            info_channel = self.bot.get_channel(WARFRAME_INFO_CHANNEL_ID)
            if info_channel:
                await self._handle_baro(data.get("voidTrader", {}))
                await self._build_and_send_main_embed(data, info_channel)
                await self._check_twitch_drops(data)
                # Сбрасываем хеш для принудительного обновления TennoCon
                self._last_tennocon_drops_hash = None
                await self._send_tennocon_drops()
            
            # Обновляем таблицу лидеров
            leaderboard_cog = self.bot.get_cog("Leaderboard")
            if leaderboard_cog:
                await leaderboard_cog.update_leaderboard_manual(ctx)
            
            await ctx.send("✅ Все данные обновлены! (Warframe + Лидерборд)", delete_after=10)
        except Exception as e:
            await ctx.send(f"❌ Ошибка обновления: {e}", delete_after=15)
            logging.error(f"[Warframe] Ошибка в update: {e}")


async def setup(bot):
    await bot.add_cog(Warframe(bot))