from main import MidoBot
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

date_format = '%Y-%m-%d %H:%M:%S'
format = logging.Formatter('[{asctime}] [{levelname:<7}] {name}: {message}', date_format, style='{')

handler_f = logging.FileHandler(filename="midobot.log", encoding="utf-8", mode="w")
handler_c = logging.StreamHandler()

handler_f.setFormatter(format)
handler_c.setFormatter(format)

logger.addHandler(handler_f)
logger.addHandler(handler_c)

bot = MidoBot()
bot.run()
