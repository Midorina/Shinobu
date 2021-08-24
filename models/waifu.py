from __future__ import annotations

import math
from typing import List, Tuple

__all__ = ['Waifu', 'Item']


class Item:
    def __init__(self, _id: int, name: str, emote: str, price: int):
        self.id: int = _id

        self.name: str = name
        self.emote: str = emote
        self.price: int = price

    @property
    def name_n_emote(self):
        return self.name + ' ' + self.emote

    @property
    def emote_n_name(self):
        return self.emote + ' ' + self.name

    @classmethod
    def get_with_id(cls, _id: int):
        try:
            return next(item for item in _ITEMS if item.id == _id)
        except StopIteration:
            return None

    @classmethod
    def get_with_emote(cls, emote: str):
        try:
            return next(item for item in _ITEMS if item.emote == emote)
        except StopIteration:
            return None

    @classmethod
    def get_all(cls):
        return _ITEMS

    @classmethod
    def find(cls, item_name: str):
        try:
            return next(x for x in _ITEMS if x.name.lower() == item_name)
        except StopIteration:
            return None

    @classmethod
    def get_emotes_and_amounts(cls, items: List[Item]) -> List[Tuple[str, int]]:
        items = list(sorted(items, key=lambda x: x.price))
        clean_dict = {}
        for item in items:
            try:
                clean_dict[item.emote] += 1
            except KeyError:
                clean_dict[item.emote] = 1

        return [(emote, count) for emote, count in clean_dict.items()]


_ITEMS = (
    Item(0, 'Potato', '🥔', 10),
    Item(1, 'Cookie', '🍪', 20),
    Item(2, 'Bread', '🥖', 40),
    Item(3, 'Lollipop', '🍭', 60),
    Item(4, 'Rose', '🌹', 100),
    Item(5, 'Beer', '🍺', 140),
    Item(6, 'Taco', '🌮', 170),
    Item(7, 'LoveLetter', '💌', 200),
    Item(8, 'Milk', '🥛', 250),
    Item(9, 'Pizza', '🍕', 300),
    Item(10, 'Chocolate', '🍫', 400),
    Item(11, 'IceCream', '🍦', 500),
    Item(12, 'Sushi', '🍣', 600),
    Item(13, 'Rice', '🍚', 800),
    Item(14, 'Watermelon', '🍉', 1000),
    Item(15, 'Bento', '🍱', 1200),
    Item(16, 'MovieTicket', '🎟', 1600),
    Item(17, 'Cake', '🍰', 2000),
    Item(18, 'Book', "📔", 3000),
    Item(19, 'Dog', "🐶", 4000),
    Item(20, 'Cat', "🐱", 4000),
    Item(21, 'Panda', "🐼", 5000),
    Item(22, 'Lipstick', "💄", 6000),
    Item(23, 'Purse', "👛", 7000),
    Item(24, 'iPhone', "📱", 8000),
    Item(25, 'Dress', "👗", 8000),
    Item(26, 'Laptop', "💻", 10000),
    Item(27, 'Violin', "🎻", 1500),
    Item(28, 'Piano', "🎹", 16000),
    Item(29, 'Car', "🚗", 18000),
    Item(30, 'Ring', "💍", 20000),
    Item(31, 'Yacht', "🛳", 24000),
    Item(32, 'House', "🏠", 30000),
    Item(33, 'Helicopter', "🚁", 40000),
    Item(34, 'Spaceship', "🚀", 60000),
    Item(35, 'Moon', "🌕", 100000)
)


class Waifu:
    def __init__(self, user):
        from models.db import UserDB

        self.user: UserDB = user

        self.affinity_id: int = self.user.data.get('waifu_affinity_id')
        self.claimer_id: int = self.user.data.get('waifu_claimer_id')
        self.price: int = self.user.data.get('waifu_price') or self.user.bot.config.base_waifu_price

        self.affinity_changes: int = self.user.data.get('waifu_affinity_changes')
        self.divorce_count: int = self.user.data.get('waifu_divorce_count')

        self.items: List[Item] = [Item.get_with_id(x) for x in self.user.data.get('waifu_items')]

    @property
    def price_readable(self) -> str:
        from mido_utils.converters import readable_currency
        return readable_currency(self.price)

    def get_price_to_reset(self):
        return math.floor(self.price * 1.25 + (self.affinity_changes + self.divorce_count + 2) * 150)

    async def change_claimer(self, new_claimer_id: int):
        self.claimer_id = new_claimer_id
        await self.user.db.execute("UPDATE users SET waifu_claimer_id=$1 WHERE id=$2;", self.claimer_id, self.user.id)

    async def reset_waifu_stats(self):
        self.affinity_changes = 0
        self.divorce_count = 0
        self.price = self.user.bot.config.base_waifu_price
        self.items = []
        self.claimer_id = None
        self.affinity_id = None

        await self.user.db.execute(
            """UPDATE users 
            SET waifu_affinity_changes=$1, 
            waifu_divorce_count=$2, 
            waifu_price=$3, 
            waifu_items=$4, 
            waifu_claimer_id=$5,
            waifu_affinity_id=$6
            WHERE id=$7;""",
            self.affinity_changes,
            self.divorce_count,
            self.price,
            self.items,
            self.claimer_id,
            self.affinity_id,
            self.user.id)

    def get_price_to_claim(self, requester_id: int) -> int:
        if not self.price:
            self.price = self.user.bot.config.base_waifu_price

        if requester_id == self.affinity_id:
            return self.price
        else:
            return math.floor(self.price * 1.1)

    async def add_item(self, item: Item):
        await self.change_price(self.price + math.floor(item.price / 2))

        self.items.append(item)
        await self.user.db.execute("UPDATE users SET waifu_items=ARRAY_APPEND(waifu_items, $1) WHERE id=$2;",
                                   item.id, self.user.id)

    async def change_price(self, new_price: int):
        self.price = new_price
        await self.user.db.execute("UPDATE users SET waifu_price=$1 WHERE id=$2;",
                                   self.price, self.user.id)

    async def change_affinity(self, _id=None):
        self.affinity_id = _id
        self.affinity_changes += 1
        await self.user.db.execute("UPDATE users SET waifu_affinity_id=$1, waifu_affinity_changes=$2 WHERE id=$3;",
                                   self.affinity_id, self.affinity_changes, self.user.id)

    async def get_claimed(self, claimer_id: int, price: int):
        if claimer_id == self.affinity_id:
            self.price = math.floor(price * 1.25)
        else:
            self.price = price

        self.claimer_id = claimer_id

        await self.user.db.execute("UPDATE users SET waifu_price=$1, waifu_claimer_id=$2 WHERE id=$3;",
                                   self.price, self.claimer_id, self.user.id)

    async def _get_divorced(self):
        if self.claimer_id == self.affinity_id:
            self.price = math.floor(self.price * 0.75)

        self.claimer_id = None

        await self.user.db.execute("UPDATE users SET waifu_price=$1, waifu_claimer_id=NULL WHERE id=$2;",
                                   self.price, self.user.id)

    async def divorce(self, waifu: Waifu):
        self.divorce_count += 1
        await self.user.db.execute("UPDATE users SET waifu_divorce_count=$1 WHERE id=$2;",
                                   self.divorce_count, self.user.id)

        await waifu._get_divorced()
