"""TF2 chat translator overlay.

Tails TF2's console.log (needs the -condebug launch option), translates chat
lines that contain Cyrillic or Turkish, and shows them in a click-through overlay.

Run:  python tf2_translator.py
      (TF2 Toolbox also starts it, so with the scanner you don't need this)

Press F8 (anywhere, even in game) to unlock the overlay:
  drag            move it (position is saved when you lock it again)
  left-click      copy that line's translation, as "name: translation"
  right-click     copy the original message, as "name: original"
  middle-click    say the translation in chat (only when started by TF2 Toolbox)
Press F8 again to lock it (click-through again).
"""

import ctypes
import ctypes.wintypes
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "log_path": r"C:\Program Files (x86)\Steam\steamapps\common\Team Fortress 2\tf\console.log",
    "target_lang": "en",
    "languages": "all",        # "russian": only lines in the Russian alphabet; "all": every language (overlay buttons)
    "toggle_key": "F8",
    "x": 20,
    "y": 520,
    "width": 620,
    "max_lines": 6,
    "line_seconds": 15,
    "font_size": 13,
}

CHAT_RE = re.compile(
    r"^(?P<dead>\*DEAD\*|\*SPEC\*)?\s*(?P<team>\(TEAM\))?\s*(?P<name>.+?) :  (?P<msg>.+)$"
)
CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
# Letters only Turkish (and Azerbaijani) use, plus common words for Turks who
# type without them.
TURKISH_LETTERS_RE = re.compile(r"[ğĞşŞıİ]")  # not re.I: that makes ı and İ match a plain i
TURKISH_RE = re.compile(r"\b(?:amk|aq|amq|knk|kanka|naber|nbr|nasilsin|lan|olm|olum|abi|"
                        r"bir|ve|degil|yok|evet|hayir|tamam|neden|nasil|simdi|burda|orda|oyun|"
                        r"takim|hile|hileci|ben|sen|biz|siz|benim|senin|cok|iyi|kotu|sagol|"
                        r"tesekkurler|merhaba|selam|salak|aptal|yani|hadi|bekle|neyse|bence|"
                        r"herkes|nerde|kardes|gel|bak|napiyon|noldu|sikerim|orospu|pic)\b", re.I)
# Common words typed without Turkish letters that Google gets wrong that way
# ("takim kotu" came back as "such a cat"). Put back before translating.
TURKISH_SPELLING = dict(pair.split("=") for pair in (
    "takim=takım|takima=takıma|takimi=takımı|kotu=kötü|kotusun=kötüsün|cok=çok|degil=değil|"
    "guzel=güzel|simdi=şimdi|hayir=hayır|tesekkurler=teşekkürler|tesekkur=teşekkür|sagol=sağol|"
    "nasil=nasıl|nasilsin=nasılsın|kardes=kardeş|icin=için|hic=hiç|boyle=böyle|soyle=söyle|"
    "gor=gör|gordum=gördüm|gorduk=gördük|dusman=düşman|yardim=yardım|saldir=saldır|"
    "saldirin=saldırın|oldur=öldür|oldurun=öldürün|olduruyor=öldürüyor|olen=ölen|cik=çık|"
    "cikin=çıkın|gec=geç|bos=boş|kac=kaç|lutfen=lütfen|iyilestir=iyileştir|ust=üst|"
    "arkadas=arkadaş|arkadaslar=arkadaşlar|sagdan=sağdan|yavas=yavaş|hizli=hızlı|"
    "kullaniyor=kullanıyor|aptalsin=aptalsın|salaksin=salaksın|kotuyuz=kötüyüz|guclu=güçlü|"
    "cunku=çünkü|baslayalim=başlayalım|kazandik=kazandık|ucuncu=üçüncü").split("|"))
TURKISH_WORD_RE = re.compile(r"\b[a-z]+\b", re.I)


# English gamer chat Google takes for another language ("ez" Basque, "kys" Danish, "rekt" Esperanto).
CHAT_SLANG = set("gg ggs ggwp wp ez ezz ezpz gl hf glhf rekt kys bruh lol lel lul kek xd xdd lmao lmfao "
                 "rofl omg wtf afk brb ty thx np gj nt mb idc idk ikr smh tbh imo irl ffs stfu gtfo "
                 "noob nub n00b pog poggers sus ok k kk".split())
