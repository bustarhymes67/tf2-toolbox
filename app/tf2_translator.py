"""TF2 Toolbox's chat translator: translates chat lines in other languages and shows them in a
click-through overlay over the game. The toolbox (tf2_lobby_scanner.py) starts it and hands it the
chat lines it reads from TF2; its settings are the toolbox's translator_... settings (settings.py).

Press F8 (anywhere, even in game) to unlock the overlay:
  drag            move it (position is saved when you lock it again)
  left-click      copy that line's translation, as "name: translation"
  right-click     copy the original message, as "name: original"
  middle-click    say the translation in chat
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
import tkinter.font as tkfont
import urllib.error
import urllib.parse
import urllib.request

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

# The overlay's look: the Tactical style of TF2 Toolbox's window (the same colours as its settings.py).
UNLOCKED_BG = "#07090c"   # the whole window while it's unlocked (F8)
LINE_BG = "#05070a"       # the dark box behind each line, so it reads on any map
EDGE = "#283342"          # thin lines: the unlocked window's outline, the buttons
ACCENT = "#2de2c8"        # the bar left of each line, the language tag, the chosen button
ON_ACCENT = "#03211d"     # dark text on the accent
LINE_TEXT = "#f1f4f6"     # the translation
NAME_FG = "#a3b0be"       # who said it (all chat)
TEAM_FG = "#3fdc8a"       # who said it, and the TEAM tag, in team chat
HINT_FG = "#7b8996"       # the unlocked window's help line
UI_FONT = "Bahnschrift"
NAME_FONT = "Bahnschrift SemiBold"
LABEL_FONT = "Bahnschrift SemiBold SemiConden"
MONO_FONTS = ("Cascadia Mono", "Consolas")
BRACKET = 8               # the accent corners of the unlocked window
HISTORY_SIZE = 50


def on_screen(x, y):
    """True if a connected monitor shows the point x, y."""
    return bool(ctypes.windll.user32.MonitorFromPoint(ctypes.wintypes.POINT(x, y), 0))


# The overlay's two buttons (shown while it's unlocked): setting value -> its text.
LANGUAGE_MODES = {"russian": "Russian only", "all": "All languages"}


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


# The key of the service that needs one (DeepL). TF2 Toolbox points this at its settings,
# so a key saved while it runs (setup, secrets file) is used at once. Empty: those services are skipped.
KEYS = {}


def post_json(url, body, headers):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read().decode("utf-8"))


# Google's codes where DeepL uses another one.
DEEPL_TARGETS = {"en": "EN-US", "pt": "PT-BR", "zh-CN": "ZH-HANS", "iw": "HE", "no": "NB"}


def deepl(text, target, source="auto"):
    """DeepL API Free: 500,000 characters a month with a free key (deepl.com/pro-api).
    A free key ends in ":fx" and has its own address."""
    key = KEYS.get("deepl_api_key", "")
    host = "api-free.deepl.com" if key.endswith(":fx") else "api.deepl.com"
    body = {"text": [text], "target_lang": DEEPL_TARGETS.get(target, target.split("-")[0].upper())}
    if source != "auto":
        body["source_lang"] = source.split("-")[0].upper()
    data = post_json(f"https://{host}/v2/translate", body, {"Authorization": f"DeepL-Auth-Key {key}"})
    first = data["translations"][0]
    return first["text"], first.get("detected_source_language", "?").lower()


deepl.needs_key = "deepl_api_key"


# In this order: Google (free, no key), then DeepL (free key, when you made one), then MyMemory.
# Each is asked only when the one before it fails.
TRANSLATORS = [google, deepl, mymemory]
resting_until = {}   # translator -> time it may be tried again after "too many requests"
cache = {}           # (text, target, source) -> (translation, lang): chat repeats a lot


SERVICE_NAMES = {"google": "Google", "deepl": "DeepL", "mymemory": "MyMemory"}
REST_CODES = (403, 429, 456)  # too many requests / out of free characters (DeepL says 456)


def active_translators():
    """The services that can be asked: those that need a key only once one is set."""
    return [t for t in TRANSLATORS if not getattr(t, "needs_key", None) or KEYS.get(t.needs_key)]


def translator_health(now=None):
    """("ok" | "warn" | "bad", what's going on) for the scanner's Status page: which of the free
    services are resting after "too many requests", and until when."""
    now = now or time.time()
    active = active_translators()
    resting = {t: until for t, until in resting_until.items() if until > now and t in active}
    if not resting:
        return "ok", "working"
    names = ", ".join(SERVICE_NAMES.get(t.__name__, t.__name__) for t in active if t in resting)
    if len(resting) >= len(active):
        back = time.strftime("%H:%M", time.localtime(min(resting.values())))
        return "bad", f"every service said too many requests: nothing is translated until {back}"
    back = time.strftime("%H:%M", time.localtime(max(resting.values())))
    return "warn", f"{names} resting until {back} (too many requests): the others take over"


def translate(text, target, source="auto"):
    """Returns (translation, source_lang). Tries the services in turn (Google, DeepL,
    MyMemory): one that says "too many requests" is left alone for 15 minutes."""
    if (text, target, source) in cache:
        return cache[(text, target, source)]
    error = None
    for translator in active_translators():
        if resting_until.get(translator, 0) > time.time():
            continue
        try:
            result = translator(text, target, source)
        except urllib.error.HTTPError as e:
            if e.code in REST_CODES:
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
    """For !speak: translate_chat, and when Google and DeepL can't, MyMemory with the
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
        if cfg["translator_languages"] == "russian" and not CYRILLIC_RE.search(msg):
            continue  # Russian only: a line without the Russian alphabet isn't sent anywhere
        hidden, names = hide_names(msg)
        rest = hidden
        for mark in names:
            rest = rest.replace(mark, " ")
        if not WORD_RE.search(rest):
            continue  # only names (and punctuation): nothing to translate
        if cfg["translator_target_lang"] == "en" and looks_english(rest):  # not worth one of Google's requests
            continue
        try:
            text, lang = translate_chat(hidden, cfg["translator_target_lang"])
            text = show_names(text, names)
        except Exception:
            # Only lines that surely aren't English say they failed: the rest are most likely English.
            if not (CYRILLIC_RE.search(msg) or turkish(msg)):
                continue
            text, lang = msg + "  (translation failed)", "?"
        if lang == cfg["translator_target_lang"]:
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


def spaced(text):
    """Capitals with a little room between the letters, like TF2 Toolbox's labels."""
    return "\u200a".join(text.upper())


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
    def __init__(self, cfg, master, save=None):
        """cfg: the toolbox's settings (its translator_... ones are the overlay's); master: the
        toolbox's Tk root, which the overlay lives in; save(cfg) saves the settings."""
        self.cfg = cfg
        self.save = save or (lambda cfg: None)
        self.history = []   # newest last; each entry is a result dict plus "expires"
        self.unlocked = False
        self.status = ""    # short feedback shown in unlocked mode, e.g. "Copied"
        self.press = None   # drag/click state while a mouse button is down
        self.on_say = None  # set by TF2 Toolbox: says an entry in chat over RCON
        self.on_add = None  # set by TF2 Toolbox: gets each new translation

        self.root = root = tk.Toplevel(master)
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        self.line_h = cfg["translator_font_size"] * 2 + 6
        height = (cfg["translator_max_lines"] + 1) * self.line_h + 10
        if not on_screen(cfg["translator_x"] + 40, cfg["translator_y"] + 10):
            cfg["translator_x"], cfg["translator_y"] = 20, 520  # its monitor isn't connected now: back to the main screen
        root.geometry(f"{cfg['translator_width']}x{height}+{cfg['translator_x']}+{cfg['translator_y']}")
        root.configure(bg=KEY_COLOR)
        root.attributes("-transparentcolor", KEY_COLOR)
        self.canvas = c = tk.Canvas(root, bg=KEY_COLOR, highlightthickness=0)
        c.pack(fill="both", expand=True)
        size = cfg["translator_font_size"]
        mono = next((f for f in MONO_FONTS if f in tkfont.families(root)), "Consolas")
        self.font = tkfont.Font(root, family=UI_FONT, size=size)
        self.name_font = tkfont.Font(root, family=NAME_FONT, size=size)
        self.tag_font = tkfont.Font(root, family=mono, size=max(8, size - 4), weight="bold")
        self.small_font = tkfont.Font(root, family=LABEL_FONT, size=max(9, size - 3))
        self.kbd_font = tkfont.Font(root, family=mono, size=max(8, size - 4))

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
            self.cfg["translator_x"], self.cfg["translator_y"] = self.root.winfo_x(), self.root.winfo_y()
            self.save(self.cfg)
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
        if mode in LANGUAGE_MODES and mode != self.cfg["translator_languages"]:
            self.cfg["translator_languages"] = mode
            self.save(self.cfg)
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
        entry["expires"] = time.time() + self.cfg["translator_line_seconds"]
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
        return items[-self.cfg["translator_max_lines"]:]

    def redraw(self):
        c = self.canvas
        c.delete("all")
        top_limit = 0
        if self.unlocked:
            top_limit = self._draw_unlocked()
        y = c.winfo_height() - 5
        for i, e in reversed(self.visible()):
            top = self._draw_line(i, e, y)
            if top < top_limit:
                c.delete(f"e{i}")
                break
            y = top - 4

    def _draw_unlocked(self):
        """The unlocked window: an outline with accent corners, the help line (or what just
        happened) and the two buttons. Returns where the lines may start."""
        c = self.canvas
        w, h = self.cfg["translator_width"], c.winfo_height()
        c.create_rectangle(0, 0, w - 1, h - 1, outline=EDGE)
        for x, y, dx, dy in ((0, 0, 1, 1), (w - 1, h - 1, -1, -1)):
            c.create_line(x, y + dy * BRACKET, x, y, x + dx * BRACKET, y, fill=ACCENT)
        mid = 8 + self.small_font.metrics("linespace") // 2
        # The two buttons on the right, side by side in one outline; the chosen one lit up.
        x = w - 8
        for mode in reversed(LANGUAGE_MODES):
            on = self.cfg["translator_languages"] == mode
            label = c.create_text(x - 10, mid, text=spaced(LANGUAGE_MODES[mode]), anchor="e", font=self.small_font,
                                  fill=ON_ACCENT if on else NAME_FG, tags=(f"mode_{mode}",))
            x0 = c.bbox(label)[0] - 10
            box = c.create_rectangle(x0, mid - 11, x, mid + 11, fill=ACCENT if on else UNLOCKED_BG,
                                     outline=EDGE, tags=(f"mode_{mode}",))
            c.tag_lower(box, label)
            x = x0
        left_of_buttons = x - 10
        if self.status:
            c.create_text(10, mid, text=spaced(self.status), anchor="w", font=self.small_font, fill=ACCENT)
        else:
            key = c.create_text(14, mid, text=self.cfg["translator_toggle_key"], anchor="w", font=self.kbd_font, fill=LINE_TEXT)
            x0, y0, x1, y1 = c.bbox(key)
            c.tag_lower(c.create_rectangle(10, y0 - 1, x1 + 4, y1 + 2, fill="#10151c", outline=EDGE), key)
            hint = c.create_text(x1 + 12, mid, text=spaced("lock · drag: move · click: copy · right-click: original"),
                                 anchor="w", font=self.small_font, fill=HINT_FG)
            for shorter in ("LOCK · DRAG: MOVE · CLICK: COPY · RIGHT-CLICK: ORIGINAL",  # a narrow overlay
                            spaced("lock · drag: move · click: copy"), "LOCK · DRAG: MOVE · CLICK: COPY"):
                if c.bbox(hint)[2] <= left_of_buttons:
                    break
                c.itemconfigure(hint, text=shorter)
        return mid + 11 + 8

    def _draw_line(self, i, e, bottom):
        """One translated line ending at bottom: a dark box with an accent bar on the left, the
        language as a small tag, who said it and the translation (wrapping under itself).
        Everything is tagged e<i>, so a click anywhere on it copies it. Returns its top."""
        c = self.canvas
        tag = f"e{i}"
        pad, x = 5, 13
        mid = pad + self.font.metrics("linespace") // 2
        item = c.create_text(x + 5, mid, text=e["lang"].upper(), anchor="w", font=self.tag_font,
                             fill=ON_ACCENT, tags=(tag,))
        x0, y0, x1, y1 = c.bbox(item)
        c.tag_lower(c.create_rectangle(x, y0 - 1, x1 + 5, y1 + 1, fill=ACCENT, outline="", tags=(tag,)), item)
        x = x1 + 13
        if e["team"]:
            item = c.create_text(x + 5, mid, text="TEAM", anchor="w", font=self.tag_font, fill=TEAM_FG, tags=(tag,))
            x0, y0, x1, y1 = c.bbox(item)
            c.create_rectangle(x, y0 - 1, x1 + 5, y1 + 1, outline=TEAM_FG, tags=(tag,))
            x = x1 + 13
        item = c.create_text(x, pad, text=e["name"], anchor="nw", font=self.name_font,
                             fill=TEAM_FG if e["team"] else NAME_FG, tags=(tag,))
        x = c.bbox(item)[2] + 8
        wrap = max(self.cfg["translator_width"] - 15 - x, 150)
        item = c.create_text(x, pad, text=e["text"], anchor="nw", width=wrap, font=self.font,
                             fill=LINE_TEXT, tags=(tag,))
        _, _, right, low = c.bbox(tag)
        height = low + pad
        box = c.create_rectangle(5, 0, min(right + 10, self.cfg["translator_width"] - 1), height, fill=LINE_BG, outline="",
                                 tags=(tag,))
        c.create_rectangle(5, 0, 7, height, fill=ACCENT, outline="", tags=(tag,))
        c.tag_lower(box)
        c.move(tag, 0, bottom - height)
        return bottom - height

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


def start_translator(cfg, master, chat_lines, save=None):
    """Starts translating the chat lines the toolbox puts in chat_lines, in an overlay living in
    master (the toolbox's Tk root). cfg: the toolbox's settings; save(cfg) saves them. Returns
    the overlay and its queues."""
    vk = key_to_vk(cfg["translator_toggle_key"])
    results, toggles = queue.Queue(), queue.Queue()
    threading.Thread(target=worker, args=(cfg, chat_lines, results), daemon=True).start()
    threading.Thread(target=hotkey_listener, args=(vk, lambda: toggles.put(1), "the translator's key"),
                     daemon=True).start()
    print(f"Translator running. Press {cfg['translator_toggle_key']} to unlock/lock the translation overlay.")
    overlay = Overlay(cfg, master, save)
    overlay.start(results, toggles)
    return overlay, results, toggles
