import math
from datetime import datetime, timedelta, timezone

from discord.ext.commands import BadArgument

time_multipliers = {
    's' : 1,
    'm' : 60,
    'h' : 60 * 60,
    'd' : 60 * 60 * 24,
    'w' : 60 * 60 * 24 * 7,
    'mo': 60 * 60 * 24 * 7 * 4
}


class MidoTime:
    def __init__(self,
                 start_date: datetime = None,
                 offset_naive: bool = False):
        self.date = start_date or datetime.now(timezone.utc)

        self.offset_naive = offset_naive

    def now(self):
        if self.offset_naive is True:
            return datetime.now()
        else:
            return datetime.now(timezone.utc)

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return self.date.strftime('%Y-%m-%d, %H:%M:%S UTC')

    def has_passed(self, other_date):
        """Returns whether it passed the other date."""
        return self.date <= other_date

    def _passed_seconds(self, return_float=False):
        """Returns the time that has passed since the start."""
        remaining_in_float = (self.now() - self.start_date) / timedelta(seconds=1)
        if return_float is True:
            return remaining_in_float
        else:
            return math.ceil(remaining_in_float)

    @property
    def passed_seconds(self) -> float:
        """Returns the time that has passed."""
        return (self.now() - self.date) / timedelta(seconds=1)

    @property
    def passed_days(self):
        return math.floor(self.passed_seconds / (60 * 60 * 24))

    @property
    def passed_string(self):
        return self.parse_seconds_to_str(self.passed_seconds)

    def remaining_seconds_before(self, other_date):
        remaining_in_float = (other_date - self.now()) / timedelta(seconds=1)

        if remaining_in_float < 0:
            return 0
        else:
            return math.ceil(remaining_in_float)

    def remaining_string(self, other_date):
        return self.parse_seconds_to_str(self.remaining_seconds_before(other_date))

    @classmethod
    def add_to_current_date_and_get(cls, seconds: int):
        date = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        return MidoTime(start_date=date)

    @classmethod
    def add_to_previous_date_and_get(cls, previous_date: datetime, seconds: int):
        if not previous_date:
            really_old_date = datetime(2000, 1, 1, tzinfo=timezone.utc)
            return MidoTime(start_date=really_old_date,
                            end_date=really_old_date,
                            initial_seconds=seconds)
        if not seconds:
            return MidoTime(start_date=previous_date)
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
            return ''

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
