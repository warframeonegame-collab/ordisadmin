"""PNG-карточки через Pillow (лидерборд, профиль) — Warframe × Cyberpunk.

Про память: рендер происходит только при вызове, промежуточные объекты
локальны, результат пишется на диск и отправляется как файл.
"""

import logging
import os
from io import BytesIO

import httpx
from PIL import Image, ImageDraw, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

# ---------- Палитра: Warframe gold × Neon cyberspace ----------
BG = (10, 11, 18)                 # глубокий космос
PANEL = (16, 18, 28)              # панель
PANEL_EDGE = (54, 44, 26)         # кромка панели (тёплый тёмный)
GOLD = (240, 201, 106)            # Orokin gold
GOLD_DIM = (176, 141, 63)
CYAN = (0, 229, 255)              # неон
CYAN_DIM = (0, 122, 140)
MAGENTA = (255, 46, 136)
TEXT = (238, 242, 248)
DIM = (128, 136, 152)

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


def _chamfer(W, H, cut, fill=None, outline=None, width=1):
    """Срезанный (chamfer) прямоугольник — примитив киберпанк-стиля."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    points = [
        (cut, 0), (W, 0), (W, H - cut),           # верх-право → низ-право (верхний правый прямой)
        (W - cut, H), (0, H), (0, cut),           # низ-лево срезан, верх-лево срезан
    ]
    d.polygon(points, fill=fill, outline=outline, width=width)
    return layer


def _scanlines(img, opacity=46):
    """Сканлайны CRT-монитора."""
    W, H = img.size
    lines = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(lines)
    for y in range(0, H, 3):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, opacity))
    img.alpha_composite(lines)
    return img


def _hex_badge(size):
    """Гексагон Warframe-стиля (уровень)."""
    layer = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    pts = [
        (0.5, 0.04), (0.93, 0.28), (0.93, 0.72),
        (0.5, 0.96), (0.07, 0.72), (0.07, 0.28),
    ]
    pts = [(x * size * 4, y * size * 4) for x, y in pts]
    d.polygon(pts, fill=(28, 26, 20, 255))
    # Золотая кромка
    outer = [(x * size * 4, y * size * 4) for x, y in pts]
    d.polygon(outer, outline=GOLD, width=size // 5)
    layer = layer.resize((size, size), Image.LANCZOS)
    layer = layer.filter(ImageFilter.SMOOTH)
    return layer


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


def _text_glow(draw, xy, text, font, color, glow=(CYAN,), radius=2):
    """Неоновый текст: цветное свечение из нескольких проходов + основной."""
    x, y = xy
    for offset in range(radius, 0, -1):
        for g in glow:
            draw.text((x + offset, y + offset), text, font=font, fill=tuple(g) + (110,))
    draw.text((x, y), text, font=font, fill=color)


async def fetch_avatars(entries, timeout=10):
    """Скачивает аватарки участников.

    entries — список словарей с 'user_id' и 'avatar_url'.
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


