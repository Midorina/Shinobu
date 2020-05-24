import math
from datetime import datetime, timezone, timedelta
from functools import cached_property

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
    def __init__(self, start_date: datetime, end_date: datetime, initial_seconds: int = 0):
        self.start_date = start_date
        self.end_date = end_date

        self.initial_remaining_seconds = initial_seconds

    @cached_property
    def start_date_string(self):
        return self.start_date.strftime('%Y-%m-%d, %H:%M:%S UTC')

    @cached_property
    def end_date_string(self):
        return self.end_date.strftime('%Y-%m-%d, %H:%M:%S UTC')

    @property
    def end_date_has_passed(self):
        return self.end_date <= datetime.now(timezone.utc)

    @property
    def remaining_seconds(self):
        remaining_in_float = (self.end_date - datetime.now(timezone.utc)) / timedelta(seconds=1)

        if remaining_in_float < 0:
            return 0
        else:
            return math.ceil(remaining_in_float)

    @property
    def remaining_string(self):
        return self.parse_seconds_to_str(self.remaining_seconds)

    @property
    def initial_remaining_string(self):
        return self.parse_seconds_to_str(self.initial_remaining_seconds)

    @classmethod
    def add_to_current_date_and_get(cls, seconds: int):
        now = datetime.now(timezone.utc)
        end_date = now + timedelta(seconds=seconds)
        return MidoTime(start_date=now,
                        end_date=end_date,
                        initial_seconds=seconds)

    @classmethod
    def add_to_previous_date_and_get(cls, previous_date: datetime, seconds: int):
        if not previous_date:
            really_old_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
            return MidoTime(start_date=really_old_date,
                            end_date=really_old_date,
                            initial_seconds=seconds)
        if not seconds:
            return None
        else:
            end_date = previous_date + timedelta(seconds=seconds)
            return MidoTime(start_date=previous_date,
                            end_date=end_date,
                            initial_seconds=seconds)

    @staticmethod
    def parse_seconds_to_str(total_seconds: float = 0, short: bool = False, sep=' ') -> str:
        def plural_check(n: int):
            return 's' if n > 1 else ''

        if not total_seconds and not short:
            return None

        # precise result for music
        # rough result for moderation commands
        if not short:
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

        return sep.join(str_blocks)

    @classmethod
    async def convert(cls, ctx, argument):
        """Converts a time length argument into MidoTime object.
        """
        length_in_seconds = 0

        index = 0
        while argument:
            if argument[index].isdigit():
                index += 1
                continue

            elif argument[index] in time_multipliers.keys():
                if index == 0:
                    raise BadArgument("Invalid time format!")

                # if its a month
                if argument[index: index + 2] == 'mo':
                    multiplier = time_multipliers['mo']
                else:
                    multiplier = time_multipliers[argument[index]]

                length_in_seconds += int(argument[:index]) * multiplier

                # if its a month
                if multiplier == time_multipliers['mo']:
                    argument = argument[index + 2:]
                else:
                    argument = argument[index + 1:]

                index = 0

            else:
                raise BadArgument("Invalid time format!")

        return cls.add_to_current_date_and_get(length_in_seconds)

    def __str__(self):
        return self.remaining_string

    def __repr__(self):
        return self.remaining_seconds
