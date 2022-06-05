import math
from datetime import datetime, timedelta, timezone
from functools import cached_property

from discord.ext.commands import BadArgument, UserInputError

time_multipliers = {
    's' : 1,
    'm' : 60,
    'h' : 60 * 60,
    'd' : 60 * 60 * 24,
    'w' : 60 * 60 * 24 * 7,
    'mo': 60 * 60 * 24 * 7 * 4
}


# TODO: rewrite this?


class Time:
    def __init__(self,
                 start_date: datetime = None,
                 end_date: datetime = None,
                 initial_seconds: int = 0,
                 offset_naive: bool = False):
        self.start_date = start_date or datetime.now(timezone.utc)
        self.end_date = end_date

        self.initial_remaining_seconds = initial_seconds

        self.offset_naive = offset_naive

    def _now(self):
        if self.offset_naive is True:
            return datetime.now()
        else:
            return datetime.now(timezone.utc)

    @classmethod
    def get_now(cls, offset_naive=False):
        if offset_naive is True:
            return cls(datetime.now())
        else:
            return cls(datetime.now(timezone.utc))

    @classmethod
    def from_timestamp(cls, timestamp: int):
        return cls(datetime.fromtimestamp(timestamp), offset_naive=True)

    @cached_property
    def start_date_string(self):
        return self.start_date.strftime('%Y-%m-%d, %H:%M:%S UTC')

    @cached_property
    def end_date_string(self):
        if not self.end_date:
            raise Exception("No end date!")
        return self.end_date.strftime('%Y-%m-%d, %H:%M:%S UTC')

    @property
    def end_date_has_passed(self):
        if not self.end_date:
            raise Exception("No end date!")
        return self.end_date <= self._now()

    @property
    def passed_seconds_in_float(self) -> float:
        return (self._now() - self.start_date) / timedelta(seconds=1)

    @property
    def passed_seconds(self) -> int:
        """Returns the time that has passed since the start."""
        return math.ceil(self.passed_seconds_in_float)

    @property
    def passed_seconds_in_float_formatted(self) -> str:
        return '{:.5f}s'.format(self.passed_seconds_in_float)

    @property
    def passed_string(self):
        return self.parse_seconds_to_str(self.passed_seconds)

    @property
    def remaining_seconds(self):
        if self.end_date:
            remaining_in_float = (self.end_date - self._now()) / timedelta(seconds=1)
        else:
            remaining_in_float = (self._now() - self.start_date) / timedelta(seconds=1)

        if remaining_in_float < 0:
            return 0
        else:
            return math.ceil(remaining_in_float)

    @property
    def remaining_days(self):
        return math.floor(self.remaining_seconds / (60 * 60 * 24))

    @property
    def remaining_string(self):
        return self.parse_seconds_to_str(self.remaining_seconds)

    @property
    def initial_remaining_string(self):
        return self.parse_seconds_to_str(self.initial_remaining_seconds)

    @classmethod
    def add_to_current_date_and_get(cls, seconds: int):
        now = datetime.now(timezone.utc)

        try:
            end_date = now + timedelta(seconds=seconds)
        except OverflowError:
            raise UserInputError("That date is too far past the current date "
                                 "that you probably won't be able to see that day. "
                                 "Please input a closer date and try again.")
        else:
            return Time(start_date=now,
                        end_date=end_date,
                        initial_seconds=seconds)

    @classmethod
    def add_to_previous_date_and_get(cls, previous_date: datetime, seconds: int):
        if not previous_date:
            really_old_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
            return Time(start_date=really_old_date,
                        end_date=really_old_date,
                        initial_seconds=seconds)
        if not seconds:
            return Time(start_date=previous_date)
        else:
            end_date = previous_date + timedelta(seconds=seconds)
            return Time(start_date=previous_date,
                        end_date=end_date,
                        initial_seconds=seconds)

    @staticmethod
    def parse_seconds_to_str(total_seconds: float = 0, short: bool = False, sep=' ') -> str:
        def plural_check(n: int):
            return 's' if n > 1 else ''

        if not total_seconds and not short:
            return 'forever'

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
    async def convert(cls, ctx, argument: str):  # ctx arg is passed no matter what
        """Converts a time length argument into MidoTime object."""
        length_in_seconds = 0

        if argument.isdigit():  # if only digit is passed
            length_in_seconds = int(argument) * 60  # its probably minutes, so we convert to seconds

        else:
            index = 0
            while argument:
                if argument[index].isdigit():
                    if argument[index] == argument[-1]:  # if its the last index
                        raise BadArgument("Invalid time format!")
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
