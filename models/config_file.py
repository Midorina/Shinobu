from __future__ import annotations

import json
import logging
from typing import Dict, List, Union

import mido_utils


class ConfigFile:
    def __init__(self, data: dict):
        self.token: str = data.get('token')
        self.ipc_port: int = data.get('ipc_port')

        self.default_prefix: str = data.get('default_prefix', 's.')

        self.playing: str = data.get('playing', f'{self.default_prefix}help')

        self.default_embed_color: str = data.get('default_embed_color', '0xfffe91')

        self.log_channel_id: int = data.get('log_channel_id', 0)

        self.daily_amount: int = data.get('daily_amount', 250)

        self.base_waifu_price: int = data.get('base_waifu_price', 200)

        self.owner_ids: List[int] = data.get('owner_ids', [90076279646212096])

        self.cooldowns: Dict[str, int] = data.get('cooldowns', {"daily": 43200, "xp": 60})

        self.db_credentials: Dict[str, str] = data.get('db_credentials')
        self.lavalink_nodes_credentials: List[Dict[str, Union[str, int]]] = data.get('lavalink_nodes_credentials')
        self.topgg_credentials: Dict[str, Union[bool, str, int]] = data.get('topgg_credentials')
        self.spotify_credentials: Dict[str, str] = data.get('spotify_credentials')
        self.reddit_credentials: Dict[str, str] = data.get('reddit_credentials')
        self.blizzard_credentials: Dict[str, str] = data.get('blizzard_credentials')
        self.patreon_credentials: Dict[str, Union[str, int]] = data.get('patreon_credentials')
        self.danbooru_credentials: Dict[str, str] = data.get('danbooru_credentials')

        self.currency_api_key: str = data.get('currency_api_key')

        # mandatory field check
        mandatory_fields = {
            'token'         : self.token,
            'ipc_port'      : self.ipc_port,
            'db_credentials': self.db_credentials
        }
        for field_name, value in mandatory_fields.items():
            if value is None:
                raise mido_utils.IncompleteConfigFile(
                    f"Field '{field_name}' is a mandatory field in the config file, but is not set properly.")

    @classmethod
    def get_config(cls, bot_name: str) -> ConfigFile:
        try:
            with open(f'config_{bot_name}.json') as f:
                return cls(json.load(f))
        except FileNotFoundError:
            logging.warning(f"Config file 'config_{bot_name}.json' could not be found.\n\n"
                            f"Please fill 'config_example.json' properly, then rename it as 'config_{bot_name}.json'.")
            exit()
