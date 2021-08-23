import argparse
import asyncio
import logging
import os
from logging.handlers import TimedRotatingFileHandler

from cluster_manager import Launcher

# arg stuff
parser = argparse.ArgumentParser()
parser.add_argument("name", help="The name of the bot you want to launch.")
bot_name = parser.parse_args().name

# logging stuff
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# todo: colored logging
_format = logging.Formatter(fmt='[{asctime}.{msecs:.0f}] [{levelname:<7}] {name}: {message}',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            style='{')

if not os.path.exists('logs'):
    os.makedirs('logs')
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