WORD_RE = re.compile(r"\w+")
# Common English and TF2 words: a plain-letter line made mostly of these is English and isn't sent to
# Google at all. Sending every English line got Google's "too many requests" in a busy lobby.
ENGLISH_WORDS = CHAT_SLANG | set("""
a an the i me my mine you your yours u ur he him his she her it its we us our they them their this that
these those is am are was were be been being do does did done dont doesnt didnt isnt arent wasnt cant
cannot wont wouldnt couldnt shouldnt im ive id ill youre youve hes shes its were theyre thats whats
have has had having will would can could should shall may might must not no yes yeah yea yep nah nope
and or but if so then than because cause cuz bc just only also too very really still even again ever
never always now here there where when why how what who whom which while all any some every each
other another more most less much many few lot lots of in on at to from for with without about into
out up down off over under after before by as like get got go going gone went come came coming make
made take took give gave see saw seen look know knew think thought want need say said tell told play
playing played win won lose lost kill killed killing die died dead dying shoot shot help stop try
let keep put use used one two three four five first last good bad bro dude man guys guy team enemy
enemies game games match map round time back well right left fuck fucking fucked shit damn hell ass
bitch hacker hackers cheater cheaters cheating cheat cheats bot bots hack hacks aimbot kick vote ban
report spy spies sniper snipers medic heavy scout pyro engi engie engineer demo demoman soldier sentry
uber dispenser tele teleporter intel cart point push defend attack crit crits nice great sorry thanks
thank please lmao haha hahaha yo hey hi hello bye gl hf rip lag laggy ping server wait fast slow
ready oh wow hehe hate love welcome random unfair idiot stupid meme sry cool fun funny best worst
""".split())


def looks_english(msg):
    """True for a line in plain letters where most words are common English ones: "spy is crocket",
    "nice shot". "hola amigos" or "bonjour tout le monde" still go to the translator."""
    if re.search(r"[^\x00-\x7f]", msg):
        return False
    words = WORD_RE.findall(msg.lower())
    return not words or sum(w in ENGLISH_WORDS for w in words) * 2 > len(words)


def not_really_foreign(msg, text):
    """True for an English line Google guessed as another language: its "translation" is the same
    text ("bruh", "1v1 me", "f1"), or it's only gamer slang ("gg ez", "kys")."""
    def bare(s):
        return "".join(WORD_RE.findall(s.lower()))
    words = WORD_RE.findall(msg.lower())
    return bare(text) == bare(msg) or bool(words) and all(w in CHAT_SLANG for w in words)


def turkish(msg):
    return bool(TURKISH_LETTERS_RE.search(msg) or TURKISH_RE.search(msg))


def turkish_spelling(msg):
    def fix(m):
        word = m.group()
        fixed = TURKISH_SPELLING.get(word.lower())
        return fixed.upper() if fixed and word.isupper() and len(word) > 1 else fixed or word
    return TURKISH_WORD_RE.sub(fix, msg)


KEY_COLOR = "#010101"  # painted pixels of this color become transparent
UNLOCKED_BG = "#1e1e1e"
HISTORY_SIZE = 50


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    if cfg.pop("only_cyrillic", False):  # the switch from before the overlay's buttons
        cfg["languages"] = "russian"
    return cfg


def on_screen(x, y):
    """True if a connected monitor shows the point x, y."""
    return bool(ctypes.windll.user32.MonitorFromPoint(ctypes.wintypes.POINT(x, y), 0))


# The overlay's two buttons (shown while it's unlocked): setting value -> its text.
LANGUAGE_MODES = {"russian": "Russian only", "all": "All languages"}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def parse_chat(line):
    m = CHAT_RE.match(line.strip())
    if not m:
        return None
    return m.group("name"), m.group("msg"), bool(m.group("team"))


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


