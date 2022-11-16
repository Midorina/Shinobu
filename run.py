import argparse
import logging
import os
import sys
from logging.handlers import TimedRotatingFileHandler

from discord.utils import _ColourFormatter

from cluster_manager import Launcher


def main():
    # arg stuff
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="The name of the bot you want to launch.")
    bot_name = parser.parse_args().name

    # logger setup
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # use discord.py's colored formatter
    _format = _ColourFormatter()

    # file handler
    if not os.path.exists('logs'):
        os.makedirs('logs')
    handler_f = TimedRotatingFileHandler(
        filename=f"logs/{bot_name}.log",
        when="d",
        interval=1,
        backupCount=5,
        encoding="utf-8")

    # stdout handler (that only shows INFO and DEBUG)
    handler_c1 = logging.StreamHandler(stream=sys.stdout)
    handler_c1.setLevel(logging.DEBUG)
    handler_c1.addFilter(lambda msg: msg.levelno <= logging.INFO)

    # stderr handler (that only shows warnings and above)
    handler_c2 = logging.StreamHandler(stream=sys.stderr)
    handler_c2.setLevel(logging.WARNING)

    handler_f.setFormatter(_format)
    handler_c1.setFormatter(_format)
    handler_c2.setFormatter(_format)

    logger.handlers = [handler_c1, handler_c2, handler_f]

    # multiprocessing_logging.install_mp_handler()

    Launcher(bot_name).start()


if __name__ == '__main__':
    main()
