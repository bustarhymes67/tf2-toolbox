# TF2 Toolbox

Cheat & bot detector, live match HUD, chat translator and more for Team Fortress 2.

This program shows who is in your TF2 match. It flags likely cheaters and bots, checks demos for cheats, translates the chat, and runs HoovyGPT, an AI chat bot that talks like the Heavy.

![TF2 Toolbox: the player list with the cheater score, then the Cheat check, Duels, Chat, Status and Help pages](docs/tf2-toolbox.gif)

*The real program with made-up players.*

## The folder

After you extract the ZIP, the folder has only these files:

| File | When |
|---|---|
| **`1 - Install.bat`** | One time: installs everything. Open it again to add or change a key. |
| **`2 - Start TF2 Toolbox.bat`** | Each time you play. |
| `README.md`, `docs` | This page. |
| `app` | The program itself. You do not need to open it. |

## Procedure: Install (one click)

1. On this page, click the green **Code** button. Click **Download ZIP**.
2. Right-click the ZIP file. Click **Extract All**.
3. Open the file **`1 - Install.bat`**.
4. Do what the black window tells you. For each question, push **Enter** to accept the answer in capitals. To skip a key, push **Enter** without a key.

If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.

The setup does all of this for you:

| Step | What the setup does | What you do |
|---|---|---|
| Python | Installs Python if it is not installed (free, from python.org). Installs the two Python packages the scanner needs. | Nothing. |
| Cheat check | Downloads demo-analysis (free, open source, [github.com/Nocrex/demo-analysis](https://github.com/Nocrex/demo-analysis)) and checks that the file is correct. | Push **Enter**. |
| Steam | Closes Steam and sets the TF2 launch options. Keeps your own launch options. | Push **Enter**. |
| Steam API key (optional) | Opens [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey) and tells you what to click. | Type `localhost`, click **Register**, copy the key, paste it in the black window. |
| steamhistory.net key (optional) | Opens [steamhistory.net/account#developer](https://steamhistory.net/account#developer). | Log in with Steam, make a key, paste it. |
| HoovyGPT (optional) | Opens [aistudio.google.com/api-keys](https://aistudio.google.com/api-keys) (Gemini, the main AI), then [console.groq.com/keys](https://console.groq.com/keys) (Groq, the backup AI). Saves the keys and lets HoovyGPT talk. | Make each key, paste it. |
| Translation backups (optional) | Opens [deepl.com/pro-api](https://www.deepl.com/pro-api) (DeepL API Free, 500,000 characters a month), then the [Azure Translator page](https://portal.azure.com/#create/Microsoft.CognitiveServicesTextTranslation) (Microsoft, free tier F0, 2 million characters a month). The order is: Google (no key), DeepL, Microsoft, Google's second address, MyMemory. Each one is asked only when the one before it fails (an error, or "too many requests": then it rests 15 minutes). Without these keys it goes Google, Google's second address, MyMemory. MyMemory only does Russian (Cyrillic) and Turkish-looking lines. | Make each key, paste it. Both ask for a card to check you're a person; the free plans cost nothing. |
| Start | Starts TF2 and the scanner. | Push **Enter**. |

All keys are free. To add a key later, open `1 - Install.bat` again. A scanner that is already running picks up a new key by itself within a few seconds.

The setup saves the keys in `C:\Users\<you>\.secrets\tf2translator\.env`, not in the scanner folder. Keep your keys secret.

## Procedure: Use the scanner

1. Start TF2. Set TF2 to **Windowed** or **Fullscreen Windowed** (TF2: **Options > Video**).
2. Open the file **`2 - Start TF2 Toolbox.bat`**. No black window stays open. This is normal. (The install can also start it for you.)
3. In the game, push **F9** to show or hide the scanner window.
4. To stop the scanner, push **F9**. Click the **X** at the top right.

| Key | Function |
|---|---|
| **F9** | Shows or hides the scanner window. |
| **F8** | Unlocks the translations, so you can move them. Push it again to lock them. |

To use HoovyGPT, open the **Duels** page and click **HoovyGPT + Duels**. It starts off each time, so it never talks by surprise. When it is on, it answers chat lines from other players from your account. Every other answer starts with `HoovyGPT:`, so players know that it is the bot. Players can type `!badbot` to mute it and `!goodbot` to unmute it.

## What the scanner shows

| Where | What |
|---|---|
| Mini HUD (top of the screen, always on) | The enemy line-up, their Medics (**MEDIC DOWN - PUSH** when one dies), and their Spies. |
| Alerts | A short message at the top of the screen when the scanner finds something. |
| **Players** page | Both teams with class, HP, kills/deaths and flags. Filters (flagged, cheaters, new accounts) and search. Click a player for the reasons, Votekick, Mark cheater, SteamHistory and chat buttons. |
| **Cheat check** page | What demo-analysis found in the demo of your match, with the tick to jump to. **Export evidence** makes a folder next to the demos for the selected player: a copy of the demo, the saved detections and `report.txt` (SteamID64, profile link, each check with its ticks and the `demo_gototick` command). **Record only with a flagged player** (on by default): TF2 records a demo only while someone flagged is in your match, so clean matches never fill your disk. The page shows if a recording is running. |
| **Duels** page | HoovyGPT on or off, running duels and their scores, the AI model and the free answers left today. |
| **Chat** page | Announcer, "ez" after your kills, post translations in chat, country kill score, auto-reconnect when idle, and the chat commands (each on or off). |
| **Status** page | The connections, whether each function works, and the keys. |
| **Help** page | Every key and every chat command, with what it does. |

## Chat commands

Other players (and you) can type these commands in chat. The **Help** page in the scanner shows all of them. You can switch each one off on the **Chat** page.

| Command | Function |
|---|---|
| `!who <name>` | Information about a player. |
| `!check <name>` | A player's class and health. `!check all` shows the classes of the other team. |
| `!kd <name>` | A player's kills, deaths and killstreak. |
| `!top` | The most kills on each team. |
| `!medic`, `!hours <name>`, `!cheaters`, `!ip <name>`, `!help` | More information commands. |
| `!speak <language> <message>` | Translates a message and says it in chat. |
| `!duel <name>` | Starts a duel score with a player. |

A part of a name is sufficient. Example: `!who iva` finds Ivan.

## What the setup does

You can read all of the code: `1 - Install.bat` and `app/tf2_setup.py`. The setup asks before each change.

1. If Python is not installed, it installs Python 3.13 from python.org with winget (the Windows package installer). If winget is not available, it opens python.org for you.
2. It installs the Python packages in `app/requirements.txt` (Pillow for pictures, tzdata for time zones).
3. If you want the cheat check, it downloads `cli.exe` from the official [demo-analysis v3 release](https://github.com/Nocrex/demo-analysis/releases/tag/v3), checks the SHA-256 checksum that GitHub publishes, and saves it as `app\tools\demo-analysis.exe`. If the checksum is wrong, it does not save the file.
4. It closes Steam (Steam deletes changes to its settings when it closes) and makes a backup copy of the Steam settings file (`localconfig.vdf`).
5. It adds these TF2 launch options. It keeps your other launch options. It does not change TF2 files.
6. It saves the keys that you paste in `C:\Users\<you>\.secrets\tf2translator\.env`.

| Option | Function |
|---|---|
| `-condebug` | TF2 writes its console (chat, kill feed, player list) into `console.log`. The scanner reads this file. |
| `-conclearlog` | TF2 starts `console.log` empty at each start, so the file does not become too large. |
| `-g15` | TF2 answers `g15_dumpplayer`: the scoreboard data (health, team, kills). |
| `-usercon`, `+rcon_password <random>` | The scanner sends commands to TF2 (RCON), for example `status` and chat lines. Only a program with the random password can do this. |
| `+ip 0.0.0.0`, `+hostport 27069`, `+net_start` | These start the network function of TF2 that RCON uses. |
| `+ds_enable 0` or `+ds_enable 2` | Only with the cheat check. `0` (the default, **Record only with a flagged player** on): TF2 records only when the scanner types `ds_record`, which it does while a player with a serious flag (or your mark) is in your match; it types `ds_stop` 1 minute after the last one leaves. `2` (that switch off): TF2 records a demo of each match. The scanner deletes demos where nothing was found. The switch also tells a running TF2 at once (`ds_enable` over RCON). |

NOTE: The scanner does not read or change the memory of the game. It only reads `console.log`, the demo files, and the answers to console commands.

## Why it doesn't trigger VAC

### What VAC looks for

VAC (Valve Anti-Cheat) runs alongside TF2 and looks for **cheats: programs that change the game process.** For example:
- code injected into the game (a DLL loaded into TF2, hooks on its functions);
- another program that reads or writes the game's memory (wallhacks read where players are, aimbots write where you aim);
- changed game files;
- fake mouse and keyboard input (aimbots, triggerbots).

TF2 Toolbox does **none** of these. It is a separate program, like Discord or OBS running beside the game. It never opens the TF2 process. It only uses three things TF2 gives every player on purpose: the **console log**, the **remote console (RCON)** and **demo recording**. The community tools [TF2 Bot Detector](https://github.com/PazerOP/tf2_bot_detector) and [MegaAntiCheat](https://github.com/MegaAntiCheat/client-backend) work the same way: they also read `console.log` and talk to TF2 over RCON.

### 1. The console log: a text file TF2 writes itself

- With the launch option `-condebug`, TF2 itself copies everything its console shows into a plain text file: `Team Fortress 2\tf\console.log`. This includes chat lines, kill messages and the answers to commands.
- The toolbox opens that file **for reading only**, the way Notepad would, and reads the new lines as they are added. It never writes to it.
- Example line: `xX_aim_god_Xx :  gg ez`. The toolbox sees "a player said something" and translates it if it's in another language.
- `-conclearlog` makes TF2 start a fresh, empty log each time it launches, so the file doesn't grow forever.

Reading a text file that the game writes on its own doesn't touch the game in any way. VAC has no reason to look at it.

### 2. RCON: TF2's own remote console

**What it is.** RCON (Remote CONsole) is a feature Valve built into every Source game. It lets a program send a line to the game's console, the same console you open with `~`, and get the console's answer back. Server admins use it every day. TF2 only accepts RCON because of these launch options:

| Launch option | What it does |
|---|---|
| `-usercon` | Turns RCON on in your game (normally only servers have it). |
| `+ip 0.0.0.0`, `+hostport 27069`, `+net_start` | Starts TF2's network listener on port 27069, where RCON connects. |
| `+rcon_password <random>` | The password. The setup makes a random one; without it TF2 refuses the connection. |

**How the toolbox uses it, step by step:**
1. It opens a normal network connection (TCP) to `127.0.0.1:27069`. That is your own computer, so nothing leaves your PC.
2. It logs in by sending the password in an RCON "auth" packet. TF2 answers "OK" or "wrong password".
3. For each command, it sends an RCON "exec" packet containing the command as text, for example `status`. TF2 runs it **exactly as if you had typed it in the console** and sends the printed answer back as text.
4. The toolbox reads that text, for example the player list from `status`.

**Every command it sends:**

| Command | When | What TF2 answers / does |
|---|---|---|
| `status` | Every 10 seconds | The players on the server: name, Steam ID, time played, ping. Any player can type it. |
| `tf_lobby_debug` | Every 10 seconds | Which team each player is on in a matchmaking lobby. |
| `g15_dumpplayer` | Every 3 seconds | The scoreboard: team, class, health, score, deaths, alive or dead. It exists for Logitech G15 keyboard screens and works because of `-g15`. |
| `say "..."` / `say_team "..."` | Only when a chat feature you turned on posts, or a player uses a chat command (`!who`, `!speak`, ...) | A normal chat message from you. |
| `ds_enable`, `ds_record`, `ds_stop`, `ds_mark` | Only with the cheat check | TF2's own demo recorder: start, stop, bookmark. |
| `callvote kick "<id> cheating"` | Only when you click **Votekick** | The same vote as from TF2's own scoreboard menu. |
| `retry` | Only with **Auto-reconnect when idle** on | Reconnects to the same server, like typing `retry`. |

None of these is a cheat command. None needs `sv_cheats`, and each one is something any player can type in their console by hand.

**Why it's safe even though it's an external program controlling TF2:**
- **The game does the work itself.** RCON is a door Valve built into the game. The toolbox doesn't break in: it knocks with the password, and TF2 runs ordinary console commands with its own code. Nothing in the game's memory or code changes. Only the console gets a text line, as if you typed it.
- **"External" isn't what VAC checks for.** External cheats are also caught. They aren't caught for running beside the game, but for **reading the game's memory** (`ReadProcessMemory`, used to find player positions) or **faking your input**. The toolbox does neither. All it knows about the match comes from the text answers above, which TF2 gives to anyone who types those commands.
- **No unfair information.** `status` and the scoreboard show what you could see yourself with `~` and Tab. Nothing hidden, like positions behind walls, is ever available through these commands.

### 3. Demos: TF2's own recordings

- TF2 records a demo, a `.dem` file in `tf\demos`, when told to with `ds_record`. That's the built-in demo recorder.
- After the match, a separate program ([demo-analysis](https://github.com/Nocrex/demo-analysis)) reads that **finished file from disk**, the same way a video player opens a video. It doesn't touch TF2.
- When nothing was found in a demo, the toolbox deletes it (only its own recordings), so your disk doesn't fill up.

### 4. Everything else

| What | How |
|---|---|
| Steam's `localconfig.vdf` | Only the setup, only while Steam is closed: it adds the launch options above to TF2's launch options. A backup is saved next to it first. You can see the result in Steam > TF2 > Properties. |
| Windows on top of the game | The player list, the mini HUD and the translations are ordinary Windows windows that float above TF2, like a Discord overlay window. Nothing is drawn **inside** the game. |
| F8 / F9 | Windows' `RegisterHotKey`: Windows tells the toolbox when these 2 keys are pressed. It doesn't see any other key, and it never presses keys or moves the mouse. |
| Internet | Steam Web API, steamhistory.net, cheater lists, Google / DeepL / Microsoft (translation), Gemini / Groq (HoovyGPT). These are requests from the toolbox, never through TF2 and never to the game server. |

### What it never touches

- **TF2's memory or process:** never opened, read or written.
- **TF2's code:** no DLL injection, no hooks, nothing drawn inside the game.
- **TF2's files:** `.vpk`, `.dll`, the `cfg` folder, `autoexec.cfg` and the `custom` folder stay as they are.
- **Your mouse and keyboard in the game:** never moved or pressed, no aiming, no shooting.
- **The game server:** it only talks to your own TF2. The server sees only what any player can do: chat, a vote, `retry`.
- **Other players' computers:** the "fake IP" is a made-up number it says in chat. It never looks up real IPs.

### Good to know

- VAC is about cheats. The chat features can still get you **reported or muted by players or community servers** if you use them to spam. The auto-chat switches (announcer, "ez", translations in chat) are off until you turn them on. The chat commands (`!who`, `!speak` and so on) answer other players, and each one can be switched off on the Chat page.
- The RCON port is protected by the random password that only the toolbox knows. Your router and Windows Firewall normally keep it closed to the internet.
- Valve doesn't publish how VAC works, so nobody can give a written guarantee. What's above is why tools that only read the console log and use RCON are not seen as cheats.

## Troubleshooting

| Problem | Action |
|---|---|
| The message "Steam is running" shows. | Right-click the Steam icon near the clock. Click **Exit**. Do the setup again. |
| The player list stays empty. | Stop TF2. Start TF2 again. Make sure that you did the setup. |
| The cheat check says demo-analysis is missing. | Open `1 - Install.bat` again and answer yes to the cheat check. |
| Nothing happens when you push F9. | Set TF2 to **Windowed** or **Fullscreen Windowed**. |
| HoovyGPT does not answer. | Open `1 - Install.bat` again and add the keys. Then switch it on on the **Duels** page. |
| Other problems | Look at the **Status** page and the file `app\scanner.log`. |

If you are still stuck, ask [Claude](https://claude.ai).

<details>
<summary>For developers</summary>

## Where everything is

All the code is in `app/`.

| File | What's in it |
|---|---|
| `tf2_lobby_scanner.py` | The start of the program: `main()` and `App`, which reads TF2's output and keeps the player list |
| `game_log.py` | How to read what TF2 prints: player list, kill feed, scoreboard, weapons |
| `player_flags.py` | Who looks suspicious, why, and how sure that is |
| `lookups.py` | Background threads: the RCON connection to TF2, Steam, cheater lists, profiles |
| `chat.py` | Everything said in chat: the spam limit, the queues, and most of the lines |
| `duels.py` | The `!duel` commands and scores |
| `demo_check.py` | The live cheat check: runs `tools/demo-analysis.exe` on the demo TF2 records, and keeps only demos where it found something |
| `ai.py` | HoovyGPT: asking the models and counting free answers and tokens |
| `hoovygpt_prompt.txt` | HoovyGPT's personality, in plain text |
| `screens.py` | The window: header, tabs (Players, Cheat check, Duels, Chat, Status, Help), the player table, alerts and tokens window |
| `settings.py` | File locations, every setting with its default, and colours |
| `tf2_translator.py` | The chat translator, which also runs on its own |
| `tf2_setup.py`, `tf2_icons.py` | First-time setup and the class icons |

## How it fits together

Background threads never touch the screen. They put what they find in a queue, and `App.run`
picks it up every 150 ms: `handle_line` for TF2's output and `handle_event` for results from the
threads. `App` is one object built from parts in different files (`ChatMixin`, `DuelsMixin`,
`AIMixin`, `ScreensMixin`), so `self.` reaches all of them.

## Tests

```bash
cd app
python -m unittest discover -s tests
```

These use no free AI answers. `tests/chat_test.py` does: it sends fixed chat situations to a
real model so you can read the replies after changing the prompt.

```bash
python tests/chat_test.py  # from app/ ctf_2fort gemini-3.5-flash-lite
```

## Kept out of git

Your settings (`scanner_config.json`), your "Mark cheater" marks (`marks.json`), logs and caches.
Players are only remembered during a match (their fake IPs, for one): nothing about them is kept
once the match ends or you join another server.

Your API keys and the RCON password are not in this folder at all. They're in
`~/.secrets/tf2translator/.env`, as `KEY=value` lines (`STEAM_API_KEY`, `STEAMHISTORY_API_KEY`,
`RCON_PASSWORD`, `GEMINI_API_KEY`, `GROQ_API_KEY`, `DEEPL_API_KEY`, `MICROSOFT_TRANSLATOR_KEY`). Keys found in an older `scanner_config.json`
are moved there the next time the scanner starts.
See `.gitignore`.

</details>
