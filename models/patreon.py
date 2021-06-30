from __future__ import annotations

import copy
import json

__all__ = ['PatreonPledger', 'PatreonUser', 'UserAndPledgerCombined']


class BasePatreonModel:
    def to_str(self) -> str:
        return json.dumps(vars(self))


class Data(BasePatreonModel):
    def __init__(self, data: dict):
        self.id: int = int(data.pop('id'))
        self.type: str = data.pop('type')


class PatreonPledger(BasePatreonModel):
    class Attributes(BasePatreonModel):
        def __init__(self, data: dict):
            self.amount_cents: int = data.pop('amount_cents')
            self.currency: str = data.pop('currency')
            self.patron_pays_fees: bool = data.pop('patron_pays_fees')
            self.pledge_cap_cents: int = data.pop('pledge_cap_cents')

            self.declined_since = data.pop('declined_since')
            self.created_at = data.pop('created_at')

    class Relationships(BasePatreonModel):
        class Patron(BasePatreonModel):
            def __init__(self, data):
                self.data = Data(data.pop('data'))
                self.links: dict = data.pop('links')

        def __init__(self, data: dict):
            self.address: dict = data.pop('address')
            self.creator: dict = data.pop('creator')
            self.patron = self.Patron(data.pop('patron'))
            self.rewards: dict = data.pop('rewards', None)

    def __init__(self, data: dict):
        self._data = copy.deepcopy(data)

        self.attributes = self.Attributes(data.pop('attributes'))
        self.id: int = int(data.pop('id'))
        self.relationships = self.Relationships(data.pop('relationships'))
        self.type: str = data.pop('type')


class PatreonUser(BasePatreonModel):
    class Attributes(BasePatreonModel):
        class SocialConnections(BasePatreonModel):
            class Discord(BasePatreonModel):
                def __init__(self, data: dict):
                    self.url = data.pop('url') if data else None
                    self.user_id = int(data.pop('user_id')) if data else None

            def __init__(self, data: dict):
                self.deviantart = data.pop('deviantart')
                self.discord = self.Discord(data.pop('discord'))
                self.facebook = data.pop('facebook')
                self.google = data.pop('google')
                self.twitch = data.pop('twitch')
                self.twitter = data.pop('twitter')
                self.youtube = data.pop('youtube')
                self.instagram = data.pop('instagram')
                self.reddit = data.pop('reddit')
                self.spotify = data.pop('spotify')

        def __init__(self, data: dict):
            self.full_name: str = data.pop('full_name')
            self.first_name: str = data.pop('first_name')
            self.last_name: str = data.pop('last_name')

            self.about = data.pop('about')
            self.created = data.pop('created')
            self.default_country_code = data.pop('default_country_code')
            self.email: str = data.pop('email')
            self.gender = data.pop('gender')
            self.is_email_verified = data.pop('is_email_verified')
            self.social_connections = self.SocialConnections(data.pop('social_connections'))
            self.vanity = data.pop('vanity')

            self.profile_url: str = data.pop('url')
            self.image_url: str = data.pop('image_url')
            self.thumb_url: str = data.pop('thumb_url')

            self.facebook = data.pop('facebook')
            self.twitch = data.pop('twitch')
            self.twitter = data.pop('twitter')
            self.youtube = data.pop('youtube')

    def __init__(self, data: dict):
        self._data = copy.deepcopy(data)

        self.attributes = self.Attributes(data.pop('attributes'))
        self.id: int = int(data.pop('id'))
        self.relationships: dict = data.pop('relationships')
        self.type: str = data.pop('type')


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


class UserAndPledgerCombined(BasePatreonModel):
    def __init__(self, user: PatreonUser, pledger: PatreonPledger):
        self.user = user
        self.pledger = pledger

        # useful quick access
        self.discord_id = self.user.attributes.social_connections.discord.user_id
        self.pledge_amount = self.pledger.attributes.amount_cents

        self.level_status = Level.get_with_pledge_amount(self.pledge_amount)

    @property
    def can_claim_daily_without_ads(self) -> bool:
        return self.pledge_amount >= 500

    @property
    def can_use_premium_music(self) -> bool:
        return self.pledge_amount >= 1000

    @classmethod
    def from_str(cls, data: str) -> UserAndPledgerCombined:
        data = json.loads(data)

        return cls(user=PatreonUser(data['user']), pledger=PatreonPledger(data['pledger']))

    def to_str(self):
        return json.dumps({'user': self.user._data, 'pledger': self.pledger._data})
