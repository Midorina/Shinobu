import math
import json

from datetime import datetime, timezone, timedelta

with open('config.json') as f:
    config = json.load(f)


def get_cooldown(user, cd_type: str) -> int:
    cooldowns = config['cooldowns']

    last_time_in_db = None

    if cd_type == "xp":
        last_time_in_db = user.last_xp_gain_date

    elif cd_type == "daily":
        last_time_in_db = user.last_daily_claim_date

    if last_time_in_db is None:
        return 0

    current_time = datetime.now(timezone.utc)

    time_difference = current_time - last_time_in_db

    time_difference_in_seconds = time_difference / timedelta(seconds=1)

    if time_difference_in_seconds < cooldowns[cd_type]:
        return cooldowns[cd_type] - time_difference_in_seconds
    else:
        return 0


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
