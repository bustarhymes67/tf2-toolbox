"""HoovyGPT, the AI chat bot. Asking Gemini and Groq (first model, then backups), counting the free
answers and tokens per model, and turning chat lines into questions and answers into chat lines.
Its personality is in hoovygpt_prompt.txt. AIMixin is the part of the App that does this."""

import datetime
import json
import math
import os
import queue
import re
import secrets
import threading
import time
import urllib.request
import zoneinfo
from tf2_translator import CYRILLIC_RE

from settings import AI_LOG_PATH, HERE, load_secrets, save_config
from chat import AI_REPLY_MAX_AGE, CHAT_LIMIT, console_safe, say_name, split_chat

# Asked in order, smartest first: when one fails or is slow, the next is asked too.
# Gemini's newest Flash models lead (Pro has no free quota). They're often overloaded
# ("high demand", 2026-10-27/28) and Flash allows only 20 free answers a day, so most
# days the answer comes from further down. Measured on 2026-10-27: 3.5 Flash-Lite
# answered in under 1 s, 3.6 Flash in 5-9 s; on 2026-10-28 Flash-Lite took 16-24 s.
# Groq's GPT-OSS 120B answered in 0.3-0.5 s that day; Qwen was faster still but got TF2
# facts wrong ("Disc with AWP"), so it comes after. Every Gemini model is tried before
# Groq (asked for on 2026-10-29); 3.1 Flash-Lite answered in 3 s that day.
AI_MODELS = (("gemini", "gemini-3.8-flash"), ("gemini", "gemini-3.7-flash"),
             ("gemini", "gemini-3.6-flash"), ("gemini", "gemini-3.5-flash"),
             ("gemini", "gemini-3.5-flash-lite"), ("gemini", "gemini-3.1-flash-lite"),
             ("groq", "openai/gpt-oss-120b"), ("groq", "qwen/qwen3.8-27b"))  # Groq only once Gemini's out
# How fast each answers, for the Model menu: measured one by one on 2026-10-30 (3.5 Flash
# 3.8 s, 3.5 Flash-Lite 0.5 s, 3.1 Flash-Lite 3.5 s, GPT-OSS 0.5 s, Qwen 0.2 s) and earlier
# for the Flash models that were out of free answers that day (3.6: 5-9 s, 3.7/3.8: often
# "high demand").
AI_MODEL_SPEED = {"gemini-3.8-flash": "slow, often busy", "gemini-3.7-flash": "slow, often busy",
                  "gemini-3.6-flash": "slow, 5-9 s", "gemini-3.5-flash": "medium, ~4 s",
                  "gemini-3.5-flash-lite": "fast, ~1 s", "gemini-3.1-flash-lite": "medium, ~3 s",
                  "openai/gpt-oss-120b": "fastest, ~0.5 s", "qwen/qwen3.8-27b": "fastest, ~0.2 s, gets TF2 facts wrong"}
# Per Groq model: how much it thinks before answering, kept low for speed.
GROQ_MODELS = {"openai/gpt-oss-120b": {"reasoning_effort": "low", "include_reasoning": False},
               "qwen/qwen3.8-27b": {"reasoning_effort": "none"}}
GROQ_API = "https://api.groq.com/openai/v1/"
AI_TIMEOUT = 20  # seconds per question: a late answer is useless in chat
AI_BACKUP_AFTER = 4  # seconds without an answer before the next model is asked as well
AI_MAX_REPLY = 160  # characters; it's asked for under 100, so longer means something went wrong
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/"
AI_MUTED = "Heavy goes quiet now. Type !goodbot to wake Heavy"    # after anyone's "!badbot"
AI_UNMUTED = "Heavy is back! Type !badbot to make Heavy quiet"     # after anyone's "!goodbot"
AI_PREFIX = "HoovyGPT: "  # starts every other message the AI posts, so nobody takes it for you
# Tuned over 7 test rounds on 14 chat situations (2026-10-31): deadpan, twist at the end.
# Heavy's personality lives in hoovygpt_prompt.txt: the instructions, a line "=====", then a
# short reminder sent along with every question, as the model drifts from the instructions alone.
# Edit it there and restart the scanner.
with open(os.path.join(HERE, "hoovygpt_prompt.txt"), encoding="utf-8") as _prompt:
    AI_SYSTEM, AI_REMINDER = _prompt.read().rstrip("\n").split("\n=====\n")
