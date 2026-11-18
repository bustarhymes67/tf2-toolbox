"""The scanner's window drawn as a web page (web/index.html) in a WebView2 window (pywebview),
instead of with Tkinter. The scanner itself does not change: App still runs on its own Tk thread
(Tk also draws the mini HUD, the alerts and the translation overlay), this module only

- runs the web window on the main thread (pywebview needs it) and App on a second thread,
- sends App's state to the page as JSON whenever it changed (App.web_push -> render() in the page),
- carries clicks on the page back to App as named actions (Api.act -> App.web_actions), which
  App runs on its own thread, so nothing from here touches Tk directly.

Without pywebview the toolbox can't start: '1 - Install.bat' installs it."""

import ctypes
import json
import os
import queue
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "web", "index.html")

GWL_EXSTYLE, WS_EX_NOACTIVATE = -20, 0x08000000


def available():
    """True when pywebview (and the Windows WebView2 it uses) can be imported."""
    try:
        import webview  # noqa: F401
        return True
    except ImportError:
        return False


class Api:
    """What the page can call: window.pywebview.api.act(name, args)."""

    def __init__(self, actions):
        self._actions = actions

    def act(self, name, args=None):
        self._actions.put((str(name), list(args or [])))
        return True


class WebWindow:
    """The web window, and the few things App asks of it."""

    def __init__(self, cfg, actions):
        import webview
        self.webview = webview
        self.cfg = cfg
        self.ready = threading.Event()
        self.last = None        # the last JSON sent, so an unchanged state isn't sent again
        self.hwnd = None
        self.keyboard_from = None  # while typing in the page: the window that had the keyboard (TF2)
        w, h = cfg.get("web_width") or 1400, cfg.get("web_height") or 780
        self.window = webview.create_window(
            "TF2 Toolbox", url=PAGE, js_api=Api(actions), frameless=True, easy_drag=False, on_top=True,
            width=w, height=h, x=cfg["x"], y=cfg["y"], background_color="#07090c", resizable=True,
            min_size=(980, 560), hidden=True)  # hidden until F9, like the scanner itself (else it shows the page's example text)
        self.window.events.loaded += self._loaded

    def _loaded(self):
        try:
            self.hwnd = self.window.native.Handle.ToInt64()
        except Exception:
            self.hwnd = None
        self.no_activate(True)
        self.last = None  # a (re)loaded page has nothing yet: send everything
        self.ready.set()

    # --- the page -------------------------------------------------------------------------

    def push(self, state):
        """Sends the state to the page when it changed. Safe from App's thread."""
        if not self.ready.is_set():
            return
        text = json.dumps(state, ensure_ascii=False, separators=(",", ":"), default=str)
        if text == self.last:
            return
        self.last = text
        try:
            self.window.evaluate_js(f"window.LS && LS.render({text})")
        except Exception as e:  # the window is closing
            print("web push failed:", e, flush=True)

    # --- the window -----------------------------------------------------------------------

    def set_visible(self, visible):
        if visible:
            self.window.show()
            self.no_activate(True)
        else:
            self.window.hide()

    def toggle_maximized(self):
        if getattr(self, "maximized", False):
            self.window.restore()
        else:
            self.window.maximize()
        self.maximized = not getattr(self, "maximized", False)

    def minimize(self):
        self.window.minimize()

    def where(self):
        """(x, y, width, height) for the settings."""
        return self.window.x, self.window.y, self.window.width, self.window.height

    def no_activate(self, on):
        """With WS_EX_NOACTIVATE, clicking the window never takes the keyboard from the game
        (like the Tk window). Turned off while you type in the page's search box."""
        if not self.hwnd:
            return
        u = ctypes.windll.user32
        u.GetWindowLongPtrW.restype = ctypes.c_longlong
        u.SetWindowLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
        style = u.GetWindowLongPtrW(ctypes.c_void_p(self.hwnd), GWL_EXSTYLE)
        style = style | WS_EX_NOACTIVATE if on else style & ~WS_EX_NOACTIVATE
        u.SetWindowLongPtrW(ctypes.c_void_p(self.hwnd), GWL_EXSTYLE, style)

    def take_keyboard(self, take):
        """The page's search box got or lost focus: the window takes the keyboard while you
        type, then gives it back to the window that had it (TF2)."""
        if not self.hwnd:
            return
        u = ctypes.windll.user32
        if take:
            self.keyboard_from = u.GetForegroundWindow()
            self.no_activate(False)
            u.SetForegroundWindow(ctypes.c_void_p(self.hwnd))
        else:
            self.no_activate(True)
            if self.keyboard_from:
                u.SetForegroundWindow(ctypes.c_void_p(self.keyboard_from))
            self.keyboard_from = None

    def close(self):
        try:
            self.window.destroy()
        except Exception:
            pass


def run(cfg, start_app):
    """Runs the web window on this (the main) thread and start_app(web, actions) on a second
    thread, where it builds App and runs its Tk loop. Returns when the window is closed."""
    import webview
    actions = queue.Queue()
    web = WebWindow(cfg, actions)

    def app_thread():
        try:
            start_app(web, actions)
        finally:
            web.close()

    webview.start(lambda: threading.Thread(target=app_thread, daemon=True).start(), gui="edgechromium",
                  private_mode=True, debug=bool(os.environ.get("LOBBY_SCANNER_DEVTOOLS")))
