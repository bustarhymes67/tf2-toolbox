"""Everything that talks to the outside world and doesn't need the screen, running in background
threads: the RCON connection to TF2, the Steam API, steamhistory.net, the cheater lists, profile comments,
and downloading flag and class icons. Results go back to the App through its "events" queue."""

import html
import io
import json
import os
import queue
import re
import socket
import struct
import time
import urllib.parse
import urllib.request
from collections import Counter
from tf2_icons import extract_class_icons

from settings import AVATARS_DIR, CLASS_ICONS_DIR, FLAGS_DIR, LISTS_CACHE_PATH, LIST_NAMES, load_json
from game_log import G15_DONE, G15_SECONDS, USER_AGENT, to_steam64
from player_flags import ban_field

# --- RCON -------------------------------------------------------------------------

class Rcon:
    """Minimal Source RCON client."""
    AUTH, AUTH_RESPONSE, EXEC, RESPONSE = 3, 2, 2, 0

    def __init__(self, port, password):
        self.addr = ("127.0.0.1", port)
        self.password = password
        self.sock = None
        self.last_id = 100

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None

    def connect(self):
        """Connects to TF2 and logs in. A wrong password raises PermissionError."""
        self.close()
        self.sock = socket.create_connection(self.addr, timeout=3)
        self._send(1, self.AUTH, self.password)
        while True:
            rid, kind, _ = self._recv()
            if kind == self.AUTH_RESPONSE:
                if rid == -1:
                    raise PermissionError("wrong RCON password")
                return

    def command(self, cmd):
        """Runs one console command in TF2 and returns what it printed."""
        # Long output comes in several packets. An empty RESPONSE packet sent
        # right after is echoed back once the real output is done.
        cmd_id, end_id = self._next_id(), self._next_id()
        self._send(cmd_id, self.EXEC, cmd)
        self._send(end_id, self.RESPONSE, "")
        out = []
        while True:
            rid, _, body = self._recv()
            if rid == end_id:
                return "".join(out)
            if rid == cmd_id:
                out.append(body)

    def _next_id(self):
        self.last_id += 1
        return self.last_id

    def _send(self, rid, kind, body):
        data = struct.pack("<ii", rid, kind) + body.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(data)) + data)

    def _recv_exact(self, n):
        """Reads exactly n bytes: a network read can return less than was asked for."""
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("RCON connection closed")
            buf += chunk
        return buf

    def _recv(self):
        size = struct.unpack("<i", self._recv_exact(4))[0]
        data = self._recv_exact(size)
        rid, kind = struct.unpack("<ii", data[:8])
        return rid, kind, data[8:-2].decode("utf-8", errors="replace")


def rcon_worker(cfg, lines, commands, events):
    """Runs status + tf_lobby_debug every scan_seconds and g15_dumpplayer every
    other time, plus any queued commands. TF2 prints their output to console.log,
    where tail() picks it up."""
    rcon = Rcon(cfg["rcon_port"], cfg["rcon_password"])
    state = None

    def set_state(new):
        nonlocal state
        if new != state:
            state = new
            events.put(("rcon", new))

    def run(cmd):
        for line in rcon.command(cmd).splitlines():
            lines.put(line)

    while True:
        try:
            if state != "connected":
                rcon.connect()
                set_state("connected")
            run("status")
            run("tf_lobby_debug")
            deadline = time.time() + cfg["scan_seconds"]
            # The scoreboard answers over RCON (not into console.log), so polling it
            # often is cheap; it's what catches fake deaths and tracks streaks.
            while True:
                run("g15_dumpplayer")
                lines.put(G15_DONE)
                next_dump = min(deadline, time.time() + G15_SECONDS)
                while (left := next_dump - time.time()) > 0:
                    try:
                        run(commands.get(timeout=left))
                    except queue.Empty:
                        break
                if time.time() >= deadline:
                    break
        except PermissionError:
            rcon.close()
            set_state("wrong password")
            time.sleep(10)
        except OSError:
            rcon.close()
            set_state("not connected")
            time.sleep(5)


# --- Steam Web API and cheater lists ---------------------------------------------

def get_json(url):
    req = urllib.request.Request(url, headers=USER_AGENT)
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def steam_get(path, **params):
    return get_json(f"https://api.steampowered.com/{path}/?" + urllib.parse.urlencode(params))


