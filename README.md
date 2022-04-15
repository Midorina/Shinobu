# Shinobu Discord Bot

Shinobu is a Discord bot which provides service since 2016 and serves over 20,000 servers. It was a Nadeko clone at
first, but then it got re-written from scratch using Discord.py.

There's a lot of TODO's around the code, which I could not find time to implement myself. If you find one and would like
to contribute, that'd be appreciated :)

### Links

- **Invite Shinobu to your server:** https://midorina.dev/shinobu
- Top.GG: https://top.gg/bot/212783784163016704
- Support server: https://discord.gg/5RXauct

## Technical Features

- Autosharding (provided by discord.py)
- Clustering
- IPC (interprocess communication) for clusters to be able to communicate with each other
- 15 Modules, 130+ Commands
- Custom ORM to communicate with the database
- Makes use of the following APIs:
  1. Reddit API (3D NSFW Content)
  2. Danbooru API (2D NSFW Content)
  3. Gelbooru API (2D NSFW Content)
  4. Rule34 API (2D NSFW Content)
  5. Sankaku Complex API (2D NSFW Content)
  6. Nekos.Life API (2D NSFW Content)
  7. Some Random API (Lyrics, Random Pictures etc.)
  8. Exchange API (Currency Conversion)
  9. Spotify API (Processing Spotify Links)
  10. Blizzard API (Searching Hearthstone Cards)
  11. Patreon API (Supporter Features)

## Installation

1. Install the repo and change your directory to the script's location:

```shell
git clone https://github.com/Midorina/Shinobu
cd Shinobu
```

2. Install the required libraries:

```shell
python3 -m pip install -r requirements.txt
```

3. Fill in the `config_example.json` file following this guide: https://github.com/Midorina/Shinobu/wiki/Config-File.  
   **Do not forget to rename it** to your bot's name afterwards (e.g. `config_shinobu.json`).


4. Run our IPC server with the port you specified in the config file (example is for port `13337`):

```shell
cd ipc
python3 ipc.py --port 13337
```

5. Finally, open a new terminal, `cd` into the code directory run the bot (example is for bot name `shinobu`):

```shell
cd Shinobu
python3 run.py shinobu
``` 

If you needed additional steps during installation, please specify and I will add them.
