from enum import Enum

__all__ = ['HearthstoneCard']


class Rarity(Enum):
    Common = 1
    Free = 2
    Rare = 3
    Epic = 4
    Legendary = 5


class Type(Enum):
    Hero = 3
    Minion = 4
    Spell = 5
    Weapon = 7


class HearthstoneCard:
    def __init__(self, data: dict):
        from mido_utils.converters import html_to_discord

        self.id: int = data.pop('id')

        self.name: str = data.pop('name')
        self.description: str = html_to_discord(data.pop('text'))

        self.rarity: Rarity = Rarity(data.pop('rarityId'))
        self.type: Type = Type(data.pop('cardTypeId'))

        self.health: int = data.pop('health', 0)
        self.attack: int = data.pop('attack', 0)
        self.mana_cost: int = data.pop('manaCost', 0)
        self.durability: int = data.pop('durability', 0)

        self.image: str = data.pop('image')
        self.thumb: str = data.pop('cropImage')

    @property
    def rarity_color(self):
        if self.rarity == Rarity.Free:
            return 0x36393f
        elif self.rarity == Rarity.Common:
            return 0xfcfcf6
        elif self.rarity == Rarity.Rare:
            return 0x258cf1
        elif self.rarity == Rarity.Epic:
            return 0x9a37b3
        elif self.rarity == Rarity.Legendary:
            return 0xeda90d
