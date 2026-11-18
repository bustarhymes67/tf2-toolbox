"""Web window state and actions for the Chat, Status and Help pages (see web_state.py).

Everything shown comes from App and the same tables the Tk pages use (screens.py): the setting
texts, CHAT_EXAMPLES for the hover preview, feature_health() and the help tables. The clicks call
App's own toggle methods, which also keep the (hidden) Tk widgets up to date."""
from chat import COUNTRY_NAMES
from info_commands import INFO_COMMANDS
from screens import (CHAT_EXAMPLES, DUEL_COMMANDS, HEAVY_COMMANDS, PREVIEW_DELAY, PREVIEW_STEP,
                     SPEAK_COMMANDS)
from web_state import action, light, page

# The Chat page's switches: (key, title, what it does, App method, setting, CHAT_EXAMPLES key).
# The texts are the Tk page's (screens._build_chat_page). The beef title is built from the setting.
CHAT_SETTINGS = (
    ("announcer", "Announcer: first blood, gardens, humiliations, rage-quits",
     "Calls these out in chat when they happen.", "toggle_announcer", "announcer", "announcer"),
    ("ez", '"ez" after your kills', 'Says "ez <name>" for every kill you make.', "toggle_ez_mode", "ez_mode", "ez"),
    ("translate", "Post translations in chat", "Says every translation for everyone (not your own lines).",
     "toggle_translate_to_chat", "translate_to_chat", "translate"),
    ("beef", None, "Announces each kill between these two countries, with the score.",
     "toggle_country_beef", "country_beef_auto", "beef"),
    ("idle", "Auto-reconnect when idle",
     "TF2 kicks you after 3 minutes idle. This types retry 10 seconds before, so you reconnect first.",
     "toggle_idle_rejoin", "idle_rejoin", "idle"),
)
CHAT_TOGGLES = {key: method for key, _, _, method, _, _ in CHAT_SETTINGS}
# The Status page's connection cards: what each one is for (the Tk page's words).
CONNECTIONS = (("TF2", "rcon_state", "RCON"), ("Steam", "api_state", "bans, hours, age"),
               ("History", "sh_state", "server bans"), ("Lists", "lists_state", "cheater lists"))
LAST_POSTS = 8  # lines of the scanner's own chat shown on the Chat page


def beef_title(cfg):
    a, b = cfg["country_beef"]
    return f"Country kill score: {COUNTRY_NAMES.get(a, a)} vs {COUNTRY_NAMES.get(b, b)}"


def command(usage):
    """"!check <name>" -> ["!check", "<name>"]: what you type as is, then the parts you fill in."""
    cut = usage.find("<")
    return [usage, ""] if cut < 0 else [usage[:cut].rstrip(), usage[cut:]]


@page("Chat")
def chat_state(app):
    cfg = app.cfg
    settings = [{"key": key, "title": title or beef_title(cfg), "about": about, "on": bool(cfg[setting]),
                 "example": example} for key, title, about, _, setting, example in CHAT_SETTINGS]
    muted = len(cfg["speak_muted"])
    commands = [{"id": "who", "usage": ["!who", "<name>"], "on": bool(cfg["who_command"])},
                {"id": "speak", "usage": ["!speak", ""], "on": bool(cfg["translate_command"])}]
    commands += [{"id": f"info:{name}", "usage": command(usage), "on": bool(cfg["info_commands"].get(name, True))}
                 for name, (usage, _) in INFO_COMMANDS.items()]
    return {
        "settings": settings,
        "muted": muted,
        "commands": commands,
        "posts": list(app.chat_sent)[-LAST_POSTS:],
        "examples": {key: [list(line) for line in lines] for key, lines in CHAT_EXAMPLES.items()},
        "preview_delay": PREVIEW_DELAY,
        "preview_step": PREVIEW_STEP,
    }


@action("chat_toggle")
def _chat_toggle(app, key):
    """A switch on the Chat page."""
    getattr(app, CHAT_TOGGLES[key])()


@action("chat_command")
def _chat_command(app, which):
    """A pill on the Chat commands card: "who", "speak" or "info:<command>"."""
    if which == "who":
        app.toggle_who_command()
    elif which == "speak":
        app.toggle_translate_command()
    elif which.startswith("info:") and which[5:] in INFO_COMMANDS:
        app.toggle_info_command(which[5:])


@action("unmute_all_speak")
def _unmute_all_speak(app):
    app.unmute_all_speak()


@page("Status")
def status_state(app):
    health = [{"name": name, "level": level, "text": text} for name, level, text in app.feature_health()]
    return {
        "hud": bool(app.cfg["hud"]),
        "hud_moving": bool(app.hud.moving),
        "connections": [{"name": name, "state": getattr(app, attr), "dot": light(getattr(app, attr)), "about": about}
                        for name, attr, about in CONNECTIONS],
        "chat": {"sent": app.chat_sent_count, "refused": app.chat_refused_count},
        "health": health,
        "health_ok": sum(row["level"] == "ok" for row in health),
        "keys": [[app.cfg["toggle_key"], "Show / hide this window"], ["F8", "Move translations"]],
    }


@action("hud_toggle")
def _hud_toggle(app):
    app.toggle_hud()


@action("hud_move")
def _hud_move(app):
    app.toggle_hud_move()


@page("Help")
def help_state(app):
    rows = lambda pairs: [{"usage": command(usage), "about": about} for usage, about in pairs]
    info = [("!who <name>", "A player's summary and stats, in two messages.")] + list(INFO_COMMANDS.values())
    return {"cards": [
        {"id": "keys", "title": "Keys (work in the game)",
         "rows": rows(((app.cfg["toggle_key"], "Show or hide the scanner window."),
                       ("F8", "Unlock the translations to move them with the mouse. F8 again locks them."))),
         "note": ""},
        {"id": "info", "title": "Information", "rows": rows(info),
         "note": "Switch each one off or on on the Chat page. Part of a name is enough: !who iva finds Ivan."},
        {"id": "speak", "title": "Translate", "rows": rows(SPEAK_COMMANDS),
         "note": "Switch !speak off or on on the Chat page. "
                 "Mute one player's !speak in their panel (click them on the Players page)."},
        {"id": "heavy", "title": "HoovyGPT", "rows": rows(HEAVY_COMMANDS),
         "note": "Switch it on with HoovyGPT + Duels on the Duels page."},
        {"id": "duels", "title": "Duels", "rows": rows(DUEL_COMMANDS), "note": "Duels work while HoovyGPT + Duels is on."},
    ]}
