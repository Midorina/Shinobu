import json
from typing import List

with open("config.json") as f:
    BASE_WAIFU_PRICE = json.load(f)['base_waifu_price']


class Item:
    def __init__(self, value, name, emote, price):
        self.id: int = value

        self.name: str = name
        self.emote: str = emote
        self.price: int = price

    @classmethod
    def get_with_id(cls, _id: int):
        try:
            return next(item for item in _ITEMS if item.id == _id)
        except StopIteration:
            return None

    @classmethod
    def get_all(cls):
        return _ITEMS


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

        self.affinity_id = self.user.data.get('waifu_affinity_id')
        self.owner_id = self.user.data.get('waifu_claimer_id')
        self.price = self.user.data.get('waifu_price')
        self.affinity_changes: int = self.user.data.get('waifu_affinity_changes')
        self.items: List[Item] = [Item.get_with_id(x) for x in self.user.data.get('waifu_items')]

    def get_price_to_claim(self, requester_id: int) -> int:
        if not self.price:
            self.price = BASE_WAIFU_PRICE

        if requester_id == self.affinity_id:
            return self.price
        else:
            return self.price * 1.1

    def get_divorce_price(self, requester_id: int) -> int:
        if self.affinity_id == requester_id:
            return self.price / 2 * 0.75
        else:
            return self.price / 2

    async def change_affinity(self, _id=None):
        self.affinity_id = _id
        self.affinity_changes += 1
        await self.user.db.execute("UPDATE users SET waifu_affinity_id=$1, waifu_affinity_changes=$2 WHERE id=$3;",
                                   self.affinity_id, self.affinity_changes, self.user.id)

    async def get_claimed(self, claimer_id: int, price: int):
        if claimer_id == self.affinity_id:
            self.price = price * 1.25
        else:
            self.price = price

        self.owner_id = claimer_id

        await self.user.db.execute("UPDATE users SET waifu_price=$1, waifu_claimer_id=$2 WHERE id=$3;",
                                   self.price, self.owner_id, self.user.id)

    async def get_divorced(self):
        if self.owner_id == self.affinity_id:
            self.price *= 0.75

        self.owner_id = None

        await self.user.db.execute("UPDATE users SET waifu_price=$1, waifu_claimer_id=$2 WHERE id=$3;",
                                   self.price, self.owner_id)