def sourcebans(key, ids):
    """{sid: [ban, ...]} from steamhistory.net, which collects SourceBans from
    community servers."""
    data = get_json("https://steamhistory.net/api/sourcebans?"
                    + urllib.parse.urlencode({"key": key, "steamids": ids}))
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(str(data["error"]).lower())
    bans = data.get("response", []) if isinstance(data, dict) else data
    found = {}
    for ban in bans or []:
        sid = ban_field(ban, "steamid")
        if sid.isdigit():
            found.setdefault(int(sid), []).append(ban)
    return found


def tf2_hours(key, sid):
    """TF2 hours, or None when the player hides their game details or their playtime.
    Steam's "keep my total playtime private" still lists the games, but with 0
    minutes for every one of them, so 0 everywhere counts as hidden, not as 0h."""
    games = steam_get("IPlayerService/GetOwnedGames/v1", key=key, steamid=sid,
                      include_played_free_games=1)["response"].get("games") or []
    tf2 = next((g for g in games if g["appid"] == 440), None)
    if not tf2 or not any(g.get("playtime_forever") for g in games):
        return None
    return round(tf2["playtime_forever"] / 60)


def friend_ids(key, sid):
    """SteamID64s of a player's friends, or None when their friend list is private."""
    try:
        resp = steam_get("ISteamUser/GetFriendList/v1", key=key, steamid=sid, relationship="friend")
    except urllib.error.HTTPError as e:
        if e.code == 401:  # private friend list
            return None
        raise
    return {int(f["steamid"]) for f in resp.get("friendslist", {}).get("friends", [])}


TF2_CLASSES = ("Scout", "Soldier", "Pyro", "Demoman", "Heavy", "Engineer", "Medic", "Sniper", "Spy")


def tf2_stats(key, sid):
    """A player's lifetime TF2 stats from Steam, the same ones as the Records screen in TF2's menu:
    {(class, "accum" or "max", stat): value}, the stat lower case ("inumberofkills"). "accum" is the
    lifetime total, "max" the best in one life. None when their game details are private (Steam then
    answers with an error or no stats). Mann vs. Machine stats ("Scout.mvm.accum...") are left out."""
    try:
        resp = steam_get("ISteamUserStats/GetUserStatsForGame/v2", key=key, steamid=sid, appid=440)
    except urllib.error.HTTPError as e:
        if e.code in (400, 403, 500):  # private, or never played
            return None
        raise
    found = {}
    for stat in (resp.get("playerstats") or {}).get("stats") or []:
        parts = str(stat.get("name", "")).split(".")
        if len(parts) == 3 and parts[0] in TF2_CLASSES and parts[1] in ("accum", "max"):
            found[(parts[0], parts[1], parts[2].lower())] = stat.get("value", 0)
    return found or None


def tf2_stats_lookup(key, sid, asked, events):
    """Background thread for !mystats: sends ("mystats", sid, asked, stats or why not) back."""
    try:
        stats = tf2_stats(key, sid)
        result = stats if stats else "private"
    except urllib.error.HTTPError as e:
        result = "invalid key" if e.code == 401 else f"error {e.code}"
    except (OSError, ValueError, KeyError):
        result = "offline"
    events.put(("mystats", sid, asked, result))


def steam_level(key, sid):
    return steam_get("IPlayerService/GetSteamLevel/v1", key=key, steamid=sid)["response"].get("player_level")


def steam_lookup(key, batch, events):
    """Asks Steam about a batch of players and sends each answer to the App as an event."""
    ids = ",".join(map(str, batch))
    try:
        summaries = steam_get("ISteamUser/GetPlayerSummaries/v2", key=key, steamids=ids)
        bans = steam_get("ISteamUser/GetPlayerBans/v1", key=key, steamids=ids)
    except urllib.error.HTTPError as e:
        events.put(("api", "invalid key" if e.code in (401, 403) else f"error {e.code}"))
        return
    except (OSError, ValueError):
        events.put(("api", "offline"))
        return
    events.put(("api", "ok"))
    for s in summaries["response"]["players"]:
        events.put(("summary", int(s["steamid"]), s))
    for b in bans["players"]:
        events.put(("bans", int(b["SteamId"]), b))
    for sid in batch:
        for kind, lookup in (("hours", tf2_hours), ("friends", friend_ids), ("level", steam_level)):
            try:
                value = lookup(key, sid)
            except (OSError, ValueError, KeyError):
                value = None
            events.put((kind, sid, value))


