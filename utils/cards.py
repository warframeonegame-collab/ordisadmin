"""PNG-карточки через Pillow (лидерборд, профиль).

Про память: рендер происходит только при вызове, промежуточные объекты
локальны, результат пишется на диск и отправляется как файл.
"""

import logging
import os
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

# ---------- Палитра ----------
BG = (18, 18, 22)             # фон
ROW = (30, 30, 36)            # плашка строки
GOLD = (245, 197, 66)         # акцент Warframe
TEXT = (235, 235, 240)
DIM = (150, 150, 160)

DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"


def _font(size, bold=True):
    """Первый доступный шрифт; в Docker-slim откатываемся на дефолтный."""
    if bold:
        candidates = ("arialbd.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf",
                      "arial.ttf", "DejaVuSans.ttf")
    else:
        candidates = ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf")
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _round_avatar(avatar_bytes, size):
    """Круглая аватарка; None, если аватар не получен/не распарсен."""
    try:
        img = Image.open(BytesIO(avatar_bytes)).convert("RGBA")
        img = img.resize((size, size))
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
        mask = mask.resize((size, size))
        img.putalpha(mask)
        return img
    except Exception as e:
        logger.debug(f"[Cards] Не удалось обработать аватар: {e}")
        return None


async def fetch_avatars(entries, timeout=10):
    """Скачивает аватарки участников.

    entries — список объектов с ключами 'user_id' и 'avatar_url'.
    Возвращает {user_id: bytes|None}.
    """
    results = {}
    async with httpx.AsyncClient(timeout=timeout, headers={"User-Agent": "OrdisBot/1.0"}) as client:
        for entry in entries:
            uid = str(entry["user_id"])
            url = entry.get("avatar_url") or DEFAULT_AVATAR
            try:
                r = await client.get(url)
                results[uid] = r.content if r.status_code == 200 else None
            except Exception:
                results[uid] = None
    return results


def _draw_rank_badge(draw, xy, rank, radius=13):
    x, y = xy
    medal = {1: (212, 175, 55), 2: (170, 170, 178), 3: (163, 106, 55)}
    color = medal.get(rank, (60, 60, 68))
    draw.ellipse((x, y, x + radius * 2, y + radius * 2), fill=color)
    f = _font(15)
    text = str(rank)
    w = draw.textlength(text, font=f)
    draw.text((x + radius - w / 2, y + radius - 9), text, font=f,
              fill=(20, 20, 24) if rank <= 3 else DIM)


def build_leaderboard_card(entries, avatars, path):
    """Рисует карточку топ-10 и сохраняет на диск.

    entries — [{user_id, nickname, level}]; avatars — {user_id: bytes|None}.
    Возвращает путь или None при ошибке.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rows = entries[:10]
        W, ROW_H, HEADER_H = 560, 56, 64
        H = HEADER_H + len(rows) * ROW_H + 12

        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)

        draw.text((16, 16), "⚡ Таблица лидеров клана", font=_font(26), fill=GOLD)
        draw.text((W - 110, 24), "TOP-10", font=_font(20), fill=DIM)

        for i, row in enumerate(rows):
            uid = str(row["user_id"])
            y = HEADER_H + i * ROW_H
            rank = i + 1
            nickname = (row.get("nickname") or "Участник")[:22]

            draw.rounded_rectangle((10, y, W - 10, y + ROW_H - 6), radius=10, fill=ROW)
            _draw_rank_badge(draw, (26, y + 10), rank)

            size = 36
            raw = avatars.get(uid)
            avatar = _round_avatar(raw, size) if raw else None
            if avatar:
                img.paste(avatar, (62, y + 5), avatar)
            else:
                x0, y0 = 62, y + 5
                draw.ellipse((x0, y0, x0 + size, y0 + size), fill=(60, 60, 68))
                f = _font(18)
                initial = nickname[0].upper() if nickname and nickname[0].isalpha() else "?"
                w = draw.textlength(initial, font=f)
                draw.text((x0 + size / 2 - w / 2, y0 + 8), initial, font=f, fill=DIM)

            draw.text((112, y + 12), nickname, font=_font(18), fill=TEXT)
            lvl_text = f"LVL {row.get('level', 1)}"
            lw = draw.textlength(lvl_text, font=_font(16))
            draw.text((W - 30 - lw, y + 14), lvl_text, font=_font(16), fill=GOLD)

        img.save(path, "PNG")
        return path
    except Exception as e:
        logger.error(f"[Cards] Ошибка рендера карточки лидерборда: {e}")
        return None


def build_profile_card(nickname, level, avatar_bytes, card_path):
    """Компактная карточка профиля.

    nickname — отображаемое имя; avatar_bytes — содержимое PNG/JPG с аватаром
    (или None → заглушка). Возвращает путь или None при ошибке.
    ВАЖНО: это синхронная (блокирующая) функция — вызывать из кода бота
    напрямую в обработчиках допустимо только для мелких рендеров.
    """
    try:
        os.makedirs(os.path.dirname(card_path), exist_ok=True)
        W, H = 480, 150
        img = Image.new("RGB", (W, H), BG)
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((10, 10, W - 10, H - 10), radius=14, fill=(26, 26, 32),
                               outline=(45, 45, 55), width=2)

        size = 96
        avatar = _round_avatar(avatar_bytes, size) if avatar_bytes else None
        x0, y0 = 26, 27
        if avatar:
            img.paste(avatar, (x0, y0), avatar)
        else:
            draw.ellipse((x0, y0, x0 + size, y0 + size), fill=(60, 60, 68))
            f = _font(34)
            initial = (nickname or "?")[0].upper()
            w = draw.textlength(initial, font=f)
            draw.text((x0 + size / 2 - w / 2, y0 + 28), initial, font=f, fill=DIM)

        draw.text((142, 30), (nickname or "Участник")[:20], font=_font(24), fill=TEXT)
        draw.text((142, 66), f"Уровень: {level}", font=_font(20), fill=GOLD)

        img.save(card_path, "PNG")
        return card_path
    except Exception as e:
        logger.error(f"[Cards] Ошибка рендера карточки профиля: {e}")
        return None
