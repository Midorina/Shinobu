from main import MidoBot
import logging
from logging.handlers import TimedRotatingFileHandler

logger = logging.getLogger()
logger.setLevel(logging.INFO)

date_format = '%Y-%m-%d %H:%M:%S'
_format = logging.Formatter('[{asctime}] [{levelname:<7}] {name}: {message}', date_format, style='{')

handler_f = TimedRotatingFileHandler(filename="logs/midobot.log",
                                     when="d",
                                     interval=1,
                                     backupCount=5,
                                     encoding="utf-8")
handler_c = logging.StreamHandler()

handler_f.setFormatter(_format)
handler_c.setFormatter(_format)

logger.addHandler(handler_f)
logger.addHandler(handler_c)

bot = MidoBot()
bot.run()
