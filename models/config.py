from __future__ import annotations

import json
import logging
from typing import Dict, List, Union


class ConfigFile:
    def __init__(self, data: dict, warn=False):
        # mandatory
        self.token: str = data.get('token')
        self.ipc_port: int = data.get('ipc_port')
        self.db_credentials: Dict[str, str] = data.get('db_credentials')

        # optional
        self.default_prefix: str = data.get('default_prefix', 's.')

        self.playing: str = data.get('playing', f'{self.default_prefix}help')

        self.default_embed_color: str = data.get('default_embed_color', '0xfffe91')

        self.log_channel_id: int = data.get('log_channel_id', 0)

        self.daily_amount: int = data.get('daily_amount', 250)

        self.base_waifu_price: int = data.get('base_waifu_price', 200)

        self.owner_ids: List[int] = data.get('owner_ids', [90076279646212096])

        self.cooldowns: Dict[str, int] = data.get('cooldowns', {"daily": 43200, "xp": 60})

        self.lavalink_nodes_credentials: List[Dict[str, Union[str, int]]] = data.get('lavalink_nodes_credentials')
        self.topgg_credentials: Dict[str, Union[bool, str, int]] = data.get('topgg_credentials')
        self.spotify_credentials: Dict[str, str] = data.get('spotify_credentials')
        self.reddit_credentials: Dict[str, str] = data.get('reddit_credentials')
        self.blizzard_credentials: Dict[str, str] = data.get('blizzard_credentials')
        self.patreon_credentials: Dict[str, Union[str, int]] = data.get('patreon_credentials')
        self.danbooru_credentials: Dict[str, str] = data.get('danbooru_credentials')
        self.gelbooru_credentials: Dict[str, str] = data.get('gelbooru_credentials')

        self.currency_api_key: str = data.get('currency_api_key')

        self.redis_host: str = data.get('redis_host')

        self.check_validity(warn)

    def check_validity(self, warn: bool):
        """
        These checks are done in order for the config base to be idiot-proof.
        Looks like a lot of duplicate code but it can't be helped much.
        """
        self.check_token_validity(warn)
        self.check_db_credentials_validity(warn)
        self.check_lavalink_credentials_validity(warn)
        self.check_topgg_credentials_validity(warn)
        self.check_spotify_credentials_validity(warn)
        self.check_reddit_credentials_validity(warn)
        self.check_blizzard_credentials_validity(warn)
        self.check_patreon_credentials_validity(warn)
        self.check_danbooru_credentials_validity(warn)
        self.check_gelbooru_credentials_validity(warn)
        self.check_currency_api_key_validity(warn)

        # mandatory field check
        mandatory_fields = {
            'token'         : self.token,
            'ipc_port'      : self.ipc_port,
            'db_credentials': self.db_credentials
        }
        for field_name, value in mandatory_fields.items():
            if not value:
                logging.error(
                    f"Field '{field_name}' is a mandatory field in the config file, but is not set. "
                    f"Please fill it in properly, then restart the bot.")
                exit()

    def check_token_validity(self, warn: bool):
        """No warning needed."""
        if self.token and self.token == "token":
            self.token = None

    def check_db_credentials_validity(self, warn: bool):
        """No warning needed."""
        if self.db_credentials and self.db_credentials["password"] == "CHANGE_THIS":
            self.db_credentials = None

    def check_lavalink_credentials_validity(self, warn: bool):
        if self.lavalink_nodes_credentials:
            final = self.lavalink_nodes_credentials.copy()

            # remove unconfigured node credentials
            for node in self.lavalink_nodes_credentials:
                if node["password"] == "CHANGE_THIS":
                    final.remove(node)

            self.lavalink_nodes_credentials = final

        if not self.lavalink_nodes_credentials and warn is True:
            logging.warning("Lavalink node credentials are not set. The music module will not work.")

    def check_topgg_credentials_validity(self, warn: bool):
        if self.topgg_credentials and self.topgg_credentials['webhook_port'] == 0:
            self.topgg_credentials = None

        if not self.topgg_credentials and warn is True:
            logging.warning(
                "Top.GG / DBL credentials are not set. Users will not require a vote to claim their dailies.")

    def check_spotify_credentials_validity(self, warn: bool):
        if self.spotify_credentials and self.spotify_credentials["client_id"] == "client_id":
            self.spotify_credentials = None

        if not self.spotify_credentials and warn is True:
            logging.warning("SpotifyAPI credentials are not set. Processing Spotify links will not work.")

    def check_reddit_credentials_validity(self, warn: bool):
        if self.reddit_credentials and self.reddit_credentials["client_id"] == "client_id":
            self.reddit_credentials = None

        if not self.reddit_credentials and warn is True:
            logging.warning("RedditAPI credentials are not set. Image services that use Reddit will not work.")

    def check_blizzard_credentials_validity(self, warn: bool):
        if self.blizzard_credentials and self.blizzard_credentials["client_id"] == "client_id":
            self.blizzard_credentials = None

        if not self.blizzard_credentials and warn is True:
            logging.warning("BlizzardAPI credentials are not set. Hearthstone command will not work.")

    def check_patreon_credentials_validity(self, warn: bool):
        """No warning needed."""
        if self.patreon_credentials and self.patreon_credentials["campaign_id"] == 0:
            self.patreon_credentials = None

    def check_danbooru_credentials_validity(self, warn: bool):
        """No warning needed."""
        if self.danbooru_credentials and self.danbooru_credentials["api_key"] == "api_key":
            self.danbooru_credentials = None

    def check_gelbooru_credentials_validity(self, warn: bool):
        """No warning needed."""
        if self.gelbooru_credentials and self.gelbooru_credentials["api_key"] == "api_key":
            self.gelbooru_credentials = None

    def check_currency_api_key_validity(self, warn: bool):
        if self.currency_api_key and self.currency_api_key == "api_key":
            self.currency_api_key = None

        # if not self.currency_api_key and warn is True:
        #     logging.info("ExchangeAPI key is not set. "
        #                  "Although I am designed to function without one, using one would be better.")

    @classmethod
    def get_config(cls, bot_name: str, warn: bool = False) -> ConfigFile:
        try:
            with open(f'config_{bot_name}.json') as f:
                return cls(json.load(f), warn=warn)
        except FileNotFoundError:
            logging.error(f"Config file 'config_{bot_name}.json' could not be found.\n\n"
                          f"Please fill 'config_example.json' properly, then rename it as 'config_{bot_name}.json'.")
            exit()
