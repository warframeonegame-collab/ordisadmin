import discord
from discord.ext import commands, tasks
import os
import asyncio
import traceback
import sys
from dotenv import load_dotenv
import logging

# Импортируем менеджер ошибок бота
from utils.bot_errors import BotErrorsManager
bot_errors = BotErrorsManager()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

load_dotenv()
TOKEN = os.environ.get('DISCORD_TOKEN')

if not TOKEN:
    raise ValueError("Токен не найден в файле .env!")

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.guild_messages = True
intents.members = True
intents.voice_states = True
intents.presences = True

bot = commands.Bot(command_prefix='.', intents=intents)
bot.remove_command("help")

# Глобальный кэш для предотвращения дублирования команд
_processed_commands = set()
_duplicate_lock = asyncio.Lock()

@bot.before_invoke
async def _prevent_duplicate_commands(ctx):
    """Отменяет выполнение команды, если это сообщение уже было обработано."""
    async with _duplicate_lock:
        message_id = ctx.message.id
        if message_id in _processed_commands:
            raise commands.CommandError("Duplicate command ignored")
        _processed_commands.add(message_id)
        # Очистка старых записей (держим не больше 1000)
        if len(_processed_commands) > 1000:
            _processed_commands.clear()

async def load_cogs():
    try:
        cog_files = [f for f in os.listdir('cogs') if f.endswith('.py')]
        
        for cog in cog_files:
            cog_name = f'cogs.{cog[:-3]}'
            try:
                await bot.load_extension(cog_name)
                logging.info(f'✅ Успешно загружен Cog: {cog_name}')
            except commands.ExtensionNotFound:
                logging.error(f'❌ Cog не найден: {cog_name}')
            except commands.ExtensionAlreadyLoaded:
                logging.warning(f'⚠️ Cog уже загружен: {cog_name}')
            except commands.NoEntryPointError:
                logging.error(f'❌ Отсутствует точка входа в Cog: {cog_name}')
            except Exception as e:
                logging.error(f'❌ Ошибка при загрузке Cog {cog_name}: {str(e)}')
                
    except Exception as e:
        logging.critical(f'❌ Критическая ошибка при загрузке Cogs: {str(e)}')

async def setup_hook():
    """Загружает коги ОДИН раз при старте бота (до on_ready)."""
    logging.info('--- Загружаю расширения... ---')
    await load_cogs()

bot.setup_hook = setup_hook

@bot.event
async def on_ready():
    logging.info(f'🤖 Бот {bot.user} успешно авторизован!')
    logging.info(f'ID бота: {bot.user.id}')

    await bot.change_presence(activity=discord.Game(name="Warframe"))
    logging.info('Статус установлен: Играет в Warframe')

@bot.command(name="stop")
@commands.is_owner()
async def stop_bot(ctx):
    """Останавливает бота (только для владельца)."""
    try:
        await ctx.message.delete()
    except Exception:
        pass
    await ctx.send("🔴 Бот останавливается...", delete_after=5)
    logging.info(f"Бот остановлен по команде пользователя {ctx.author} ({ctx.author.id})")
    await bot.close()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    error_str = str(error)
    if "Duplicate command ignored" in error_str or "Command not allowed in this channel" in error_str:
        return  # Игнорируем дубликаты и запрещённые каналы
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас недостаточно прав для выполнения этой команды.", ephemeral=True)
    elif isinstance(error, commands.NotOwner):
        await ctx.send("❌ Эта команда доступна только владельцу бота.", delete_after=5)
    
    # Сохраняем ошибку в локальное хранилище для отображения на сайте
    try:
        error_type = type(error).__name__
        bot_errors.add_error(
            error_type=error_type,
            error_message=error_str,
            source=f"команда: {ctx.command}",
            user_id=str(ctx.author.id),
            user_name=ctx.author.display_name,
            details={
                'command': str(ctx.command),
                'message_content': ctx.message.content,
                'channel_id': str(ctx.channel.id),
                'guild_id': str(ctx.guild.id) if ctx.guild else '',
            }
        )
    except Exception as e:
        logging.error(f"Не удалось сохранить ошибку команды: {e}")

@bot.event
async def on_error(event, *args, **kwargs):
    """Глобальный обработчик необработанных исключений."""
    error_type, error_value, error_traceback = sys.exc_info()
    error_str = str(error_value) if error_value else "Неизвестная ошибка"
    tb_str = ''.join(traceback.format_exception(error_type, error_value, error_traceback)) if error_type else ''
    
    logging.error(f"Необработанная ошибка в событии {event}: {error_str}")
    
    try:
        bot_errors.add_error(
            error_type=f"on_error:{event}",
            error_message=error_str,
            source=f"событие: {event}",
            details={
                'traceback': tb_str[:2000],
                'args': [str(a)[:200] for a in args],
            }
        )
    except Exception as e:
        logging.error(f"Не удалось сохранить глобальную ошибку: {e}")

if __name__ == '__main__':
    try:
        bot.run(TOKEN)
    except Exception as e:
        logging.critical(f'❌ Ошибка при запуске бота: {str(e)}')
