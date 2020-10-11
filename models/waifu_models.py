from __future__ import annotations

import json
import math
from typing import List, Tuple

with open("config.json") as f:
    BASE_WAIFU_PRICE = json.load(f)['base_waifu_price']


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
    def get_all(cls):
        return _ITEMS

    @classmethod
    def find(cls, item_name: str):
        return next(x for x in _ITEMS if x.name.lower() == item_name)

    @classmethod
    def get_emotes_and_amounts(cls, items: List[Item]) -> List[Tuple[str, int]]:
        print("items:", items)
        items = list(sorted(items, key=lambda x: x.price))
        clean_dict = {}
        for item in items:
            try:
                clean_dict[item.emote] += 1
            except KeyError:
                clean_dict[item.emote] = 1

        return [(emote, count) for emote, count in clean_dict.items()]


_ITEMS = (
    Item(0, 'Potato', '🥔', 5),
    Item(1, 'Cookie', '🍪', 10),
    Item(2, 'Bread', '🥖', 20),
    Item(3, 'Lollipop', '🍭', 30),
    Item(4, 'Rose', '🌹', 50),
    Item(5, 'Beer', '🍺', 70),
    Item(6, 'Taco', '🌮', 85),
    Item(7, 'LoveLetter', '💌', 100),
    Item(8, 'Milk', '🥛', 125),
    Item(9, 'Pizza', '🍕', 150),
    Item(10, 'Chocolate', '🍫', 200),
    Item(11, 'IceCream', '🍦', 250),
    Item(12, 'Sushi', '🍣', 300),
    Item(13, 'Rice', '🍚', 400),
    Item(14, 'Watermelon', '🍉', 500),
    Item(15, 'Bento', '🍱', 600),
    Item(16, 'MovieTicket', '🎟', 800),
    Item(17, 'Cake', '🍰', 1000),
    Item(18, 'Book', "📔", 1500),
    Item(19, 'Dog', "🐶", 2000),
    Item(20, 'Cat', "🐱", 2001),
    Item(21, 'Panda', "🐼", 2500),
    Item(22, 'Lipstick', "💄", 3000),
    Item(23, 'Purse', "👛", 3500),
    Item(24, 'iPhone', "📱", 4000),
    Item(25, 'Dress', "👗", 4500),
    Item(26, 'Laptop', "💻", 5000),
    Item(27, 'Violin', "🎻", 7500),
    Item(28, 'Piano', "🎹", 8000),
    Item(29, 'Car', "🚗", 9000),
    Item(30, 'Ring', "💍", 10000),
    Item(31, 'Yacht', "🛳", 12000),
    Item(32, 'House', "🏠", 15000),
    Item(33, 'Helicopter', "🚁", 20000),
    Item(34, 'Spaceship', "🚀", 30000),
    Item(35, 'Moon', "🌕", 50000)
)


# https://gitlab.com/Kwoth/nadekobot/-/tree/1.9/NadekoBot.Core/Services/Database/Models
# https://gitlab.com/Kwoth/nadekobot/-/tree/1.9/NadekoBot.Core/Modules/Gambling/Common/Waifu

class Waifu:
    def __init__(self, user):
        self.user = user

        self.affinity_id: int = self.user.data.get('waifu_affinity_id')
        self.claimer_id: int = self.user.data.get('waifu_claimer_id')
        self.price: int = self.user.data.get('waifu_price') or BASE_WAIFU_PRICE

        self.affinity_changes: int = self.user.data.get('waifu_affinity_changes')
        self.divorce_count: int = self.user.data.get('waifu_divorce_count')

        self.items: List[Item] = [Item.get_with_id(x) for x in self.user.data.get('waifu_items')]

    def get_price_to_reset(self):
        return math.floor(self.price * 1.25 + (self.affinity_changes + self.divorce_count + 2) * 150)

    async def reset_waifu_stats(self):
        await self.user.remove_cash(self.get_price_to_reset())

        self.affinity_changes = 0
        self.divorce_count = 0
        self.price = BASE_WAIFU_PRICE
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
            self.price = BASE_WAIFU_PRICE

        if requester_id == self.affinity_id:
            return self.price
        else:
            return math.floor(self.price * 1.1)

    async def add_item(self, item: Item):
        await self.change_price(self.price + math.floor(item.price / 2))

        self.items.append(item)
        await self.user.db.execute("UPDATE users SET waifu_items=array_append(waifu_items, $1) WHERE id=$2;",
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
                                   self.price, self.claimer_id)

    async def divorce(self, waifu: Waifu):
        self.divorce_count += 1
        await self.user.db.execute("UPDATE users SET waifu_divorce_count=$1 WHERE id=$2;",
                                   self.divorce_count, self.user.id)

        await waifu._get_divorced()
