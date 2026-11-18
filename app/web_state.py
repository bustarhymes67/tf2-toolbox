"""What the web window (web_ui.py, web/index.html) shows, as JSON-able dicts built from App, and
the actions the page may ask App to do. One module per group of pages fills its part:

    web_players.py           the Players page and the selected player's panel
    web_cheat_duels.py       the Cheat check and Duels pages
    web_chat_status_help.py  the Chat, Status and Help pages

Each registers its state with @page("name") (a function app -> dict, under state["pages"][name])
and its clicks with @action("name") (a function (app, *args), run on App's thread). Only
registered actions can be run from the page."""

import time

STATE = {}    # page name -> function(app) -> dict
ACTIONS = {}  # action name -> function(app, *args)


def page(name):
    def register(fn):
        STATE[name] = fn
        return fn
    return register


def action(name):
    def register(fn):
        ACTIONS[name] = fn
        return fn
    return register


def light(state):
    """A connection's state as the page's dot: "ok", "warn", "off" or "bad", plus its short text."""
    from screens import status_colour
    from settings import BAD, FAINT, GOOD, WAITING
    colour = status_colour(state)
    return {GOOD: "ok", WAITING: "warn", FAINT: "off", BAD: "bad"}.get(colour, "bad")


def header(app):
    """The title bar and the sidebar: player count, map, server, the four lights, feedback, the open page,
    the sidebar's badges and its footer."""
    flagged = sum(1 for p in app.players.values() if p.sid != app.me
                  and max((s for s, _ in app.flags.get(p.sid, [])), default=-1) >= 1)
    states = {"TF2": app.rcon_state, "Steam": app.api_state, "History": app.sh_state, "Lists": app.lists_state}
    me = app.players.get(app.me)
    server, slots = app.server_text()
    return {
        "players": len(app.players),
        "map": app.map_name or "",
        "server": server,          # "Casual · Frankfurt", or a community server's (cut) name
        "slots": slots,            # "10/24" from status, "" when not known
        "hostname": app.hostname,  # the server's full name, for the sidebar's footer
        "lights": [{"name": n, "state": s, "dot": light(s)} for n, s in states.items()],
        "feedback": app.feedback,
        "page": app.cfg["page"],
        "toggle_key": app.cfg["toggle_key"],
        "badges": {"Players": flagged or None,
                   "Cheat check": len({sid for sid in getattr(app, "demo_alerted", {})}) or None,
                   "Duels": len(app.duel_entries()) or None},
        "foot": {"session": time.strftime("%H:%M:%S", time.gmtime(time.time() - app.started_at)),
                 "map": app.map_name or "-", "server": app.hostname or "-", "ping": f"{me.ping} ms" if me and me.ping else "-"},
    }


def build(app):
    """Everything the page shows now."""
    state = {"header": header(app), "pages": {}}
    for name, fn in STATE.items():
        try:
            state["pages"][name] = fn(app)
        except Exception as e:  # one broken page must not blank the others
            state["pages"][name] = {"error": repr(e)}
            print(f"web state for {name} failed: {e!r}", flush=True)
    return state


def run_action(app, name, args):
    """A click on the page, on App's thread."""
    fn = ACTIONS.get(name)
    if not fn:
        print(f"web: no action called {name!r}", flush=True)
        return
    try:
        fn(app, *args)
    except Exception as e:
        print(f"web action {name}{tuple(args)} failed: {e!r}", flush=True)
    app.dirty = True


# --- the window's own actions ----------------------------------------------------------------

@action("show_page")
def _show_page(app, name):
    app.show_page(name)


@action("hide")
def _hide(app):
    app.set_visible(False)


@action("minimize")
def _minimize(app):
    app.web.minimize()


@action("maximize")
def _maximize(app):
    app.web.toggle_maximized()


@action("quit")
def _quit(app):
    app.quit()


@action("keyboard")
def _keyboard(app, take):
    """The page's text box got (True) or lost (False) focus."""
    app.web.take_keyboard(bool(take))


import web_players  # noqa: E402,F401  (they register their pages and actions)
import web_cheat_duels  # noqa: E402,F401
import web_chat_status_help  # noqa: E402,F401