def sourcebans_lookup(key, batch, events):
    """Asks steamhistory.net for a batch of players' community server bans, as events."""
    try:
        found = sourcebans(key, ",".join(map(str, batch)))
    except urllib.error.HTTPError as e:
        events.put(("sh", f"error {e.code}"))
        return
    except ValueError as e:  # the API's own error message, e.g. "invalid key"
        events.put(("sh", str(e) or "error"))
        return
    except OSError:
        events.put(("sh", "offline"))
        return
    events.put(("sh", "ok"))
    for sid in batch:
        events.put(("sourcebans", sid, found.get(sid, [])))


def lookup_worker(cfg, requests, events):
    """Background thread: collects players to look up, so a new lobby costs one call instead of 24."""
    while True:
        batch = {requests.get()}
        time.sleep(0.5)  # let the rest of a fresh lobby queue up: one call for up to 100
        while not requests.empty() and len(batch) < 100:
            batch.add(requests.get_nowait())
        if cfg["steamhistory_api_key"]:
            sourcebans_lookup(cfg["steamhistory_api_key"], batch, events)
        if cfg["steam_api_key"]:
            steam_lookup(cfg["steam_api_key"], batch, events)


def lists_worker(urls, events):
    """Downloads the cheater lists (cached for 12 hours) and indexes them by SteamID64."""
    cache = load_json(LISTS_CACHE_PATH, {})
    if time.time() - cache.get("time", 0) > 12 * 3600 or set(cache.get("lists", {})) != set(urls):
        fresh = {}
        for url in urls:
            try:
                req = urllib.request.Request(url, headers=USER_AGENT)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    fresh[url] = json.loads(resp.read().decode("utf-8"))
            except (OSError, ValueError):
                if url in cache.get("lists", {}):
                    fresh[url] = cache["lists"][url]  # keep the stale copy
        cache = {"time": time.time(), "lists": fresh}
        with open(LISTS_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f)  # compact: the SteamRep archive alone is 52k entries

    index = {}
    for url, data in cache["lists"].items():
        title = data.get("file_info", {}).get("title", "community")
        source = LIST_NAMES.get(title, title)
        for entry in data.get("players", []):
            try:
                sid = to_steam64(entry["steamid"])
            except (KeyError, ValueError):
                continue
            item = index.setdefault(sid, {"attributes": set(), "sources": []})
            item["attributes"].update(entry.get("attributes", []))
            name = ((entry.get("last_seen") or {}).get("player_name") or "").strip()
            if name and not item.get("name"):
                item["name"] = name  # as the list last saw them, for naming a cheater's friends
            if source not in item["sources"]:
                item["sources"].append(source)
            # Per list: its address (which lists copy each other), what it says and when it last saw
            # them, for the cheater score (cheat_score.list_clues).
            per = item.setdefault("by_source", {}).setdefault(source, {"urls": [], "attributes": set(), "time": 0})
            if url not in per["urls"]:
                per["urls"].append(url)
            per["attributes"].update(entry.get("attributes", []))
            seen = (entry.get("last_seen") or {}).get("time")
            if isinstance(seen, (int, float)) and seen > per["time"]:
                per["time"] = seen
    events.put(("lists", index))


def class_icons_worker(log_path, events):
    """Copies TF2's scoreboard class icons out of the game's files (first run only)."""
    try:
        events.put(("class_icons", extract_class_icons(os.path.dirname(log_path), CLASS_ICONS_DIR)))
    except (OSError, ValueError, KeyError, struct.error) as e:
        print(f"Couldn't read the class icons from TF2 ({e}); showing class names instead.")


