from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from shinobu import ShinobuBot


class BaseShinobuService:
    def __init__(self, bot: ShinobuBot):
        self.bot = bot