def google(text, target, source="auto"):
    data = get_json("https://translate.googleapis.com/translate_a/single?" + urllib.parse.urlencode(
        {"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text}))
    return "".join(part[0] for part in data[0] if part[0]), (data[2] or "?")


def google_chrome(text, target, source="auto"):
    """The endpoint Chrome's translate extension uses: Google limits it separately."""
    data = get_json("https://clients5.google.com/translate_a/t?" + urllib.parse.urlencode(
        {"client": "dict-chrome-ex", "sl": source, "tl": target, "q": text}))
    first = data[0]
    return (first[0], first[1]) if isinstance(first, list) else (first, "?")


def mymemory(text, target, source="auto"):
    """Free with a daily limit. It needs the source language, so it only takes
    Cyrillic messages (as Russian) and Turkish-looking ones."""
    if source == "auto":
        source = "ru" if CYRILLIC_RE.search(text) else "tr" if turkish(text) else None
    if not source:
        raise ValueError("source language unknown")
    data = get_json("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(
        {"q": text, "langpair": f"{source}|{target}"}))
    if data.get("responseStatus") != 200:
        raise ValueError(data.get("responseDetails") or "MyMemory error")
    return data["responseData"]["translatedText"], source


TRANSLATORS = [google, google_chrome, mymemory]
resting_until = {}   # translator -> time it may be tried again after "too many requests"
cache = {}           # (text, target, source) -> (translation, lang): chat repeats a lot


SERVICE_NAMES = {"google": "Google", "google_chrome": "Google's second address", "mymemory": "MyMemory"}


def translator_health(now=None):
    """("ok" | "warn" | "bad", what's going on) for the scanner's Status page: which of the free
    services are resting after "too many requests", and until when."""
    now = now or time.time()
    resting = {t: until for t, until in resting_until.items() if until > now}
    if not resting:
        return "ok", "working"
    names = ", ".join(SERVICE_NAMES.get(t.__name__, t.__name__) for t in TRANSLATORS if t in resting)
    if len(resting) >= len(TRANSLATORS):
        back = time.strftime("%H:%M", time.localtime(min(resting.values())))
        return "bad", f"every service said too many requests: nothing is translated until {back}"
    back = time.strftime("%H:%M", time.localtime(max(resting.values())))
    return "warn", f"{names} resting until {back} (too many requests): the others take over"


def translate(text, target, source="auto"):
    """Returns (translation, source_lang). Tries free services in turn: one that
    says "too many requests" is left alone for 15 minutes."""
    if (text, target, source) in cache:
        return cache[(text, target, source)]
    error = None
    for translator in TRANSLATORS:
        if resting_until.get(translator, 0) > time.time():
            continue
        try:
            result = translator(text, target, source)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                resting_until[translator] = time.time() + 15 * 60
                print(f"Translator: {translator.__name__} said {e.code} (too many requests): "
                      f"not asked again for 15 minutes", flush=True)
            error = e
            continue
        except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
            error = e
            continue
        if len(cache) > 500:
            cache.clear()
        if source != "auto":
            result = result[0], source
        cache[(text, target, source)] = result
        return result
    raise error or RuntimeError("every translation service is resting")


def claim_instance(name):
    """True if no other program holds this name, which it then keeps for as long
    as this process runs."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW(None, False, name)  # released when this process exits
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def single_instance(name, message="Already running in another window; close that one first."):
    """Exits if this script is already running (e.g. its .bat was opened twice),
    so chat doesn't get translated twice and Steam/Google aren't asked twice."""
    if not claim_instance(name):
        if ctypes.windll.kernel32.GetConsoleWindow():
            print(message)
        else:  # started without a console: a print would go nowhere
            ctypes.windll.user32.MessageBoxW(None, message, "TF2 tools", 0x40)
        sys.exit(1)


def tail(path, out):
    """Pushes each new line appended to path. Starts at the end of the file."""
    while not os.path.exists(path):
        time.sleep(1)
    f = open(path, "rb")
    f.seek(0, os.SEEK_END)
    buf = b""
    while True:
        chunk = f.read()
        if chunk:
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for raw in lines:
                out.put(raw.decode("utf-8", errors="replace").rstrip("\r"))
        else:
            # File was recreated or truncated (e.g. TF2 restarted): start over.
            try:
                if os.path.getsize(path) < f.tell():
                    f.close()
                    f = open(path, "rb")
                    buf = b""
            except OSError:
                pass
            time.sleep(0.15)


# Languages "!speak <language> <message>" takes, by name, as Google Translate codes them.
# A code itself (ru, de, ...) and the first 3+ letters of a name ("rus", "ger") work too.
LANGUAGES = {
    "english": "en", "russian": "ru", "turkish": "tr", "dutch": "nl", "german": "de", "french": "fr",
    "spanish": "es", "portuguese": "pt", "brazilian": "pt", "italian": "it", "polish": "pl",
    "ukrainian": "uk", "czech": "cs", "slovak": "sk", "hungarian": "hu", "romanian": "ro",
    "bulgarian": "bg", "serbian": "sr", "croatian": "hr", "bosnian": "bs", "slovenian": "sl",
    "macedonian": "mk", "albanian": "sq", "greek": "el", "swedish": "sv", "norwegian": "no",
    "danish": "da", "finnish": "fi", "icelandic": "is", "estonian": "et", "latvian": "lv",
    "lithuanian": "lt", "belarusian": "be", "georgian": "ka", "armenian": "hy", "azerbaijani": "az",
    "kazakh": "kk", "uzbek": "uz", "mongolian": "mn", "chinese": "zh-CN", "mandarin": "zh-CN",
    "japanese": "ja", "korean": "ko", "arabic": "ar", "hebrew": "iw", "persian": "fa", "farsi": "fa",
    "hindi": "hi", "urdu": "ur", "bengali": "bn", "indonesian": "id", "malay": "ms", "thai": "th",
    "vietnamese": "vi", "filipino": "tl", "tagalog": "tl", "afrikaans": "af", "swahili": "sw",
    "irish": "ga", "welsh": "cy", "latin": "la",
    # as players may write them in their own language
    "русский": "ru", "türkçe": "tr", "turkce": "tr", "nederlands": "nl", "deutsch": "de",
    "français": "fr", "francais": "fr", "español": "es", "espanol": "es", "português": "pt",
    "portugues": "pt", "italiano": "it", "polski": "pl", "українська": "uk",
}


def language_code(word):
    """The Google Translate code for a language as typed in "!speak <language> ...", or None."""
    word = word.lower().strip(".,:;!?")
    if word in LANGUAGES:
        return LANGUAGES[word]
    if word == "zh":
        return "zh-CN"
    if word in LANGUAGES.values():
        return word
    starts = {code for name, code in LANGUAGES.items() if len(word) >= 3 and name.startswith(word)}
    return starts.pop() if len(starts) == 1 else None


def translate_chat(msg, target):
    """Google spots Turkish typed without its letters on its own ("sniperi
    oldurun" -> tr), but not always ("takim kotu" -> Polish), and translates it
    better with the letters put back. Common Turkish words settle it."""
    text, lang = translate(msg, target)
    if CYRILLIC_RE.search(msg) or lang == target and not TURKISH_LETTERS_RE.search(msg):
        return text, lang
    if lang == "tr" or turkish(msg):
        fixed = turkish_spelling(msg)
        if fixed != msg or lang != "tr":
            return translate(fixed, target, "tr")
    return text, lang


def translate_any(text, target):
    """For !speak: translate_chat, and when the Google services are resting, MyMemory with the
    source guessed (Cyrillic: Russian, Turkish-looking: Turkish, else English)."""
    try:
        return translate_chat(text, target)
    except Exception:
        source = "ru" if CYRILLIC_RE.search(text) else "tr" if turkish(text) else "en"
        if source == target:
            raise
        return mymemory(text, target, source)


# Names of the players in your match, set by TF2 Toolbox: kept as they are in a translation,
# so "tomato" isn't turned into "hair salon". Only names of 3 or more letters.
KEEP_NAMES = set()
NAME_MARK = 90731  # a name is swapped for a number from here while the line is translated: numbers stay put


def hide_names(msg, names=None):
    """(the line with every known player name swapped for a number, {number: name}). Longest
    names first, so "tomato" goes before "kap"; letters around a name must not be letters."""
    found = {}
    for name in sorted(names if names is not None else KEEP_NAMES, key=len, reverse=True):
        pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.I)
        while (m := pattern.search(msg)):
            mark = str(NAME_MARK + len(found))
            found[mark] = m.group(0)
            msg = msg[:m.start()] + mark + msg[m.end():]
    return msg, found


def show_names(text, found):
    for mark, name in found.items():
        text = text.replace(mark, name)
    return text


def worker(cfg, lines, results):
    while True:
        parsed = parse_chat(lines.get())
        if not parsed:
            continue
        name, msg, team = parsed
        if msg.lstrip().lower().startswith(("!speak", "!who", "!check", "!medic", "!top", "!kd", "!hours", "!ip",
                                            "!cheaters", "!help", "!kick")):  # TF2 Toolbox answers those itself
            continue
        if cfg["languages"] == "russian" and not CYRILLIC_RE.search(msg):
            continue  # Russian only: a line without the Russian alphabet isn't sent anywhere
        hidden, names = hide_names(msg)
        rest = hidden
        for mark in names:
            rest = rest.replace(mark, " ")
        if not WORD_RE.search(rest):
            continue  # only names (and punctuation): nothing to translate
        if cfg["target_lang"] == "en" and looks_english(rest):  # not worth one of Google's requests
            continue
        try:
            text, lang = translate_chat(hidden, cfg["target_lang"])
            text = show_names(text, names)
        except Exception:
            # Only lines that surely aren't English say they failed: the rest are most likely English.
            if not (CYRILLIC_RE.search(msg) or turkish(msg)):
                continue
            text, lang = msg + "  (translation failed)", "?"
        if lang == cfg["target_lang"]:
            continue
        if lang != "?" and not CYRILLIC_RE.search(msg) and not_really_foreign(msg, text):
            continue
        results.put({"name": name, "text": text, "original": msg, "lang": lang, "team": team})


# Keys by name, as Windows numbers them (virtual-key codes).
NAMED_KEYS = {"END": 0x23, "HOME": 0x24, "INSERT": 0x2D, "DELETE": 0x2E, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
              "PAUSE": 0x13, "SCROLLLOCK": 0x91}


def key_to_vk(key):
    key = key.strip().upper().replace(" ", "")
    if key.startswith("F") and key[1:].isdigit():
        return 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isalnum():
        return ord(key)
    if key in NAMED_KEYS:
        return NAMED_KEYS[key]
    raise ValueError(f"Unsupported key {key!r}, use F1-F24, a letter or digit, or one of {', '.join(NAMED_KEYS)}")


def hotkey_listener(vk, on_press, name="the toggle key"):
    """Global hotkey: fires even while TF2 has focus."""
    user32 = ctypes.windll.user32
    MOD_NOREPEAT, WM_HOTKEY = 0x4000, 0x0312
    if not user32.RegisterHotKey(None, 1, MOD_NOREPEAT, vk):
        print(f"Could not register {name} (another program may be using it, and Windows keeps F12 for itself).")
        return
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message == WM_HOTKEY:
            on_press()


def set_click_through(root, enabled):
    user32 = ctypes.windll.user32
    hwnd = user32.GetParent(root.winfo_id())
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x20
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    # layered | toolwindow (no taskbar/alt-tab) | noactivate (never steals focus from TF2)
    style |= 0x80000 | 0x80 | 0x08000000
    style = style | WS_EX_TRANSPARENT if enabled else style & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class Overlay:
    def __init__(self, cfg, master=None):
        """master: another program's Tk window to live in (TF2 Toolbox),
        so both run in one process instead of each needing its own."""
        self.cfg = cfg
        self.history = []   # newest last; each entry is a result dict plus "expires"
        self.unlocked = False
        self.status = ""    # short feedback shown in unlocked mode, e.g. "Copied"
        self.press = None   # drag/click state while a mouse button is down
        self.on_say = None  # set by TF2 Toolbox: says an entry in chat over RCON
        self.on_add = None  # set by TF2 Toolbox: gets each new translation

        self.root = root = tk.Toplevel(master) if master else tk.Tk()
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        self.line_h = cfg["font_size"] * 2 + 6
        height = (cfg["max_lines"] + 1) * self.line_h + 10
        if not on_screen(cfg["x"] + 40, cfg["y"] + 10):
            cfg["x"], cfg["y"] = 20, 520  # its monitor isn't connected now: back to the main screen
        root.geometry(f"{cfg['width']}x{height}+{cfg['x']}+{cfg['y']}")
        root.configure(bg=KEY_COLOR)
        root.attributes("-transparentcolor", KEY_COLOR)
        self.canvas = c = tk.Canvas(root, bg=KEY_COLOR, highlightthickness=0)
        c.pack(fill="both", expand=True)
        self.font = ("Segoe UI Semibold", cfg["font_size"])
        self.small_font = ("Segoe UI", max(9, cfg["font_size"] - 3))

        c.bind("<ButtonPress-1>", self._press)
        c.bind("<B1-Motion>", self._motion)
        c.bind("<ButtonRelease-1>", self._release)
        c.bind("<Button-3>", self._copy_original)
        c.bind("<Button-2>", self._say)
        root.update_idletasks()
        set_click_through(root, True)

    # --- lock / unlock -------------------------------------------------------

    def toggle(self):
        self.unlocked = not self.unlocked
        self.status = ""
        set_click_through(self.root, not self.unlocked)
        self.canvas.configure(bg=UNLOCKED_BG if self.unlocked else KEY_COLOR)
        if not self.unlocked:
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
            save_config(self.cfg)
        self.redraw()

    # --- mouse (only reaches us while unlocked) --------------------------------

    def _entry_under_mouse(self):
        for tag in self.canvas.gettags("current"):
            if tag.startswith("e"):
                return self.history[int(tag[1:])]
        return None

    def _mode_under_mouse(self):
        for tag in self.canvas.gettags("current"):
            if tag.startswith("mode_"):
                return tag[5:]
        return None

    def set_languages(self, mode):
        """A button: Russian only, or All languages. Saved, and used from the next chat line."""
        if mode in LANGUAGE_MODES and mode != self.cfg["languages"]:
            self.cfg["languages"] = mode
            save_config(self.cfg)
            self._show_status(f"Translating: {LANGUAGE_MODES[mode].lower()}")

    def _press(self, e):
        mode = self._mode_under_mouse()
        if mode:
            self.press = None
            self.set_languages(mode)
            return
        self.press = {
            "x": e.x_root, "y": e.y_root,
            "wx": self.root.winfo_x(), "wy": self.root.winfo_y(),
            "entry": self._entry_under_mouse(), "dragging": False,
        }

    def _motion(self, e):
        p = self.press
        if not p:
            return
        dx, dy = e.x_root - p["x"], e.y_root - p["y"]
        if not p["dragging"] and abs(dx) + abs(dy) < 4:
            return  # small wobble during a click is not a drag
        p["dragging"] = True
        self.root.geometry(f"+{p['wx'] + dx}+{p['wy'] + dy}")

    def _release(self, _e):
        p, self.press = self.press, None
        if p and not p["dragging"] and p["entry"]:
            self._copy(f'{p["entry"]["name"]}: {p["entry"]["text"]}', "Copied translation")

    def _copy_original(self, _e):
        entry = self._entry_under_mouse()
        if entry:
            self._copy(f'{entry["name"]}: {entry["original"]}', "Copied original")

    def _say(self, _e):
        entry = self._entry_under_mouse()
        if entry and self.on_say:
            self.on_say(entry)
            self._show_status("Said in chat")

    def _copy(self, text, status):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self._show_status(status)

    def _show_status(self, status):
        self.status = status
        self.redraw()
        self.root.after(1500, self._clear_status, status)

    def _clear_status(self, status):
        if self.status == status:
            self.status = ""
            self.redraw()

    # --- drawing -------------------------------------------------------------

    def add(self, entry):
        entry["expires"] = time.time() + self.cfg["line_seconds"]
        self.history = (self.history + [entry])[-HISTORY_SIZE:]
        self.redraw()
        if self.on_add:
            self.on_add(entry)

    def visible(self):
        """(index, entry) pairs to draw. Unlocked shows recent history so you can copy."""
        now = time.time()
        items = list(enumerate(self.history))
        if not self.unlocked:
            items = [(i, e) for i, e in items if e["expires"] > now]
        return items[-self.cfg["max_lines"]:]

    def redraw(self):
        c = self.canvas
        c.delete("all")
        wrap = self.cfg["width"] - 10
        top_limit = 0
        if self.unlocked:
            key = self.cfg["toggle_key"]
            hint = self.status or f"{key}: lock  ·  drag: move  ·  click: copy  ·  right-click: original"
            c.create_text(6, 4, text=hint, anchor="nw", font=self.small_font,
                          fill="#7CFC9A" if self.status else "#bbbbbb")
            # The two buttons, right of the hint: the chosen one lit up.
            x = self.cfg["width"] - 6
            for mode in reversed(LANGUAGE_MODES):
                on = self.cfg["languages"] == mode
                label = c.create_text(x - 8, 6, text=LANGUAGE_MODES[mode], anchor="ne", font=self.small_font,
                                      fill="#ffffff" if on else "#bbbbbb", tags=(f"mode_{mode}",))
                x0, y0, x1, y1 = c.bbox(label)
                box = c.create_rectangle(x0 - 8, y0 - 2, x1 + 8, y1 + 2, fill="#5b8cff" if on else "#2a2f38",
                                         outline="", tags=(f"mode_{mode}",))
                c.tag_lower(box, label)
                x = x0 - 22
            top_limit = self.line_h + 4
        y = c.winfo_height() - 5
        for i, e in reversed(self.visible()):
            label = f"[{e['lang'].upper()}]{' (TEAM)' if e['team'] else ''} {e['name']}: {e['text']}"
            # Shadow first, then text, so it stays readable on any background.
            shadow = c.create_text(6, y + 1, text=label, anchor="sw", width=wrap,
                                   font=self.font, fill="black", tags=(f"e{i}",))
            c.create_text(5, y, text=label, anchor="sw", width=wrap, tags=(f"e{i}",),
                          font=self.font, fill="#ffd866" if e["team"] else "#9fe7ff")
            top = c.bbox(shadow)[1]
            if top < top_limit:
                c.delete(f"e{i}")
                break
            y = top - 4

    def run(self, results, toggles):
        self.start(results, toggles)
        self.root.mainloop()

    def start(self, results, toggles):
        """Schedules the overlay's updates on the Tk loop that's already running."""
        shown = []

        def tick():
            nonlocal shown
            while not toggles.empty():
                toggles.get()
                self.toggle()
            while not results.empty():
                self.add(results.get())
            now_shown = [i for i, _ in self.visible()]
            if now_shown != shown:  # something expired
                shown = now_shown
                self.redraw()
            self.root.after(150, tick)

        def keep_on_top():
            self.root.attributes("-topmost", True)
            self.root.lift()
            self.root.after(2000, keep_on_top)

        tick()
        keep_on_top()


def start_translator(master=None, chat_lines=None):
    """Starts reading chat and translating it. With master (TF2 Toolbox's
    window) the overlay joins that program; returns the overlay and its queues.
    chat_lines: a queue the caller fills with console.log's chat lines, so the file
    isn't read twice; without it the translator reads console.log itself."""
    cfg = load_config()
    vk = key_to_vk(cfg["toggle_key"])
    if not os.path.exists(cfg["log_path"]):
        print(f"Waiting for {cfg['log_path']}")
        print("Make sure TF2 has -condebug in its launch options.")
    lines, results, toggles = chat_lines or queue.Queue(), queue.Queue(), queue.Queue()
    if chat_lines is None:
        threading.Thread(target=tail, args=(cfg["log_path"], lines), daemon=True).start()
    threading.Thread(target=worker, args=(cfg, lines, results), daemon=True).start()
    threading.Thread(target=hotkey_listener, args=(vk, lambda: toggles.put(1)), daemon=True).start()
    print(f"Translator running. Press {cfg['toggle_key']} to unlock/lock the translation overlay.")
    overlay = Overlay(cfg, master)
    if master:
        overlay.start(results, toggles)
    return overlay, results, toggles


def main():
    single_instance("tf2_chat_translator")
    overlay, results, toggles = start_translator()
    print("Close this window to stop.")
    overlay.run(results, toggles)


if __name__ == "__main__":
    main()