def build_leaderboard_card(entries, avatars, path):
    """Рендерит топ-10 по уровню в Warframe × Cyberpunk стиле.

    entries — [{user_id, nickname, level}]; avatars — {user_id: bytes|None}.
    Возвращает путь или None при ошибке.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        rows = entries[:10]
        W, ROW_H, HEADER_H, GAP = 600, 56, 74, 6
        H = HEADER_H + len(rows) * (ROW_H + GAP) + 10

        img = Image.new("RGBA", (W, H), BG + (255,))
        draw = ImageDraw.Draw(img)

        # ---- Хедер: золотая рамка + никмен титул ----
        header = _chamfer(W, HEADER_H, 14, fill=PANEL + (255,), outline=GOLD_DIM + (255,), width=2)
        img.alpha_composite(header, (0, 0))
        draw = ImageDraw.Draw(img)
        # Верхняя полоска-риска
        draw.line([(18, 22), (W - 40, 22)], fill=GOLD + (200,), width=2)
        _text_glow(draw, (20, 32), "◆ RANK PROTOCOL · СИСТЕМА РЕЙТИНГА", _font(19),
                   GOLD, glow=[GOLD, CYAN_DIM])
        draw.text((W - 130, 34), "TOP-10", font=_font(22), fill=CYAN + (235,))

        max_level = max((r.get('level', 1) for r in rows), default=1) or 1

        for i, row in enumerate(rows):
            uid = str(row["user_id"])
            y = HEADER_H + 2 + i * (ROW_H + GAP)
            rank = i + 1
            nickname = (row.get("nickname") or "Неизвестно")[:20]

            # Панель строки (чамфер) — топ-3 с золотым контуром
            edge = (GOLD if rank <= 3 else (CYAN_DIM if rank <= 5 else PANEL_EDGE))
            edge_full = (GOLD if rank <= 3 else CYAN if rank <= 5 else (70, 60, 40))
            row_img = _chamfer(W - 8, ROW_H, 10, fill=PANEL + (255,),
                               outline=edge_full + (230 if rank <= 5 else 120,), width=2)
            img.alpha_composite(row_img, (4, y))
            draw = ImageDraw.Draw(img)

            # Ранк: номер в цветном чипе
            medal = {1: GOLD, 2: (200, 200, 210), 3: (200, 130, 70)}
            rank_color = medal.get(rank, CYAN if rank <= 5 else DIM)
            draw.text((22, y + 12), f"{rank:02d}", font=_font(26), fill=rank_color + (255,))
            draw.line([(52, y + 10), (52, y + ROW_H - 10)], fill=(60, 55, 40) + (200,), width=1)

            # Аватар
            size = 38
            raw = avatars.get(uid)
            avatar = _round_avatar(raw, size) if raw else None
            x0, y0 = 68, y + 8
            if avatar:
                # золотое/циановое кольцо вокруг
                ring = ImageDraw.Draw(img)
                ring.ellipse((x0 - 2, y0 - 2, x0 + size + 2, y0 + size + 2),
                             outline=edge + (255,), width=2)
                img.paste(avatar, (x0, y0), avatar)
            else:
                ring = ImageDraw.Draw(img)
                ring.ellipse((x0, y0, x0 + size, y0 + size), fill=(40, 40, 48) + (255,))
                f = _font(18)
                initial = nickname[0].upper() if nickname and nickname[0].isalpha() else "?"
                w = draw.textlength(initial, font=f)
                draw.text((x0 + size / 2 - w / 2, y0 + 8), initial, font=f, fill=DIM + (255,))

            # Имя + полоска уровня до 100%
            draw.text((120, y + 10), nickname, font=_font(19), fill=TEXT + (255,))
            bar_x, bar_y, bar_w, bar_h = 120, y + 34, (W - 210) - 120, 8
            frac = min(1.0, (row.get('level', 1) or 1) / max_level)
            draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                           fill=(40, 42, 52) + (255,))
            if frac > 0:
                fill_w = max(4, int(bar_w * frac))
                color = GOLD if rank <= 3 else CYAN
                # градиентная заливка сегментами (Варфрейм-стиль)
                seg_w = 9
                for s in range(bar_x, bar_x + fill_w, seg_w):
                    end = min(s + seg_w - 2, bar_x + fill_w)
                    draw.rectangle((s, bar_y, end, bar_y + bar_h), fill=color + (235,))
            # Уровень справа
            lvl_text = f"LVL {row.get('level', 1)}"
            layer_hex = _hex_badge(44)
            img.alpha_composite(layer_hex, (W - 62, y + 6))
            draw = ImageDraw.Draw(img)
            lw = draw.textlength(lvl_text.replace('LVL ', ''), font=_font(17))
            draw.text((W - 62 + 22 - lw / 2, y + 14), lvl_text.replace('LVL ', ''),
                      font=_font(17), fill=GOLD + (255,))

        _scanlines(img)
        img.convert("RGB").save(path, "PNG")
        return path
    except Exception as e:
        logger.error(f"[Cards] Ошибка рендера лидерборда: {e}")
        return None


def build_profile_card(nickname, level, avatar_bytes, card_path):
    """Рендерит карточку профиля в Warframe × Cyberpunk стиле.

    nickname — полученный ник; avatar_bytes — байты PNG/JPG (или None).
    Возвращает путь или None при ошибке.
    """
    try:
        os.makedirs(os.path.dirname(card_path), exist_ok=True)
        W, H = 640, 240

        img = Image.new("RGBA", (W, H), BG + (255,))
        draw = ImageDraw.Draw(img)

        # ---- Главная панель с двойным чамфером ----
        panel = _chamfer(W - 16, H - 16, 18, fill=PANEL + (255,),
                         outline=GOLD_DIM + (255,), width=3)
        img.alpha_composite(panel, (8, 8))
        draw = ImageDraw.Draw(img)

        # Внутренняя тонкая кромка (неон)
        inner = _chamfer(W - 34, H - 34, 14, fill=(0, 0, 0, 0),
                         outline=CYAN + (70,), width=1)
        img.alpha_composite(inner, (17, 17))

        # ---- Верхний титул-риска ----
        draw.line([(40, 34), (150, 34)], fill=GOLD + (220,), width=2)
        _text_glow(draw, (158, 22), "ORDIS OS // ARASAKA PLAZA", _font(16),
                   GOLD_DIM, glow=[GOLD_DIM])
        draw.line([(386, 34), (W - 40, 34)], fill=GOLD + (220,), width=2)

        # ---- Аватар в неоновом кольце + уголки ----
        size = 120
        avatar = _round_avatar(avatar_bytes, size) if avatar_bytes else None
        x0, y0 = 40, 72
        ring = ImageDraw.Draw(img)
        ring.ellipse((x0 - 4, y0 - 4, x0 + size + 4, y0 + size + 4),
                     outline=CYAN + (140,), width=3)
        if avatar:
            img.paste(avatar, (x0, y0), avatar)
        else:
            ring.ellipse((x0, y0, x0 + size, y0 + size), fill=(40, 40, 48) + (255,))
            f = _font(46)
            initial = (nickname or "?")[0].upper()
            w = draw.textlength(initial, font=f)
            draw.text((x0 + size / 2 - w / 2, y0 + 34), initial, font=f, fill=DIM + (255,))

        # ---- Имя: крупный, золотой, с неоном ----
        _text_glow(draw, (190, 68), (nickname or "Неизвестно")[:18], _font(30),
                   GOLD, glow=[GOLD, CYAN_DIM], radius=3)
        draw = ImageDraw.Draw(img)

        # ---- Сегментированный прогресс-бар ----
        bar_x, bar_y, bar_w, bar_h = 192, 112, 300, 10
        draw.rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                       fill=(40, 42, 52) + (255,))
        # Текущий уровень как доля шкалы (уровень / 30 визуально, зацикливание сегментов)
        frac = ((int(level) - 1) % 10) / 10 if level else 0
        if level == 10 or frac == 0 and level:
            frac = 1.0 if (level or 0) % 10 == 0 else frac
        elif level:
            pass
        seg_w = 17
        fill_w = max(8, int(bar_w * frac))
        for s in range(bar_x, bar_x + fill_w, seg_w):
            end = min(s + seg_w - 3, bar_x + fill_w)
            draw.rectangle((s, bar_y, end, bar_y + bar_h), fill=GOLD + (235,))

        # ---- Гексагон уровня ----
        hex_size = 96
        layer_hex = _hex_badge(hex_size)
        img.alpha_composite(layer_hex, (W - 118, H - 122))
        draw = ImageDraw.Draw(img)
        lvl = str(level or 0)
        lw = draw.textlength(lvl, font=_font(34))
        draw.text((W - 118 + 48 - lw / 2, H - 122 + 28), lvl, font=_font(34),
                  fill=GOLD + (255,))
        sub = "LVL"
        sw = draw.textlength(sub, font=_font(13))
        draw.text((W - 118 + 48 - sw / 2, H - 122 + 62), sub, font=_font(13),
                  fill=CYAN + (200,))

        # ---- Уголки-скобы (скан-рамка) ----
        bracket = CYAN + (120,)
        for (cx, cy, sx, sy) in [(24, 24, 1, 1), (W - 24, 24, -1, 1),
                                 (24, H - 24, 1, -1), (W - 24, H - 24, -1, -1)]:
            draw.line([(cx, cy + 16 * sy), (cx, cy)], fill=bracket, width=2)
            draw.line([(cx, cy), (cx + 16 * sx, cy)], fill=bracket, width=2)

        _scanlines(img, opacity=38)
        img.convert("RGB").save(card_path, "PNG")
        return card_path
    except Exception as e:
        logger.error(f"[Cards] Ошибка рендера профиля: {e}")
        return None
