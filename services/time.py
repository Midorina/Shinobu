import math
from datetime import datetime, timezone, timedelta

from discord.ext.commands import BadArgument

time_multipliers = {
    's': 1,
    'm': 60,
    'h': 60 * 60,
    'd': 60 * 60 * 24,
    'w': 60 * 60 * 24 * 7,
    'mo': 60 * 60 * 24 * 7 * 4
}


class MidoTime:
    def __init__(self, end_date: datetime):
        self.end_date = end_date

    @property
    def end_date_has_passed(self):
        return self.end_date.date() <= datetime.now(timezone.utc).date()

    @property
    def remaining_in_seconds(self):
        return (self.end_date - datetime.now(timezone.utc)) / timedelta(seconds=1)

    @property
    def remaining_string(self):
        return self.parse_seconds_to_str(self.remaining_in_seconds)

    @classmethod
    def add_to_current_date_and_get(cls, seconds: int):
        end_date = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return MidoTime(end_date=end_date)

    @classmethod
    def add_to_previous_date_and_get(cls, previous_date: datetime, seconds: int):
        if not previous_date:
            return MidoTime(end_date=datetime(2000, 1, 1, tzinfo=timezone.utc))
        if not seconds:
            return None
        else:
            end_date = previous_date + timedelta(seconds=seconds)
            return MidoTime(end_date=end_date)

    @staticmethod
    def parse_seconds_to_str(total_seconds: float, short: bool = False, sep=' ') -> str:
        def plural_check(n: int):
            return 's' if n > 1 else ''

        if not total_seconds:
            return 'indefinite'

        # round it up to save the lost milliseconds in calculation
        total_seconds = math.ceil(total_seconds)

        minutes, seconds = divmod(total_seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        weeks, days = divmod(days, 7)
        months, weeks = divmod(weeks, 4)

        str_blocks = list()
        if not short:
            # this may be optimized but idk
            if months > 0:
                str_blocks.append(f'{months} month{plural_check(months)}')
            if weeks > 0:
                str_blocks.append(f'{weeks} week{plural_check(weeks)}')
            if days > 0:
                str_blocks.append(f'{days} day{plural_check(days)}')
            if hours > 0:
                str_blocks.append(f'{hours} hour{plural_check(hours)}')
            if minutes > 0:
                str_blocks.append(f'{minutes} minute{plural_check(minutes)}')
            if seconds > 0:
                str_blocks.append(f'{seconds} second{plural_check(seconds)}')

        else:
            if days > 0:
                str_blocks.append(f'{days:02d}')
            if hours > 0:
                str_blocks.append(f'{hours:02d}')

            str_blocks.append(f'{minutes:02d}')
            str_blocks.append(f'{seconds:02d}')

        if short is True and not sep:
            sep = ':'

        return sep.join(str_blocks)

    @classmethod
    async def convert(cls, ctx, argument):
        length_in_seconds = 0

        index = 0
        while argument:
            if argument[index].isdigit():
                index += 1
                continue

            elif argument[index] in time_multipliers.keys():
                if index == 0:
                    raise BadArgument("Invalid time format!")

                length_in_seconds += int(argument[:index]) * time_multipliers[argument[index]]

                argument = argument[index + 1:]
                index = 0
                continue

            else:
                raise BadArgument("Invalid time format!")

        return cls.add_to_current_date_and_get(length_in_seconds)

    def __str__(self):
        return self.remaining_string

    def __repr__(self):
        return self.remaining_in_seconds
