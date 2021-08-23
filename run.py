import argparse
import asyncio
import logging
from logging.handlers import TimedRotatingFileHandler

from cluster_manager import Launcher

# arg stuff
parser = argparse.ArgumentParser()
parser.add_argument("bot", "botname", "name", help="The name of the bot you want to launch.")
bot_name = parser.parse_args().bot

# logging stuff
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# todo: colored logging
date_format = '%Y-%m-%d %H:%M:%S'
_format = logging.Formatter('[{asctime}.{msecs:.0f}] [{levelname:<7}] {name}: {message}', date_format, style='{')

handler_f = TimedRotatingFileHandler(filename=f"logs/{bot_name}.log",
                                     when="d",
                                     interval=1,
                                     backupCount=5,
                                     encoding="utf-8")
handler_c = logging.StreamHandler()

handler_f.setFormatter(_format)
handler_c.setFormatter(_format)

logger.handlers = [handler_f, handler_c]

loop = asyncio.get_event_loop()
Launcher(loop, bot_name).start()
