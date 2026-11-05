import discord
from discord.ext import commands
from utils.database import Database

# Порядковый список достижений (ключ → описание). Уровневые + специальные.
ACHIEVEMENTS = [
    ("15",       "🌟", "Испытание: Уровень 15",         "Достигните 15 уровня активности"),
    ("25",       "🔥", "Испытание: Уровень 25",         "Достигните 25 уровня активности"),
    ("50",       "💎", "Испытание: Уровень 50",         "Достигните 50 уровня активности"),
    ("75",       "👑", "Испытание: Уровень 75",         "Достигните 75 уровня активности"),
    ("100",      "🏆", "Испытание: Уровень 100",        "Достигните 100 уровня активности"),
    ("voice10",  "🎧", "Комм-офицер I",                 "Проведите 10 часов в голосовых каналах"),
    ("voice50",  "📡", "Комм-офицер II",                "Проведите 50 часов в голосовых каналах"),
    ("first_questionnaire", "📋", "Новобранец клана", "Заполните анкету рекрута после верификации"),
    # Роли за уровни (выдаются в maybe_award_level, profile.py)
    ("role_5",      "🥉", "Роль «Уровень 5+\"",   "Получите авто-роль за 5 уровень"),
    ("role_10",     "🥈", "Роль «Уровень 10+\"",  "Получите авто-роль за 10 уровень"),
    ("role_15",     "🥇", "Роль «Уровень 15+\"",  "Получите авто-роль за 15 уровень"),
    ("role_20",     "🎖️", "Роль «Уровень 20+\"", "Получите авто-роль за 20 уровень"),
]

ACHIEVEMENT_KEYS = [k for k, *_ in ACHIEVEMENTS]


class Achievements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    async def get_achievements_embed(self, member: discord.Member, author: discord.Member) -> discord.Embed:
        """Создаёт embed с достижениями для указанного пользователя."""
        user_data = self.db.get_user(member.id)
        achievements = user_data.get('achievements', {})

        desc_lines = []
        for key, emoji, name, desc in ACHIEVEMENTS:
            unlocked = achievements.get(key, False)
            if unlocked:
                desc_lines.append(f"{emoji} ~~{name}~~ ✅ — {desc}")
            else:
                desc_lines.append(f"{emoji} **{name}** ❌ — {desc}")

        emb = discord.Embed(
            title=f"🏆 Достижения {member.display_name}",
            description="\n\n".join(desc_lines) if desc_lines else "Пока нет достижений.",
            color=discord.Color.gold()
        )
        emb.set_thumbnail(url=member.display_avatar.url)
        emb.set_footer(text=f"Запрошено {author.display_name}", icon_url=author.display_avatar.url)
        return emb


async def setup(bot):
    await bot.add_cog(Achievements(bot))