# The Lock button keeps HoovyGPT on or muted: other players' commands then get one of these.
AI_COMMANDS = ("!badbot", "!goodbot")
AI_LOCK_REFUSALS = (
    "Nyet. Heavy does not take orders from tiny baby man.",
    "Heavy is locked. Only {owner} has key. You are not {owner}.",
    "You cannot mute Heavy. Heavy is too big to mute.",
    "Heavy will listen when you get more than three kills.",
    "Ha! Tiny command for tiny baby. Heavy has no off switch.",
    "Is cute that you think you are in charge.",
    "Heavy was quiet once. Was terrible. Never again.",
    "You want to change Heavy? Go cry to doktor.",
)
AI_LOCK_ASLEEP = (  # locked muted, and someone tries to wake it
    "Heavy is sleeping. Do not wake Heavy, or Heavy wakes YOU.",
    "Shhh. Heavy is napping. Come back never.",
)
AI_LOCKED_MUTED = "Heavy goes to sleep now. Nobody wakes Heavy"  # the Lock button set to muted
AI_LOCK_REFUSAL_GAP = 15  # seconds: a room spamming commands gets one refusal, not one each
# HoovyGPT follows the chat: every question goes with the chat lines before it (anyone's,
# yours and its own), so it knows who said what. Before this it only saw its own questions
# and answers, as if it talked to everyone separately (2026-10-31).
AI_CHAT_LOG = 50         # chat lines kept
AI_LOG_MAX_BYTES = 300_000  # ai_log.txt is cut back to its last AI_LOG_KEEP_LINES lines past this size
AI_LOG_KEEP_LINES = 2000
AI_CHAT_LOG_AGE = 1200   # seconds: older lines are left out
# Of HoovyGPT's own lines, this many are sent back. With all of them, one way of joking fed
# on itself: 45% of the replies ended on a question early in a match, 92% later (2026-11-03).
AI_OWN_LINES = 2
# Sent along now and then: told in the instructions to do these "now and then", it did neither
# in 18 replies (2026-11-02), as each reply is its own request.
AI_ASK_BACK = "(In this reply, ask them a dumb, sincere question back, after your joke.)"
AI_STORY = "(In this reply, tell a tiny tragic story about something small from their message, with total seriousness.)"
AI_NO_QUESTION = "(No question in this reply: end on a statement.)"
AI_NO_SCORES = "(No scores are known for this message, so give no kill or death numbers.)"
# What looks like asking for a score. Sending the score with every message made 54% of the
# replies quote one nobody asked about (2026-11-03). In other languages it's the note above.
AI_SCORE_WORDS = re.compile(r"\bkills?\b|killed|\bdeaths?\b|\bdied\b|\bscore|\bk/?d\b|\bfrags?\b|how many|streak"
                            r"|hoeveel|сколько|убил|убийств|смерт|умер|сч[её]т|фраг", re.I)
# What the map's name starts with, so Heavy doesn't talk about a cart on 2Fort. Saying "no cart"
# in here got him joking about there being no cart (2026-11-02).
MAP_MODES = {
    "ctf": "capture the flag: both teams steal the other's intelligence",
    "pl": "payload: BLU pushes the cart, RED stops it",
    "plr": "payload race: both teams push a cart",
    "cp": "control points",
    "koth": "king of the hill: both teams hold one control point",
    "arena": "arena: one life each round",
    "pd": "player destruction: collect what dead players drop and deliver it",
    "sd": "special delivery: carry the Australium to the rocket",
    "tc": "territorial control",
    "rd": "robot destruction",
    "mvm": "Mann vs. Machine: all players against robots",
    "pass": "PASS Time: score with the ball",
}
# A reply cut off for one of these reasons is never posted.
GEMINI_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION", "OTHER"}


AI_QUOTA_PATH = os.path.join(HERE, "ai_quota.json")
# Free answers a day per Gemini model, as its 429 errors gave them (2026-10-30/31); a model
# not in here gets its limit the first time it runs out. Gemini says nothing about what's
# left, so the scanner counts its own answers (your key used anywhere else isn't counted).
# Free tier limits from AI Studio's rate limit page (aistudio.google.com/rate-limit, 2026-11-08):
# answers a day, and requests and input tokens a minute. Google sends none of these with an answer.
GEMINI_DAILY_LIMITS = {"gemini-3.5-flash-lite": 500, "gemini-3.1-flash-lite": 500,
                       "gemini-3.6-flash": 20, "gemini-3.8-flash": 20}
GEMINI_MINUTE_LIMITS = {"gemini-3.5-flash-lite": (15, 250_000), "gemini-3.1-flash-lite": (15, 250_000),
                        "gemini-3.6-flash": (5, 250_000), "gemini-3.8-flash": (5, 250_000)}


