import discord
from discord.ext import commands
from utils.database import Database

ACHIEVEMENT_NAMES = {
    "15": "🌟 Испытание: Уровень 15",
    "25": "🔥 Испытание: Уровень 25",
    "50": "💎 Испытание: Уровень 50",
    "75": "👑 Испытание: Уровень 75",
    "100": "🏆 Испытание: Уровень 100",
}

ACHIEVEMENT_DESCRIPTIONS = {
    "15": "Достигните 15 уровня активности",
    "25": "Достигните 25 уровня активности",
    "50": "Достигните 50 уровня активности",
    "75": "Достигните 75 уровня активности",
    "100": "Достигните 100 уровня активности",
}

ACHIEVEMENT_EMOJIS = {
    "15": "🌟",
    "25": "🔥",
    "50": "💎",
    "75": "👑",
    "100": "🏆",
}


class Achievements(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = Database()

    async def get_achievements_embed(self, member: discord.Member, author: discord.Member) -> discord.Embed:
        """Создаёт embed с достижениями для указанного пользователя."""
        user_data = self.db.get_user(member.id)
        achievements = user_data.get('achievements', {})

        desc_lines = []
        for lvl in ["15", "25", "50", "75", "100"]:
            unlocked = achievements.get(lvl, False)
            emoji = ACHIEVEMENT_EMOJIS.get(lvl, "🔒")
            name = ACHIEVEMENT_NAMES.get(lvl, f"Уровень {lvl}")
            desc = ACHIEVEMENT_DESCRIPTIONS.get(lvl, "")
            if unlocked:
                desc_lines.append(f"{emoji} ~~{name}~~ ✅ — {desc}")
            else:
                desc_lines.append(f"{emoji} **{name}** ❌ — {desc}")

        emb = discord.Embed(
            title=f"🏆 Достижения {member.display_name}",
            description="\n\n".join(desc_lines) if desc_lines else "Пока нет достижений.",
            color=discord.Color.gold()
        )
        emb.set_thumbnail(url=member.avatar.url)
        emb.set_footer(text=f"Запрошено {author.display_name}", icon_url=author.avatar.url)
        return emb


async def setup(bot):
    await bot.add_cog(Achievements(bot))