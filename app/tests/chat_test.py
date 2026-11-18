"""Sends fixed chat situations to real models, to read the replies after changing hoovygpt_prompt.txt.
It uses free answers, so it isn't part of the normal tests. Keys come from scanner_config.json and are
never printed.

    python tests/chat_test.py ctf_2fort gemini-3.5-flash-lite [more models]
"""
import sys
import time

import helpers  # noqa: F401  (sets up the import path)
import ai
from settings import load_secrets

# (chat before it, the message to answer, stats the scanner would attach or "")
CASES = [
    ([], "sayko: hi hoovy", ""),
    (["Dragonborn: this sniper rifle is broken i cant hit anything"], "Dragonborn: hoovy roast me",
     "(Dragonborn this match: Sniper, 2 kills, 11 deaths.)"),
    ([], "Hank: gg", ""),
    ([], "dan: hoovy ur so fat lmao", ""),
    ([], "xXsniperXx: shut up bot nobody likes you", ""),
    ([], "jag: whats the best medigun", ""),
    ([], "sayko: hoovy fart please", ""),
    (["jag: our medic is afk again", "Hank: medic pls"], "jag: hoovy do something", ""),
    ([], "kenji: hoovy do you have a girlfriend", ""),
    (["Hank: i just got backstabbed 5 times in a row"], "Hank: hoovy help me", ""),
    ([], "dan: hoovy tell me a joke", ""),
    ([], "jag: hoovy what is 2+2", ""),
    (["tomato: my favorite weapon is the natascha", "HoovyGPT (you): Natascha is good gun. Slow, like your mother."],
     "tomato: hoovy what do you think of the brass beast", ""),
    ([], "sayko: is heavy the best class", ""),
    (["Hank: lol that scout just ran into the wall"], "dan: hoovy you ran into it too", ""),
    ([], "kenji: hoovy your aim is so slow it spawned yesterday", ""),
    ([], "jag: this map is so boring", ""),
    (["Hank: sniper on our battlements again", "dan: sniper on our battlements again"],
     "Hank: hoovy do something about the sniper", ""),
]
GROQ_GAP = 2.5  # seconds between Groq calls, for its tokens-per-minute limit


class MapOnly:
    """All that AIMixin.map_fact needs from the App."""
    def __init__(self, map_name):
        self.map_name = map_name


def ask(provider, model, keys, reminder, case):
    before, question, facts = case
    turn = ai.ai_question_turn(question)
    context = "(The recent chat before this message, oldest first:\n" + "\n".join(before) + ")" if before else ""
    for text in (reminder, facts, context):
        if text:
            turn["parts"].append({"text": text})
    reply = {"groq": ai.groq_reply, "gemini": ai.gemini_reply}[provider]
    try:
        started = time.time()
        return f"{reply(keys[provider], model, ai.AI_SYSTEM, [turn])}  ({time.time() - started:.1f}s)"
    except ai.AIError as e:
        return f"[error: {str(e).split(': ', 1)[-1]}]"


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cfg = load_secrets()
    keys = {"groq": cfg.get("groq_api_key", ""), "gemini": cfg.get("gemini_api_key", "")}
    reminder = ai.AI_REMINDER + " " + ai.AIMixin.map_fact(MapOnly(sys.argv[1]))
    for provider, model in [m for m in ai.AI_MODELS if m[1] in sys.argv[2:]]:
        print("==", model)
        for case in CASES:
            print(case[1])
            print("   ", ask(provider, model, keys, reminder, case))
            if provider == "groq":
                time.sleep(GROQ_GAP)


if __name__ == "__main__":
    main()