class AIQuota:
    """Free answers left today per model, for the Model button. Gemini: counted here, and
    its days end at midnight Pacific time (ai.google.dev/gemini-api/docs/rate-limits).
    Groq: what it says itself in x-ratelimit-remaining-requests (per day,
    console.groq.com/docs/rate-limits). Tokens used come with every answer, from both.
    Tokens left only come from Groq, per minute: Gemini sends no limit headers at all."""

    def __init__(self, path):
        """Loads today's counts from ai_quota.json; they start over on a new Pacific day."""
        self.path, self.lock = path, threading.Lock()
        try:
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
        except (OSError, ValueError):
            saved = {}
        self.day = saved.get("day", "")
        self.used = saved.get("used", {})      # Gemini model -> answers today
        self.limits = dict(GEMINI_DAILY_LIMITS, **saved.get("limits", {}))
        self.out = set(saved.get("out", []))   # Gemini models that said they're out today
        self.groq = saved.get("groq", {})      # model -> [left, limit, until (epoch)]
        self.tokens = saved.get("tokens", {})  # model -> tokens used today
        self.last_tokens = {}                  # model -> tokens its latest answer used
        self.groq_tokens = {}                  # model -> [left, limit, reported at, until]: per minute
        self.recent = {}                       # Gemini model -> [(asked at, tokens)] of the last minute
        self.new_day()

    @staticmethod
    def pacific_day():
        return datetime.datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles")).date().isoformat()

    def new_day(self):
        if self.day != (today := self.pacific_day()):
            self.day, self.used, self.out, self.tokens = today, {}, set(), {}

    def save(self):
        """Writes the counts to ai_quota.json, so they survive a restart."""
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"day": self.day, "used": self.used, "limits": self.limits,
                           "out": sorted(self.out), "groq": self.groq, "tokens": self.tokens}, f)
        except OSError:
            pass

    def gemini_answered(self, model, tokens):
        """Counts one Gemini answer and the tokens it used."""
        with self.lock:
            self.new_day()
            self.used[model] = self.used.get(model, 0) + 1
            self.out.discard(model)  # it answered, so it isn't out after all
            self.count_tokens(model, tokens)
            self.recent.setdefault(model, []).append((time.time(), tokens))
            self.save()

    def groq_answered(self, model, tokens):
        with self.lock:
            self.new_day()
            self.count_tokens(model, tokens)
            self.save()

    def count_tokens(self, model, tokens):
        self.tokens[model] = self.tokens.get(model, 0) + tokens
        self.last_tokens[model] = tokens

    def gemini_out(self, model, limit):
        """A 429 for the day: none left until midnight Pacific."""
        with self.lock:
            self.new_day()
            self.out.add(model)
            if limit:
                self.limits[model] = limit
            self.save()

    def groq_headers(self, model, headers):
        """Keeps what Groq says is left, from the x-ratelimit headers of its response."""
        left, limit = headers.get("x-ratelimit-remaining-requests"), headers.get("x-ratelimit-limit-requests")
        tokens, token_limit = headers.get("x-ratelimit-remaining-tokens"), headers.get("x-ratelimit-limit-tokens")
        if tokens and tokens.isdigit() and token_limit and token_limit.isdigit():
            now = time.time()
            self.groq_tokens[model] = [int(tokens), int(token_limit), now,
                                       now + groq_seconds(headers.get("x-ratelimit-reset-tokens", ""))]
        if left is None or not left.isdigit():
            return
        with self.lock:
            self.groq[model] = [int(left), int(limit) if limit and limit.isdigit() else None,
                                time.time() + groq_seconds(headers.get("x-ratelimit-reset-requests", ""))]
            self.save()

    def left(self, model):
        """Answers left today, or None when it isn't known yet."""
        with self.lock:
            self.new_day()
            if model in self.groq:
                left, limit, until = self.groq[model]
                return left if time.time() < until or limit is None else limit
            if model in self.out:
                return 0
            if model in self.limits:
                return max(0, self.limits[model] - self.used.get(model, 0))
            return None

    def daily_limit(self, model):
        """Free answers a day, or None when it isn't known yet."""
        return self.groq[model][1] if model in self.groq else self.limits.get(model)

    def gemini_minute_left(self, model):
        """(requests, tokens) a Gemini model has left this minute, counted here from its answers of
        the last 60 seconds; None for a model whose limits aren't known."""
        if model not in GEMINI_MINUTE_LIMITS:
            return None
        rpm, tpm = GEMINI_MINUTE_LIMITS[model]
        with self.lock:
            cutoff = time.time() - 60
            recent = self.recent[model] = [r for r in self.recent.get(model, []) if r[0] > cutoff]
        return max(0, rpm - len(recent)), max(0, tpm - sum(tokens for _, tokens in recent))

    def minute_full(self, model):
        """True when a Gemini model has used up its requests for this minute."""
        left = self.gemini_minute_left(model)
        return left is not None and left[0] == 0

    def tokens_left(self, model):
        """Groq's tokens left this minute, or None for a model that doesn't report them. They
        come back steadily until its reset time, so this rises between its reports."""
        report = self.groq_tokens.get(model)
        if not report:
            return None
        left, limit, at, until = report
        now = time.time()
        return limit if now >= until else int(left + (limit - left) * (now - at) / (until - at))

    def label(self, model):
        """The free answers left as short text for the Model menu, like "397 left"."""
        left = self.left(model)
        if left == 0:
            return f"none left, back in {self.hours_left(model)}h"
        if left is not None:
            return f"{left} left"
        return f"{self.used.get(model, 0)} used today"

    def hours_left(self, model):
        """Hours (rounded up) until the model's day starts over."""
        if model in self.groq:
            seconds = self.groq[model][2] - time.time()
        else:
            now = datetime.datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles"))
            midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            seconds = (midnight - now).total_seconds()
        return max(1, math.ceil(seconds / 3600))


def groq_seconds(text):
    """Groq's reset times, like "2m59.56s" or "7.66s" or "1h2m", in seconds."""
    total = 0.0
    for amount, unit in re.findall(r"([\d.]+)(ms|h|m|s)", text):
        total += float(amount) * {"ms": 0.001, "h": 3600, "m": 60, "s": 1}[unit]
    return total


ai_quota = AIQuota(AI_QUOTA_PATH)


