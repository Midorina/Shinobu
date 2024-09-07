from __future__ import annotations

import json

__all__ = ['PatreonPledger']


class BasePatreonModel:
    def to_str(self) -> str:
        return json.dumps(vars(self))


class Level:
    def __init__(self, level: int, pledge_amount: int):
        self.level = level
        self.pledge_amount = pledge_amount

        self.can_claim_daily_without_voting = False
        self.can_use_premium_music = False

        # permissions
        if self.level >= 1:
            self.can_claim_daily_without_voting = True
        if self.level >= 2:
            self.can_use_premium_music = True

        # donuts
        self.monthly_donut_reward = self.pledge_amount * 1000 * (1 + (level * 0.5))

    @classmethod
    def get_with_pledge_amount(cls, amount: int) -> Level:
        """1, 5, 10, 15, 30, 50, 100"""
        # convert from cents
        amount = amount // 100

        if amount < 0:
            return Level(0, amount)
        elif amount <= 1:
            return Level(1, amount)
        elif amount <= 5:
            return Level(2, amount)
        elif amount <= 10:
            return Level(3, amount)
        elif amount <= 15:
            return Level(4, amount)
        elif amount <= 30:
            return Level(5, amount)
        elif amount <= 50:
            return Level(6, amount)
        elif amount <= 100:
            return Level(7, amount)
        else:
            return Level(8, amount)


class PatreonPledger(BasePatreonModel):
    def __init__(self, name: str, discord_id: str, pledge_amount_in_cents: int):
        self.name = name

        # useful quick access
        self.discord_id = discord_id
        self.pledge_amount_in_cents = pledge_amount_in_cents

        self.level_status = Level.get_with_pledge_amount(self.pledge_amount_in_cents)

    @property
    def can_claim_daily_without_ads(self) -> bool:
        return self.pledge_amount_in_cents >= 500

    @property
    def can_use_premium_music(self) -> bool:
        return self.pledge_amount_in_cents >= 1000

    @classmethod
    def from_str(cls, data: str) -> PatreonPledger:
        data = json.loads(data)

        return PatreonPledger(data['name'], data['discord_id'], data['pledge_amount_in_cents'])

    def to_str(self):
        return json.dumps(
            {'name': self.name, 'discord_id': self.discord_id, 'pledge_amount_in_cents': self.pledge_amount_in_cents})
