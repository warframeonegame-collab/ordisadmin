import discord
from discord.ext import commands, tasks
import json
import os
import logging
from datetime import datetime

class WebCommands(commands.Cog):
    """Cog для обработки команд с веб-панели"""
    
    def __init__(self, bot):
        self.bot = bot
        self.pending_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pending_commands.json')
        self.check_commands.start()
    
    def cog_unload(self):
        self.check_commands.cancel()
    
    @tasks.loop(seconds=5)
    async def check_commands(self):
        if not os.path.exists(self.pending_file):
            return
        
        try:
            with open(self.pending_file, 'r', encoding='utf-8') as f:
                pending = json.load(f)
            if not pending:
                return
            with open(self.pending_file, 'w', encoding='utf-8') as f:
                json.dump([], f)
            for item in pending:
                await self.execute_command(item)
        except Exception as e:
            logging.error(f"[WebCommands] Ошибка чтения pending_commands: {e}")
    
    async def execute_command(self, item):
        command_text = item.get('command', '')
        channel_id = item.get('channel_id')
        executor = item.get('executor', 'Unknown')
        executor_id = item.get('executor_id', '')
        
        if not command_text or not channel_id:
            return
        
        try:
            channel = self.bot.get_channel(int(channel_id))
            if not channel:
                logging.error(f"[WebCommands] Канал {channel_id} не найден")
                return
            
            guild = channel.guild
            
            # Определяем реального исполнителя из участников гильдии
            fake_author = None
            if executor_id:
                try:
                    member = guild.get_member(int(executor_id))
                    if member:
                        fake_author = member
                except (ValueError, TypeError):
                    pass
            
            # Fallback: используем роль бота как автора
            if fake_author is None:
                fake_author = guild.me
            
            # Проверяем, не является ли это командой botmsg (отправка ЛС от имени бота)
            if command_text.strip().startswith('botmsg'):
                await self._send_bot_message(guild, channel, command_text, executor, executor_id)
                return
            
            prefix = '.'
            content = command_text
            if not content.startswith(prefix):
                content = prefix + content
                
            logging.info(f"[WebCommands] Выполнение: {content} (от {executor} / {executor_id})")
            
            # Создаём объект сообщения через правильный конструктор
            fake_id = discord.utils.time_snowflake(datetime.utcnow())
            message_data = {
                'id': str(fake_id),
                'content': content,
                'channel_id': str(channel.id),
                'author': {
                    'id': str(fake_author.id),
                    'username': fake_author.name,
                    'discriminator': getattr(fake_author, 'discriminator', '0'),
                    'avatar': str(fake_author.avatar.key) if fake_author.avatar else None,
                },
                'timestamp': datetime.utcnow().isoformat(),
                'edited_timestamp': None,
                'tts': False,
                'pinned': False,
                'mention_everyone': False,
                'attachments': [],
                'embeds': [],
                'mentions': [],
                'mention_roles': [],
                'mention_channels': [],
                'type': 0,
            }
            message = discord.Message(state=self.bot._connection, channel=channel, data=message_data)
            
            # Выполняем команду
            await self.bot.process_commands(message)
            logging.info(f"[WebCommands] Выполнено: {content}")
            
            # Уведомление об успехе
            embed = discord.Embed(
                title="✅ Команда выполнена",
                description=f"```{command_text}```",
                color=discord.Color.green()
            )
            embed.add_field(name="Исполнитель", value=f"Web: {executor}", inline=True)
            embed.timestamp = datetime.utcnow()
            await channel.send(embed=embed, delete_after=10)
            
        except Exception as e:
            logging.error(f"[WebCommands] Ошибка: {e}")
            import traceback
            traceback.print_exc()
            try:
                ch = self.bot.get_channel(int(channel_id))
                if ch:
                    await ch.send(embed=discord.Embed(
                        title="❌ Ошибка",
                        description=f"```{command_text}```\n\n{str(e)[:200]}",
                        color=discord.Color.red()
                    ), delete_after=15)
            except:
                pass
    
    async def _send_bot_message(self, guild, channel, command_text, executor, executor_id):
        """Отправляет сообщение от имени бота в ЛС пользователю.
        Формат: botmsg <@user> сообщение
        """
        try:
            # Парсим аргументы: botmsg <@user> сообщение
            parts = command_text.split(None, 2)  # botmsg, user, message
            if len(parts) < 3:
                embed = discord.Embed(
                    title="❌ Ошибка",
                    description="Использование: `botmsg <@user> сообщение`",
                    color=discord.Color.red()
                )
                await channel.send(embed=embed, delete_after=10)
                return
            
            user_mention = parts[1]
            msg_text = parts[2]
            
            # Извлекаем ID пользователя из упоминания
            user_id = user_mention.strip('<@!>')
            try:
                member = guild.get_member(int(user_id))
                if not member:
                    member = await guild.fetch_member(int(user_id))
            except (ValueError, discord.NotFound):
                embed = discord.Embed(
                    title="❌ Ошибка",
                    description=f"Пользователь {user_mention} не найден на сервере.",
                    color=discord.Color.red()
                )
                await channel.send(embed=embed, delete_after=10)
                return
            
            # Отправляем ЛС
            dm_embed = discord.Embed(
                title="📬 Сообщение от администрации",
                description=msg_text,
                color=discord.Color.blurple()
            )
            dm_embed.set_footer(text=f"Отправлено от имени клана Arasaka Plaza")
            dm_embed.timestamp = datetime.utcnow()
            
            await member.send(embed=dm_embed)
            
            # Подтверждение в канал
            embed = discord.Embed(
                title="✅ Сообщение отправлено",
                description=f"Пользователю {member.mention} отправлено ЛС.",
                color=discord.Color.green()
            )
            embed.add_field(name="Текст", value=msg_text[:200], inline=False)
            embed.add_field(name="Отправитель (Web)", value=executor, inline=True)
            embed.timestamp = datetime.utcnow()
            await channel.send(embed=embed, delete_after=10)
            logging.info(f"[WebCommands] ЛС отправлено {member.id} от {executor}: {msg_text[:50]}")
            
        except discord.Forbidden:
            embed = discord.Embed(
                title="❌ Ошибка",
                description=f"Не удалось отправить ЛС пользователю — он закрыт для сообщений от бота.",
                color=discord.Color.red()
            )
            await channel.send(embed=embed, delete_after=10)
        except Exception as e:
            logging.error(f"[WebCommands] Ошибка botmsg: {e}")
            embed = discord.Embed(
                title="❌ Ошибка",
                description=f"Не удалось отправить сообщение: {str(e)[:200]}",
                color=discord.Color.red()
            )
            await channel.send(embed=embed, delete_after=10)
    
    @check_commands.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

async def setup(bot):
    await bot.add_cog(WebCommands(bot))