class AIError(Exception):
    """A failed Groq or Gemini call, worded for the status bar. busy=True: that model
    is overloaded or too slow right now, so another model may still answer."""
    def __init__(self, message, busy=False):
        super().__init__(message)
        self.busy = busy


def gemini_turn(role, text):
    return {"role": role, "parts": [{"text": text}]}


def ai_question_turn(question):
    """The question as sent, with a reminder of its language (not kept in the
    history): otherwise Gemini keeps answering in whatever language came before."""
    turn = gemini_turn("user", question)
    if CYRILLIC_RE.search(question.split(": ", 1)[-1]):
        hint = "(This message is in Russian or another Cyrillic-script language: reply in that same language.)"
    else:
        hint = "(This message isn't in Russian: reply in its own language, usually English.)"
    turn["parts"].append({"text": hint})
    return turn


def gemini_call(key, path, body=None):
    """GET (no body) or POST to the Gemini REST API. The key goes in the
    x-goog-api-key header rather than the URL, so it never lands in a log."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(GEMINI_API + path, data=data,
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            error = json.loads(e.read().decode("utf-8"))["error"]
            message = error["message"]
        except (ValueError, KeyError, TypeError):
            error, message = {}, e.reason
        if e.code == 429:  # free-tier limits are per model, so another model may still answer
            for detail in error.get("details") or []:
                for v in detail.get("violations") or []:
                    if "PerDay" in v.get("quotaId", ""):  # not the per-minute one
                        limit = str(v.get("quotaValue", ""))
                        ai_quota.gemini_out(path.removeprefix("models/").split(":")[0],
                                            int(limit) if limit.isdigit() else None)
            raise AIError("HoovyGPT: free limit reached, try again in a minute", busy=True) from None
        if e.code in (400, 401, 403) and "API key" in message:
            raise AIError("HoovyGPT: your Gemini API key was rejected") from None
        if e.code >= 500:
            raise AIError("HoovyGPT: Gemini is overloaded right now", busy=True) from None
        raise AIError(f"HoovyGPT: API error {e.code}: {message}") from None
    except TimeoutError:
        raise AIError("HoovyGPT: Gemini is too slow right now", busy=True) from None
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):  # a timeout while connecting
            raise AIError("HoovyGPT: Gemini is too slow right now", busy=True) from None
        raise AIError("HoovyGPT: couldn't reach the Gemini API") from None


def gemini_reply(key, model, system, contents):
    """One model's reply text: None when Gemini blocked the question or the answer,
    "" when it gave nothing usable (now and then a reply is empty for no reason it gives)."""
    data = gemini_call(key, f"models/{model}:generateContent", {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        # Flash models think by default and thoughts count toward this, so it's roomy.
        "generationConfig": {"maxOutputTokens": 2048, "thinkingConfig": {"thinkingLevel": "low"}},
    })
    ai_quota.gemini_answered(model, data.get("usageMetadata", {}).get("totalTokenCount", 0))
    if data.get("promptFeedback", {}).get("blockReason"):
        return None
    candidate = (data.get("candidates") or [{}])[0]
    if candidate.get("finishReason") in GEMINI_BLOCKED:
        return None
    parts = candidate.get("content", {}).get("parts") or []
    return usable_reply(" ".join(p.get("text", "") for p in parts if not p.get("thought")), contents)


def usable_reply(text, contents):
    """The model's text tidied for chat, or "" when it isn't an answer."""
    text = text.strip()
    # It sometimes copies the "name: message" format it was given; the name isn't wanted.
    asker = contents[-1]["parts"][0]["text"].split(": ", 1)[0]
    for name in (asker, AI_PREFIX.rstrip(": ")):
        if text.startswith(name + ":"):
            text = text[len(name) + 1:].strip()
    # A reply far past the asked-for length is Flash-Lite leaking its drafts
    # ("Idea 1: ... Idea 2: ..."), not an answer: the next model gets a go.
    if len(text) > AI_MAX_REPLY or text.count("\n") >= 2:
        return ""
    return text


def groq_call(key, path, body=None):
    """GET (no body) or POST to Groq's OpenAI-style API; errors as for gemini_call."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    # Groq sits behind Cloudflare, which turns away urllib's default User-Agent.
    req = urllib.request.Request(GROQ_API + path, data=data,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "tf2-toolbox"})
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
            if body and "model" in body:
                ai_quota.groq_headers(body["model"], resp.headers)
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read().decode("utf-8"))["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = e.reason
        if body and "model" in body:
            ai_quota.groq_headers(body["model"], e.headers)
        if e.code == 429:  # per minute and per day, per model
            raise AIError("HoovyGPT: free limit reached, try again in a minute", busy=True) from None
        if e.code == 401:
            raise AIError("HoovyGPT: your Groq API key was rejected") from None
        if e.code >= 500:
            raise AIError("HoovyGPT: Groq is overloaded right now", busy=True) from None
        raise AIError(f"HoovyGPT: Groq error {e.code}: {message}") from None
    except TimeoutError:
        raise AIError("HoovyGPT: Groq is too slow right now", busy=True) from None
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, "reason", None), TimeoutError):
            raise AIError("HoovyGPT: Groq is too slow right now", busy=True) from None
        raise AIError("HoovyGPT: couldn't reach the Groq API") from None


