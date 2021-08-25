# Shinobu Discord Bot

Shinobu is a Discord bot which provides service since 2016 and serves over 13,000 servers. It was a Nadeko clone at
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
- Custom ORM (Object-relational mapping) to communicate with the database
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

## List of modules:

### Music
Play music using `s.play`. You can use song names or YouTube/**Spotify** playlist/album/single links.

### Assignable Roles
You can use the `s.welcomerole` command to automatically assign a role to new members or `s.aar` to add a self-assignable role for all members which can be acquired using `s.iam`.

### Custom Reactions
You can add custom reactions with a trigger and a response using `s.acr`.

### Gambling
Use the `s.daily` command to get **250 donuts** and use them in gambling and other games!

### Games
Play race with friends (with bets if you want) or Hangman.

### Logging
Disable or enable logging in the current channel using `s.logging` and toggle between simple and detailed mode using `s.loggingmode`.

### Meta
Use `s.prefix` to change the way you call me, `s.invite` to get invite links or `s.deletedata` to delete everything I know about you.

### Moderation

Ban/mute temporarily, hold logs, manage roles, prune messages quickly to moderate your server easily.

### NSFW

Get quality NSFW images. Check out `s.autohentai` to have them posted automatically.

### Reminder

Use `s.remind` to remind yourself or someone of something.

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

```python
cd Shinobu
python3 run.py shinobu
``` 

If you needed additional steps during installation, please specify and I will add them.
