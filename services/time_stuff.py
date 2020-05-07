import json
import math
from datetime import datetime, timezone, timedelta

with open('config.json') as f:
    config = json.load(f)


def get_time_difference(user, cd_type: str) -> int:
    cooldowns = config['cooldowns']

    last_time_in_db = None
    if cd_type == "xp":
        last_time_in_db = user.last_xp_gain_date

    elif cd_type == "daily":
        last_time_in_db = user.last_daily_claim_date

    elif cd_type == "uptime":
        last_time_in_db = user.uptime

    if not last_time_in_db:
        return 0

    time_difference_in_seconds = (datetime.now(timezone.utc) - last_time_in_db) / timedelta(seconds=1)

    # return time difference.
    if cd_type == "uptime":
        return time_difference_in_seconds
    else:
        return cooldowns[cd_type] - time_difference_in_seconds


def parse_seconds(remaining: int) -> str:
    str_to_return = ""

    if remaining > 86400:
        str_to_return += f"{math.floor(remaining / 86400)} days "
        remaining -= math.floor(remaining / 86400) * 86400

    if remaining > 3600:
        str_to_return += f"{math.floor(remaining / 3600)} hours "
        remaining -= math.floor(remaining / 3600) * 3600

    if remaining > 60:
        str_to_return += f"{math.floor(remaining / 60)} minutes "
        remaining -= math.floor(remaining / 60) * 60

    str_to_return += f"{math.floor(remaining)} seconds "

    return str_to_return