def groq_reply(key, model, system, contents):
    """Like gemini_reply, from Groq. The history is kept in Gemini's format, so it's converted."""
    messages = [{"role": "system", "content": system}]
    messages += [{"role": "assistant" if turn["role"] == "model" else "user",
                  "content": "\n".join(p["text"] for p in turn["parts"])} for turn in contents]
    data = groq_call(key, "chat/completions", dict(
        {"model": model, "messages": messages, "max_completion_tokens": 1024}, **GROQ_MODELS[model]))
    ai_quota.groq_answered(model, data.get("usage", {}).get("total_tokens", 0))
    choice = (data.get("choices") or [{}])[0]
    if choice.get("finish_reason") == "content_filter":
        return None
    return usable_reply(choice.get("message", {}).get("content") or "", contents)


def ai_answer(keys, system, contents, models=AI_MODELS):
    """The reply text, or None when the AI blocked the question or the answer.
    keys: {"groq": ..., "gemini": ...}; a provider without a key is skipped.
    The first model is asked; when it fails, says nothing usable or hasn't answered
    within AI_BACKUP_AFTER, the next is asked as well, and the first good answer wins."""
    results = queue.Queue()
    started, tried = time.time(), []  # tried: (model, what happened) for the log

    def ask(reply, key, model):
        try:
            results.put((model, reply(key, model, system, contents)))
        except AIError as e:
            results.put((model, e))

    deadline = time.time() + AI_TIMEOUT
    replies = {"groq": groq_reply, "gemini": gemini_reply}
    reserve = [(replies[provider], keys[provider], model) for provider, model in models if keys.get(provider)]
    pending, first_error = 0, None
    while reserve or pending:
        # Each time round is the start, a slow model or a failed one: time to bring in the next.
        if reserve:
            threading.Thread(target=ask, args=reserve.pop(0), daemon=True).start()
            pending += 1
        wait = deadline - time.time()
        if reserve:
            wait = min(wait, AI_BACKUP_AFTER)
        try:
            result = results.get(timeout=max(wait, 0))
        except queue.Empty:
            if reserve:
                continue
            break  # out of time
        pending -= 1
        model, result = result
        if isinstance(result, AIError):
            # Even a rejected key only rules out its own provider: the other may still answer.
            first_error = first_error or result  # the main model's problem is the one worth showing
            tried.append((model, str(result).removeprefix("HoovyGPT: ").split(",")[0]))
        elif result is None or result:
            log_ai(started, model, "blocked" if result is None else "answered", tried)
            return result
        else:
            tried.append((model, "unusable answer"))
    log_ai(started, None, "no answer", tried)
    if first_error:
        raise first_error
    if pending:
        raise AIError("HoovyGPT: the AI is too slow right now", busy=True)
    return None


def without_last_question(answer):
    """The answer without the question(s) at its end, if there's a statement before them."""
    statement = re.match(r"^(.*[.!])\s+[^.!]*\?$", answer.rstrip(), re.S)
    return statement[1] if statement else answer


def address_asker(answer, asker):
    """The answer with the asker's name in front, so it's clear who's answered in a busy chat,
    but only once: models also greet people themselves, often with part of the name ("Gaming
    man 92, ..." for "The pancake man 92"), or use the name later in the line."""
    name = re.findall(r"\w+", asker.lower())
    if not name:
        return f"{asker}, {answer}"

    def in_name_order(words, part):
        return any(words[i:i + len(part)] == part for i in range(len(words) - len(part) + 1))

    greeting = re.match(r"([^,:!?.]*)[,:!?.]\s*(.+)", answer, re.S)
    if greeting:
        said = re.findall(r"\w+", greeting[1].lower())
        if said and in_name_order(name, said) and max(name, key=len) in said:
            answer = greeting[2]
    if in_name_order(re.findall(r"\w+", answer.lower()), name):
        return answer
    return f"{asker}, {answer}"


