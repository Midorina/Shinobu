import argparse
import logging
from logging.handlers import TimedRotatingFileHandler

from midobot import MidoBot

# arg stuff
parser = argparse.ArgumentParser()
parser.add_argument("bot", help="The name of the bot you want to launch (either 'midobot' or 'shinobu')")
bot_name = parser.parse_args().bot

# logging stuff
logger = logging.getLogger()
logger.setLevel(logging.INFO)

date_format = '%Y-%m-%d %H:%M:%S'
_format = logging.Formatter('[{asctime}] [{levelname:<7}] {name}: {message}', date_format, style='{')

handler_f = TimedRotatingFileHandler(filename=f"logs/{bot_name}.log",
                                     when="d",
                                     interval=1,
                                     backupCount=5,
                                     encoding="utf-8")
handler_c = logging.StreamHandler()

handler_f.setFormatter(_format)
handler_c.setFormatter(_format)

logger.addHandler(handler_f)
logger.addHandler(handler_c)

bot = MidoBot(bot_name)
bot.run()
