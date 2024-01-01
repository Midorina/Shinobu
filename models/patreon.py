from __future__ import annotations

import copy
import json

__all__ = ['PatreonPledger', 'PatreonUser', 'UserAndPledgerCombined']


class BasePatreonModel:
    def to_str(self) -> str:
        return json.dumps(vars(self))


class Data(BasePatreonModel):
    def __init__(self, data: dict):
        self.id: int = int(data.pop('id', 0))
        self.type: str = data.pop('type', 'Unknown')


class PatreonPledger(BasePatreonModel):
    class Attributes(BasePatreonModel):
        def __init__(self, data: dict):
            self.amount_cents: int = data.pop('amount_cents', 0)
            self.currency: str = data.pop('currency', 'Unknown')
            self.patron_pays_fees: bool = data.pop('patron_pays_fees', False)
            self.pledge_cap_cents: int = data.pop('pledge_cap_cents', 0)

            self.declined_since = data.pop('declined_since', None)
            self.created_at = data.pop('created_at', None)

    class Relationships(BasePatreonModel):
        class Patron(BasePatreonModel):
            def __init__(self, data: dict):
                self.data = Data(data.pop('data', {}))
                self.links: dict = data.pop('links', {})

        def __init__(self, data: dict):
            self.address: dict = data.pop('address', {})
            self.creator: dict = data.pop('creator', {})
            self.patron = self.Patron(data.pop('patron', {}))
            self.rewards: dict = data.pop('rewards', {})

    def __init__(self, data: dict):
        self._data = copy.deepcopy(data)

        self.attributes = self.Attributes(data.pop('attributes', {}))
        self.id: int = int(data.pop('id', -1))
        self.relationships = self.Relationships(data.pop('relationships', {}))
        self.type: str = data.pop('type', 'Unknown')


class PatreonUser(BasePatreonModel):
    class Attributes(BasePatreonModel):
        class SocialConnections(BasePatreonModel):
            class Discord(BasePatreonModel):
                def __init__(self, data: dict):
                    self.url = data.pop('url', None) if data else None
                    self.user_id = int(data.pop('user_id', -1)) if data else None

            def __init__(self, data: dict):
                self.deviantart = data.pop('deviantart', None)
                self.discord = self.Discord(data.pop('discord', {}))
                self.facebook = data.pop('facebook', None)
                self.google = data.pop('google', None)
                self.twitch = data.pop('twitch', None)
                self.twitter = data.pop('twitter', None)
                self.youtube = data.pop('youtube', None)
                self.instagram = data.pop('instagram', None)
                self.reddit = data.pop('reddit', None)
                self.spotify = data.pop('spotify', None)

        def __init__(self, data: dict):
            self.full_name: str = data.pop('full_name', 'Unknown')
            self.first_name: str = data.pop('first_name', 'Unknown')
            self.last_name: str = data.pop('last_name', 'Unknown')

            self.about = data.pop('about', None)
            self.created = data.pop('created', None)
            self.default_country_code = data.pop('default_country_code', None)
            self.email: str = data.pop('email', 'Unknown')
            self.gender = data.pop('gender', None)
            self.is_email_verified = data.pop('is_email_verified', None)
            self.social_connections = self.SocialConnections(data.pop('social_connections', {}))
            self.vanity = data.pop('vanity', None)

            self.profile_url: str = data.pop('url', 'Unknown')
            self.image_url: str = data.pop('image_url', 'Unknown')
            self.thumb_url: str = data.pop('thumb_url', 'Unknown')

            self.facebook = data.pop('facebook', None)
            self.twitch = data.pop('twitch', None)
            self.twitter = data.pop('twitter', None)
            self.youtube = data.pop('youtube', None)

    def __init__(self, data: dict):
        self._data = copy.deepcopy(data)

        self.attributes = self.Attributes(data.pop('attributes', {}))
        self.id: int = int(data.pop('id', -1))
        self.relationships: dict = data.pop('relationships', {})
        self.type: str = data.pop('type', 'Unknown')


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