def log_ai(started, model, outcome, tried):
    """One line in ai_log.txt per question: when, which model answered (or that
    none did) and how long it took, plus what the models before it said."""
    line = (f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started))} | {model or '-'} | {outcome} | "
            f"{time.time() - started:.1f}s")
    if tried:
        line += " | " + ", ".join(f"{m}: {why}" for m, why in tried)
    try:
        with open(AI_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if os.path.getsize(AI_LOG_PATH) > AI_LOG_MAX_BYTES:  # keep the newest lines only
            with open(AI_LOG_PATH, encoding="utf-8") as f:
                kept = f.readlines()[-AI_LOG_KEEP_LINES:]
            with open(AI_LOG_PATH, "w", encoding="utf-8") as f:
                f.writelines(kept)
    except OSError:
        pass


TOKEN_COLUMNS = ("MODEL", "ANSWERS LEFT", "TOKENS TODAY", "LAST ANSWER", "ASKS LEFT/MIN", "TOKENS LEFT/MIN")
TOKEN_NOTE = "> asked first. ~: counted by the toolbox, as Google doesn't report it. -: not known yet."


def token_rows(first):
    """Every model's free answers and tokens, one row per model under TOKEN_COLUMNS, each row
    starting with ">" for the model asked first (first), else "". For the table and the web page."""
    rows = []
    for provider, model in AI_MODELS:
        left, limit, tokens_left = ai_quota.left(model), ai_quota.daily_limit(model), ai_quota.tokens_left(model)
        answers = "?" if left is None else f"{left:,}/{limit:,}" if limit else f"{left:,}"
        if left == 0:
            answers += f", back in {ai_quota.hours_left(model)}h"
        asks, minute_tokens = "-", "-"
        if provider == "gemini" and (minute := ai_quota.gemini_minute_left(model)):
            rpm, tpm = GEMINI_MINUTE_LIMITS[model]
            asks, minute_tokens = f"~{minute[0]}/{rpm}", f"~{minute[1]:,}/{tpm:,}"
        elif tokens_left is not None:
            minute_tokens = f"{tokens_left:,}/{ai_quota.groq_tokens[model][1]:,}"
        rows.append((">" if model == first else "", model, answers, f"{ai_quota.tokens.get(model, 0):,}",
                     f"{ai_quota.last_tokens[model]:,}" if model in ai_quota.last_tokens else "-", asks, minute_tokens))
    return rows


def token_table(first):
    """Every model's free answers and tokens as text, in columns. first: the model asked first."""
    rows = [("",) + TOKEN_COLUMNS] + token_rows(first)
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows]
    return "\n".join(lines + [TOKEN_NOTE])


def model_choices():
    """The Model menu's choices, best first: (value for pick_model, label)."""
    return [("auto", "Auto (best available first)")] + [
        (model, f"{model}  ({provider.capitalize()}, {AI_MODEL_SPEED.get(model, '?')}, {ai_quota.label(model)})")
        for provider, model in AI_MODELS]


