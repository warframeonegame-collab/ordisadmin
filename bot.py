import discord
from discord.ext import commands, tasks
import os
import asyncio
from dotenv import load_dotenv
import logging

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

if __name__ == '__main__':
    try:
        bot.run(TOKEN)
    except Exception as e:
        logging.critical(f'❌ Ошибка при запуске бота: {str(e)}')
