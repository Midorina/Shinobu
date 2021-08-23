# Shinobu Discord Bot 
Shinobu is a Discord bot which provides service since 2016 and serves over 13,000 servers.
It was a Nadeko clone at first, but then it got re-written from scratch using Discord.py.  

**Invite Shinobu to your server:** https://midorina.dev/shinobu

Support server: https://discord.gg/5RXauct

This is the complete source code of Shinobu. It was not intended to be public at first, so there isn't any instructions to set it up yourself yet, but soon™️.

There's a lot of TODO's around the code, which I could not find time to implement myself. If you find one and would like to contribute, that'd be appreciated.

## Technical Features
- Autosharding (provided by discord.py)
- Clustering
- IPC (interprocess communication) for clusters to be able to communicate with each other
- 15 Modules, 130 Commands
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

### Searches
Search something using `s.google`/`s.urban` or convert currencies using `s.convert`.
                
### Shitposting
RNG shitposting using `s.8ball`, `s.pp` and `s.howgay`.  
Image filters using `s.gay`, `s.wasted`, `s.triggered` and `s.ytcomment`.
                
### Waifu
Claim someone as your waifu using `s.claim`, send gifts to them using `s.gift` and check your stats using `s.waifustats`.
                
### XP / Leveling
Check your xp status using `s.xp`, set level rewards using `s.xprolereward` and compete against others in `s.xplb` and `s.xpglb`!   



## Other Information
You can use type `s.help` to get a help message.

You can use `s.help ModuleName` (eg. `s.help reminder`) to see a list of all of the commands in that module. 

For a specific command help, use `s.help CommandName` (eg. `s.help play`)

Prefix can be changed using the `s.prefix` command.  
If you forget the prefix, you can call Shinobu by pinging her. (eg. @Shinobu prefix)

**If you have problems with Shinobu, or want to join donut events, feel free to join the support server.**