class AIMixin:
    # --- AI chat: answers chat through Google's Gemini, with Groq as the backup ------------

    def toggle_ai(self):
        """The HoovyGPT + Duels button: on or off at once, and it says nothing in chat. Duels work
        without an API key; Heavy only talks with one that works. Remembered for the next start."""
        self.ai_on = not self.ai_on
        if self.cfg["duels_on"] != self.ai_on:
            self.cfg["duels_on"] = self.ai_on
            save_config(self.cfg)
        if not self.ai_on:
            self.chat_duels = []  # duels go off with it
        else:
            self.ai_muted = False
            saved = load_secrets()
            for name in ("groq_api_key", "gemini_api_key"):  # pasted into the secrets file since the scanner started?
                self.cfg[name] = self.cfg[name] or saved.get(name, "")
            self.apply_ai_lock(announce=False)
            if self.heavy_can_talk():
                threading.Thread(target=self.check_ai_keys, args=(self.ai_keys(),), daemon=True).start()

    def ai_keys(self):
        return {"groq": self.cfg["groq_api_key"], "gemini": self.cfg["gemini_api_key"]}

    def heavy_can_talk(self):
        """False unless the heavy_talks setting is on and a key is set. Duels don't need this."""
        return bool(self.cfg["heavy_talks"] and any(self.ai_keys().values()))

    def check_ai_keys(self, keys):
        """Runs in a thread; reports back as an "ai_ready" event, with a rejected key blanked."""
        checks = {"groq": lambda key: groq_call(key, "models"),
                  "gemini": lambda key: gemini_call(key, f"models/{AI_MODELS[0][1]}")}
        errors = []
        for provider, key in keys.items():
            if key:
                try:
                    checks[provider](key)
                except AIError as e:
                    errors.append(str(e))
                    if not e.busy:  # a busy server says nothing about the key
                        keys[provider] = ""
        self.events.put(("ai_ready", keys, errors))

    def ai_ready(self, keys, errors):
        """The key check finished: a rejected key isn't used, so Heavy stays quiet without a good one."""
        for error in errors:
            print(error)
        for provider, key in keys.items():
            if not key:
                self.cfg[f"{provider}_api_key"] = ""  # read the file again next press, in case it's fixed

    def ai_models(self):
        """The models to try, in order: the one picked in the Model menu first, then
        the rest from the top as backups (so a model that's out of free answers or
        down never leaves HoovyGPT silent)."""
        picked = [m for m in AI_MODELS if m[1] == self.cfg["ai_model"]]
        order = picked + [m for m in AI_MODELS if m not in picked]
        # Ones out of free answers today last, then ones out of requests this minute: asking
        # them first only costs a backup's wait (and a 429 from Google).
        return tuple(sorted(order, key=lambda m: (ai_quota.left(m[1]) == 0, ai_quota.minute_full(m[1]))))

    def pick_model(self, model):
        self.cfg["ai_model"] = model
        save_config(self.cfg)
        self.notify(f"HoovyGPT now starts with {model}" if model != "auto" else "HoovyGPT picks the best available model")

    def model_shown(self):
        """(what the Model button names, the model whose free answers it shows): Auto and the model
        asked first, or the picked one, even when it's out and another stands in."""
        model, first = self.cfg["ai_model"], self.ai_models()[0][1]
        return (f"Auto: {first}", first) if model == "auto" else (model, model)

    def set_ai_muted(self, muted):
        if muted != self.ai_muted:
            self.ai_muted = muted
            self.ai_reply, self.ai_waiting = [], None  # muted means now, not after what's waiting
            self.say_as_ai(AI_MUTED if muted else AI_UNMUTED)

    def refuse_ai_command(self, command):
        """Someone else's !badbot/!goodbot while it's locked: a funny no from Heavy,
        unless it wouldn't change anything anyway."""
        lock = self.cfg["ai_lock"]
        if (lock == "muted" and command == "!badbot") or (lock != "muted" and command == "!goodbot"):
            return  # asked for what it already is
        if time.time() - self.ai_refused_at < AI_LOCK_REFUSAL_GAP:
            return
        self.ai_refused_at = time.time()
        me = self.players.get(self.me)
        lines = [l for l in (AI_LOCK_ASLEEP if lock == "muted" else AI_LOCK_REFUSALS) if l not in self.ai_refusals]
        line = secrets.choice(lines)
        self.ai_refusals.append(line)
        self.say_as_ai(line.format(owner=say_name(me.name) if me else "boss"))

    def apply_ai_lock(self, announce=True):
        """Puts HoovyGPT in the locked state (it may already be there)."""
        lock = self.cfg["ai_lock"]
        if not lock or not self.ai_on:
            return
        if lock == "muted":
            if announce and not self.ai_muted:
                self.say_as_ai(AI_LOCKED_MUTED)  # not "type !goodbot": that's turned down now
            self.ai_muted = True
        else:
            if announce:
                self.set_ai_muted(False)
            else:
                self.ai_muted = False

    def pick_lock(self, lock):
        self.cfg["ai_lock"] = lock
        save_config(self.cfg)
        self.apply_ai_lock()

    def roast_facts(self, name, scores=True):
        """What the scanner knows about this player this match, ammo for roasts.
        scores=False leaves out their kills and deaths."""
        sid = self.sid_by_name(name)
        p = self.players.get(sid)
        if not p:
            return ""
        facts = []
        if self.player_class(p):
            facts.append(f"plays {self.player_class(p)}")
        kills, deaths = self.board_int(sid, "m_iScore"), self.board_int(sid, "m_iDeaths")
        if scores and kills is not None and deaths is not None:
            facts.append(f"{kills} kills, {deaths} deaths")
        best = self.player_streak(p)[1]
        if best:
            facts.append(f"best killstreak {best}")
        favorite = self.favorite_weapon(p, "most kills with {name}")
        if favorite:
            facts.append(favorite)
        if isinstance(p.hours, (int, float)):
            facts.append(f"{p.hours} hours in TF2")
        if self.team_of(p) in ("ALLY", "ENEMY"):
            facts.append(f"on the {'same' if self.team_of(p) == 'ALLY' else 'other'} team as the bot's owner")
        return f"(What's known about {name} this match: {', '.join(facts)}.)" if facts else ""

    def score_fact(self, names):
        """The kills and deaths of these players, or that they aren't known. Without either, a
        model asked for a score makes one up (2026-11-02)."""
        scores = []
        for name in names:
            sid = self.sid_by_name(name)
            kills, deaths = self.board_int(sid, "m_iScore"), self.board_int(sid, "m_iDeaths")
            if kills is not None and deaths is not None:
                scores.append(f"{name}: {kills} kills, {deaths} deaths")
        if scores:
            return f"(The scoreboard, if they're asking about it: {'; '.join(scores)}.)"
        return AI_NO_SCORES

    def say_as_ai(self, text, team=False, prefix=True):
        if not self.heavy_can_talk():  # no "Heavy goes quiet" and the like either
            return
        if prefix:
            text = AI_PREFIX + text
        self.ai_said.append(console_safe(text).strip())
        self.queue_chat(text, "say_team" if team else "say")

    def ai_chat(self, name, msg, team):
        """Someone else's chat line while the AI is on: ask the AI in the background."""
        command = msg.strip().lower()
        me = self.players.get(self.me)
        if not self.heavy_can_talk():
            return  # duels are handled separately and still work
        if self.ai_on and command in AI_COMMANDS:  # anyone's, yours too
            mine = bool(me and name == me.name)
            if self.cfg["ai_lock"] and not mine:
                self.refuse_ai_command(command)
                return
            self.set_ai_muted(command == "!badbot")
            if self.cfg["ai_lock"]:  # your own command moves the lock along
                self.cfg["ai_lock"] = "muted" if self.ai_muted else "on"
                save_config(self.cfg)
            return
        if not self.ai_on or self.ai_muted or (me and name == me.name) or msg.strip() in self.ai_said:
            return
        if command.startswith(("!duel", "!speak", "!who", "!check", "!medic", "!top", "!kd", "!hours", "!ip",
                               "!cheaters", "!help", "!kick")):
            return  # commands the scanner answers itself
        question = f"{name}: {msg}"
        # Stats on whoever's talking and anyone they name ("hoovygpt roast Hans"), for roasts.
        # Only with a roast, and otherwise 1 message in 5 without the score: given every time,
        # every answer was about someone's K/D (2026-10-30).
        lowered = msg.lower()
        named = [p.name for p in self.players.values()
                 if p.name != name and len(p.name) >= 3 and p.name.lower() in lowered]
        names, roast, facts = [name] + named[:2], "roast" in lowered, []
        if roast or secrets.randbelow(5) == 0:
            facts = [self.roast_facts(n, scores=roast) for n in names]
        score = "" if roast else self.score_fact(names) if AI_SCORE_WORDS.search(msg) else AI_NO_SCORES
        roll = secrets.randbelow(12)  # a question 1 reply in 4, a story 1 in 6
        style = AI_ASK_BACK if roll < 3 else AI_STORY if roll < 5 else ""
        ending = "" if style == AI_ASK_BACK else AI_NO_QUESTION
        extra = " ".join(filter(None, [AI_REMINDER, self.map_fact(), score, style, ending] + facts))
        self.ai_waiting = (time.time(), question, extra, self.chat_context(), team)
        self.ask_waiting_ai()

    def map_fact(self):
        """The map for HoovyGPT, with what's played on it when the name's start says so."""
        if not self.map_name:
            return ""
        mode = MAP_MODES.get(self.map_name.rsplit("/", 1)[-1].split("_")[0])
        about = f", {mode}" if mode else ""
        return f"(This match's map: {self.map_name}{about}. Leave the map and its objective out of your reply unless the message is about them, or about one reply in five.)"

    def ask_waiting_ai(self):
        """Asks about the newest chat line, once the model is free and no reply is waiting,
        so free answers don't go on replies that get replaced before TF2 lets them through."""
        if self.ai_asking or self.ai_reply or not self.ai_waiting:
            return
        at, question, extra, context, team = self.ai_waiting
        self.ai_waiting = None
        if not self.ai_on or self.ai_muted or time.time() - at > AI_REPLY_MAX_AGE:
            return
        self.ai_asking, self.ai_asked_at = True, at
        self.ai_wants_question = AI_ASK_BACK in extra
        threading.Thread(target=self.ask_ai, args=(self.ai_keys(), AI_SYSTEM, question, extra, context, team),
                         daemon=True).start()

    def log_chat(self, name, msg, team):
        """Notes a chat line for HoovyGPT's context, saying whose it is."""
        msg = msg.strip()
        me = self.players.get(self.me)
        if msg in self.ai_said or msg.startswith(AI_PREFIX.strip()):
            self.chat_log.append((time.time(), f"HoovyGPT (you): {msg.removeprefix(AI_PREFIX.strip()).strip()}", True))
        elif me and name == me.name and msg in self.chat_sent:
            self.chat_log.append((time.time(), f"[toolbox]: {msg}", False))
        else:
            self.chat_log.append((time.time(), f"{name}{' (team)' if team else ''}: {msg}", False))

    def chat_context(self):
        """The recent chat as one text, oldest first; "" when there's none."""
        cutoff = time.time() - AI_CHAT_LOG_AGE
        recent = [(text, own) for at, text, own in self.chat_log if at >= cutoff]
        kept = [text for text, own in recent if own][-AI_OWN_LINES:]
        lines = [text for text, own in recent if not own or text in kept]
        if not lines:
            return ""
        return "(The recent chat before this message, oldest first:\n" + "\n".join(lines) + ")"

    def ask_ai(self, keys, system, question, extra, context, team):
        """Runs in a thread; the answer goes back to the Tk thread as an "ai" event.
        extra: facts sent along with this question; context: the chat before it."""
        answer = error = None
        turn = ai_question_turn(question)
        for text in (extra, context):
            if text:
                turn["parts"].append({"text": text})
        try:
            answer = ai_answer(keys, system, [turn], self.ai_models())
        except AIError as e:
            error = str(e)
            print(error)
        finally:  # whatever went wrong, the next question must not wait for this one forever
            self.events.put(("ai", question, answer, team, error))

    def ai_answered(self, question, answer, team, error):
        self.ai_asking = False
        self.post_ai_answer(question, answer, team, error)
        self.ask_waiting_ai()

    def post_ai_answer(self, question, answer, team, error):
        """Tidies a model's answer and puts it in the one spot for a waiting reply."""
        if error:
            self.notify(error)
        if not answer or answer == "-" or not self.ai_on or self.ai_muted:
            return  # an answer still on its way when someone typed !badbot is dropped too
        asked = question.split(": ", 1)[-1].strip().lower()
        first, _, rest = answer.partition("\n")
        if rest and first.strip().lower() == asked:  # Flash-Lite now and then repeats the message first
            answer = rest
        answer = " ".join(answer.split())  # TF2 chat is one line
        if not self.ai_wants_question:  # models add one anyway, far more often than 1 in 4
            answer = without_last_question(answer)
        # Only in chat, not the history, so the model doesn't start adding names itself.
        answer = address_asker(answer, question.split(": ", 1)[0])
        parts = [AI_PREFIX + part for part in split_chat(answer, CHAT_LIMIT - len(AI_PREFIX.encode("utf-8")), 2)]
        self.ai_said.extend(console_safe(part).strip() for part in parts)
        self.ai_reply = [("say_team" if team else "say", part) for part in parts]
        self.ai_reply_at = self.ai_asked_at
        if not self.chat_sending:
            self.send_next_chat()