def download_flag(code, events):
    """Saves a small flag picture for a country code once (Windows can't draw
    flag emoji), then tells the UI it's ready."""
    path = os.path.join(FLAGS_DIR, f"{code}.png")
    if not os.path.exists(path):
        try:
            req = urllib.request.Request(f"https://flagcdn.com/20x15/{code.lower()}.png", headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            os.makedirs(FLAGS_DIR, exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
        except OSError:
            return  # the column keeps showing the country code
    events.put(("flag", code, path))


AVATAR_SIZE = 64  # pixels: sharp on the 48 px player card; smaller places scale it down


def avatar_ok(path):
    """True when path is an avatar already saved at AVATAR_SIZE."""
    try:
        from PIL import Image
        with Image.open(path) as image:
            return image.size == (AVATAR_SIZE, AVATAR_SIZE)
    except (ImportError, OSError, ValueError):
        return False


def download_avatar(sid, url, events):
    """Saves a player's Steam avatar as a small PNG once (again when an older one has another
    size), then tells the App it's ready. Steam sends JPGs; Pillow converts it. Without Pillow, or
    for an address that isn't Steam's picture server, the pages keep showing the name."""
    name = re.sub(r"[^0-9a-f]", "", os.path.basename(url).split(".")[0].split("_")[0])
    host = urllib.parse.urlsplit(url).hostname or ""
    if not (url.startswith("https://") and host.endswith(".steamstatic.com") and name):
        return
    path = os.path.join(AVATARS_DIR, f"{name}.png")
    if not avatar_ok(path):
        try:
            from PIL import Image
            req = urllib.request.Request(url, headers=USER_AGENT)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = resp.read()
            os.makedirs(AVATARS_DIR, exist_ok=True)
            small = Image.open(io.BytesIO(data)).convert("RGB").resize((AVATAR_SIZE, AVATAR_SIZE),
                                                                     Image.Resampling.LANCZOS)
            small.save(path)
        except (ImportError, OSError, ValueError):
            return
    events.put(("avatar", sid, path))


# --- profile comments and bio ----------------------------------------------------

COMMENT_TEXT_RE = re.compile(r'class="commentthread_comment_text"[^>]*>(.*?)</div>', re.S)
BIO_RE = re.compile(r"<summary><!\[CDATA\[(.*?)\]\]></summary>", re.S)
WORD_ENDINGS = r"(?:s|es|er|ers|ing|ed|ted|ter|ters|ting)?"


def keyword_regex(keywords):
    """One regex that finds any profile keyword as a whole word, with its common endings."""
    words = sorted({k.strip().lower() for k in keywords if k.strip()}, key=len, reverse=True)
    if not words:
        return None
    alternatives = "|".join(re.escape(w).replace(r"\ ", r"\s*") + WORD_ENDINGS for w in words)
    return re.compile(rf"(?<!\w)({alternatives})(?!\w)", re.I)


def strip_html(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def get_text(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("utf-8", errors="replace")


def profile_scan(sid, keywords_re):
    """Keyword hits in a player's last 50 profile comments and their bio.
    These pages are public, so no API key is needed."""
    found = {"comments_visible": False, "comment_hits": 0, "comment_words": [], "bio_words": []}
    data = json.loads(get_text(
        f"https://steamcommunity.com/comment/Profile/render/{sid}/-1/?start=0&count=50"))
    if data.get("success"):
        found["comments_visible"] = True
        words = Counter()
        for comment in COMMENT_TEXT_RE.findall(data.get("comments_html", "")):
            hits = {m.lower() for m in keywords_re.findall(strip_html(comment))}
            if hits:
                found["comment_hits"] += 1
                words.update(hits)
        found["comment_words"] = [w for w, _ in words.most_common()]
    bio = BIO_RE.search(get_text(f"https://steamcommunity.com/profiles/{sid}/?xml=1"))
    if bio:
        hits = keywords_re.findall(strip_html(bio.group(1)))
        found["bio_words"] = list(dict.fromkeys(h.lower() for h in hits))
    return found


def profile_worker(cfg, requests, events):
    """Background thread: searches each player's profile comments and bio for the keywords."""
    keywords_re = keyword_regex(cfg["profile_keywords"])
    if not keywords_re:
        return
    while True:
        sid = requests.get()
        try:
            events.put(("profile", sid, profile_scan(sid, keywords_re)))
        except urllib.error.HTTPError as e:
            if e.code == 429:  # Steam says slow down: try this one again later
                requests.put(sid)
                time.sleep(60)
                continue
            events.put(("profile", sid, {"error": True}))
        except (OSError, ValueError):
            events.put(("profile", sid, {"error": True}))
        time.sleep(1)  # one player per second keeps steamcommunity.com happy
