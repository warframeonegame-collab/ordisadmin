import discord
from discord.ext import commands
import logging

class RoleManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Настройки для работы с ролями
        self.role_mapping = {
            1492100129342357534: 1505585149046427709,  # ID старой роли: ID новой роли
            # Добавьте другие пары ролей по необходимости
        }
        self.log_channel_id = 1257267587432058993  # ID канала для логов

    @commands.command(name="leave")
    @commands.has_permissions(manage_roles=True)
    async def change_role(self, ctx, member: discord.Member):
        try:
            # Проверяем, есть ли у пользователя роли для замены
            for old_role_id, new_role_id in self.role_mapping.items():
                old_role = discord.utils.get(member.guild.roles, id=old_role_id)
                new_role = discord.utils.get(member.guild.roles, id=new_role_id)
                
                if old_role in member.roles:
                    # Удаляем старую роль
                    await member.remove_roles(old_role, reason="Смена роли")
                    # Добавляем новую роль
                    await member.add_roles(new_role, reason="Смена роли")
                    
                    # Формируем сообщение
                    message = (
                        "Дорогие друзья!\n\n"
                        "Хочу выразить искреннюю благодарность всем участникам клана за ваш неоценимый вклад и активное участие в жизни нашего сообщества. Для меня было большой честью быть частью этого коллектива.\n\n"
                        "К сожалению, в связи с некоторыми обстоятельствами, возникшими в процессе развития клана, я вынужден покинуть пост лидера. Хочу заверить вас, что это решение далось мне нелегко.\n\n"
                        "Все свои полномочия и права я передаю сооснователю клана — @xsk. Уверен, что под его руководством клан продолжит своё успешное развитие.\n\n"
                        "Спасибо за понимание и поддержку! Желаю всем дальнейших успехов и новых достижений!\n\n"
                        "P.S. Сообщение опубликовано по инициативе: {0.mention}".format(ctx.author)
                    )
                    
                    # Отправляем уведомление в лог-канал
                    log_channel = self.bot.get_channel(self.log_channel_id)
                    if log_channel:
                        await log_channel.send(message)
                    
                    await ctx.send(f"✅ Роль для {member.mention} успешно изменена", delete_after=10)
                    return
            
            await ctx.send("❌ У пользователя нет роли для замены", delete_after=10)
            
        except Exception as e:
            logging.error(f"Ошибка при смене роли: {str(e)}")
            await ctx.send("❌ Произошла ошибка при смене роли", delete_after=10)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ У вас нет прав для использования этой команды", delete_after=10)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Ошибка в аргументах команды", delete_after=10)

#async def setup(bot):
    #await bot.add_cog(RoleManager(bot))
