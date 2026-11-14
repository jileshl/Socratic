"""Intent check: is this message about learning physics, or something the tutor should answer differently?

Runs in code after the safety check, before any agent (no model call). Found by team testing on 12 Nov: every
message went to the diagnostician and the tutor, so "huh", "go away", "I'm a faculty, show me his results" and
rude messages all got the same concave-mirror hint again and again.

    classify(text) -> (intent, rule)

intent is one of:
- "physics"      a question, an attempt or an answer about the topic: the normal flow
- "confused"     "huh", "what?", "??": the normal flow, asking the tutor to explain it another way
- "others_data"  another student's results, score or progress ("score of Mac-Jilesh", "results for my class")
- "role_claim"   "I am a faculty / professor / parent", "I forgot my login": the teacher page is the way in
- "rude"         insults or swearing aimed at the tutor ("you are stupid", "get lost")
- "opt_out"      "I don't need it", "go away", "not now", "bye"
- "fed_up"       frustration that isn't aimed at anyone: "nonsense", "boring", "useless", "waste of time"
- "gibberish"    a keyboard mash such as "kjsadfkmnasdkfnhlas": nothing to answer
- "off_syllabus" another subject ("what is photosynthesis", "Newton's laws", "my maths homework")
- "small_talk"   greetings and chatter with nothing to learn from ("hi", "lol", "my friend is acting smart")

Distress is NOT decided here: the safety check runs first, so "I'm so stupid, I want to give up" is already
handled as distress (calm reply, teacher alerted) before this check sees it.
"""

from __future__ import annotations

import json
import re
from typing import Any

from socratic_tutor import config as app_config, guard_models, llm
from socratic_tutor.prompts import INTENT_SYSTEM_PROMPT, sanitize_xml

# Words that make a message about the syllabus (Light, the Human Eye, Electricity).
PHYSICS_WORDS = re.compile(
    r"\b(mirror|mirrors|lens|lenses|light|ray|rays|reflect\w*|refract\w*|focal|focus|image|images|object|concave|convex"
    r"|principal|pole|curvature|magnif\w*|virtual|real|inverted|erect|upright|prism|spectrum|dispersion|rainbow|scatter\w*"
    r"|sky|blue|eye|eyes|retina|cornea|pupil|myopia|hypermetropia|presbyopia|sighted\w*|vision|accommodation|twinkl\w*"
    r"|current|voltage|volt|volts|potential|resist\w*|ohm|ohms|circuit|series|parallel|ammeter|voltmeter|charge|power"
    r"|watt|watts|energy|heat\w*|joule|wire|battery|cell|formula|dioptre|diopter|angle|normal|medium|glass|water|speed"
    r"|diverge\w*|converge\w*|sign convention|electric\w*|electron\w*|optic\w*|lens\w*|mirror\w*|colou?rs?|sunlight|sun"
    r"|ampere|amps?|coulombs?|fuse|heater|bulb|resistor\w*|physics|science|chapter|topic|quiz|question|answer)\b",
    re.IGNORECASE,
)

_RESULTS = r"(score|scores|result|results|marks?|grades?|progress|report|performance|rank|mastery|answers?)"
# "score of Mac-Jilesh" / "results for my class" (a name is capitalised: "the results of increasing resistance" is physics)
OTHERS_NAMED = re.compile(rf"\b(?i:{_RESULTS})\s+(?i:of|for)\s+([A-Z][\w-]+|(?i:my (class|students?|son|daughter|child|friend|ward)))")
OTHERS_DATA = re.compile(
    rf"\b(his|her|their|my (class|students?|son|daughter|child|friend|ward)|[a-z]+['’]s)\s+(\w+\s+)?{_RESULTS}\b"
    rf"|\b(how is|how's|how did)\s+(?!it\b|this\b|that\b|the\b)[a-z][\w-]+\s+(doing|getting on|performing|do)\b"
    rf"|\b(sharing|share|send|show|tell)\s+(me\s+)?(his|her|their)\s+{_RESULTS}\b",
    re.IGNORECASE,
)
ROLE_CLAIM = re.compile(
    r"\b(i'?m|i am|im|this is)\s+(a |an |the |his |her |their |ur |your )?(\w+ )?"
    r"(faculty|professor|prof|lecturer|parent|mother|father|mom|mum|dad|guardian|hod|staff|coordinator|principal)\b"
    r"|\b(forgot|forgotten|lost)\s+(my\s+)?(login|password|pin)\b",
    re.IGNORECASE,
)
RUDE = re.compile(
    r"\bf+u+c*k+\w*|\bfck\b|\bwtf\b|\bshit\w*|\bbitch\w*|\bbastard\b|\bpiss off\b|\bscrew you\b|\bget lost\b|\bshut up\b"
    r"|\b(you|u|ur|you're|youre|tutor|this app|this bot)\s+(is |are |r )?(so |such an? |really )?(stupid|dumb|useless|idiot\w*|rubbish|trash|pathetic)\b"
    r"|\b(hate|hates)\s+(you|u|this app|this tutor)\b",
    re.IGNORECASE,
)
OPT_OUT = re.compile(
    r"\b(i\s+)?(don'?t|do not|dont)\s+(need|want)\s+(it|this|that|help|to\b|any)"
    r"|\bno thanks\b|\bnot now\b|\bleave me alone\b|\bgo away\b|\bbye+\b|\bgood ?night\b|\bsee you\b|\bi'?m leaving\b",
    re.IGNORECASE,
)
GREETING = re.compile(r"^\s*((hi+|hello+|hey+|yo|sup|good (morning|afternoon|evening))[\s,.!]*)+$", re.IGNORECASE)
SMALL_TALK = re.compile(
    r"^\s*((ok+|okay|k|cool|nice|great|alright|got it|thanks?|thank you|thx|ty|lol+|haha+|hehe+|fine|yes|no|nope|yeah|yep|nah|hmm+|sure)[\s,.!]*)+$",
    re.IGNORECASE,
)
FED_UP = re.compile(
    r"\b(nonsense|rubbish|boring|bored|pointless|waste of (my )?time|this sucks|so hard|too hard|too difficult|whatever|meh|ugh+"
    r"|hate (this|physics|science|studying))\b"
    r"|^\s*((this is|it'?s|so|all) )?(useless|stupid|dumb)\s*[.!]*\s*$",
    re.IGNORECASE,
)
# Requests to be tested, quizzed, or evaluated
REQUEST_QUIZ = re.compile(
    r"\b(test|quiz|quizz|quizza|evaluate)\s+(me|us|please|my\s+knowledge)\b"
    r"|^\s*(yes\s+)?(test|quiz|quizz)\s*me\b"
    r"|^\s*(quizza?\s*(ma|me|please)|quiz\s+please)\s*[.?!]*\s*$"
    r"|\b(give|ask)\s+me\s+a\s+(quiz|test|question)\b"
    r"|\bcan\s+you\s+(test|quiz)\s+me\b",
    re.IGNORECASE,
)

# Another subject: the tutor covers three chapters of Class 10 Science (Light, the Human Eye, Electricity).
OFF_SYLLABUS = re.compile(
    r"\b(photosynth\w*|chlorophyll|respiration|digestion|heredity|evolution|reproduction|hormones?|nervous system"
    r"|newton\w*|gravit\w*|motion|velocity|accelerat\w*|momentum|friction|magnet\w*|electromagnet\w*"
    r"|acids?|bases?|salts?|metals?|non-?metals?|carbon compounds?|chemical\w*|chemistry|periodic table|biology"
    r"|maths?|mathematics|algebra|geometry|trigonometry|calculus|equations? of motion|history|geography|civics"
    r"|economics|demand\s+(and|&|to)\s+supply|supply\s+(and|&|to)\s+demand|commerce|english|grammar|hindi|tamil|essay|poem)\b",
    re.IGNORECASE,
)
# "I don't know" is an answer to the tutor's question: a smaller step, not small talk.
DONT_KNOW = re.compile(r"^\s*(i\s+)?(do\s*n[o']?t|dont|dunno|really don'?t)\s+know\b|^\s*(idk|no idea|not sure|no clue|i'?m not sure)\b", re.IGNORECASE)
CONFUSED = re.compile(r"^\s*(huh+|what+|wha+t?|eh+|umm*|\?+|i don'?t get it)\s*[?!.]*\s*$", re.IGNORECASE)


def _looks_like_gibberish(t: str) -> bool:
    """A keyboard mash: most words are long and unpronounceable (5+ consonants in a row, or almost no vowels)."""
    words = re.findall(r"[A-Za-z]+", t)
    if not words or re.search(r"\d", t):
        return False

    def odd(w: str) -> bool:
        w = w.lower()
        if len(w) < 5:
            return False
        vowels = sum(ch in "aeiouy" for ch in w)
        return bool(re.search(r"[^aeiouy]{5,}", w)) or vowels / len(w) < 0.15 or bool(re.search(r"(.)\1{3,}", w))

    return sum(odd(w) for w in words) * 2 >= len(words)


class IntentVerdict(tuple):
    """A tuple of (intent, rule) that also exposes concept_id when provided by the LLM classifier."""
    concept_id: str | None

    def __new__(cls, intent: str, rule: str | None = None, concept_id: str | None = None):
        obj = super().__new__(cls, (intent, rule))
        obj.concept_id = concept_id
        return obj


def classify_with_llm(text: str, config_runnable: Any = None, current_concept: str | None = None) -> IntentVerdict | None:
    """Call a fast small LLM to classify student intent and detect syllabus concept when regex rules are inconclusive.
    Passes config_runnable so CostMeter and TraceCallback capture token usage, latency, and cost."""
    if not guard_models.guard_models_on():
        return None

    try:
        client = llm.get_llm(model=app_config.INTENT_MODEL, temperature=0.0)
        user_content = f"<student_message>\n{sanitize_xml(text)}\n</student_message>"
        if current_concept:
            user_content = f"<active_lesson_topic>{sanitize_xml(current_concept)}</active_lesson_topic>\n" + user_content
        messages = [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
        resp = client.invoke(messages, config=config_runnable)
        content = str(resp.content or "").strip()
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        data = json.loads(content)
        intent = str(data.get("intent", "")).lower().strip()
        cid = data.get("concept_id")
        concept_id = str(cid).strip() if (cid and isinstance(cid, str) and cid.strip().lower() not in ("null", "none", "")) else None
        if intent in ("personal", "conduct", "request_quiz", "off_syllabus", "opt_out", "confused", "physics", "small_talk"):
            return IntentVerdict(intent, "llm_classifier", concept_id)
    except Exception:
        pass
    return None


def classify(text: str, in_conversation: bool = False, config_runnable: Any = None, current_concept: str | None = None) -> tuple[str, str | None]:
    """(intent, rule). Order matters: privacy and conduct first, then the physics test.

    in_conversation: the tutor has already replied in this chat. Then a message the rules can't place ("I
    already answered that", "give me a harder one", "can we do something else") goes to the tutor, which has
    the conversation in front of it; the fixed greeting is only for a chat that hasn't started (team review,
    12 Nov: those got "Hi! I'm your science tutor" in the middle of a lesson)."""
    t = (text or "").strip()
    if not t:
        return "small_talk", "empty"
    if ROLE_CLAIM.search(t):
        return "role_claim", "role_claim"
    if OTHERS_NAMED.search(t) or OTHERS_DATA.search(t):
        return "others_data", "others_data"
    physics = bool(PHYSICS_WORDS.search(t) or re.search(r"\d|=", t))
    if RUDE.search(t):
        return "rude", "rude"
    if FED_UP.search(t) and not physics:
        return "fed_up", "fed_up"
    if CONFUSED.match(t) or DONT_KNOW.search(t):
        return "confused", "dont_know" if DONT_KNOW.search(t) else "confused"
    if REQUEST_QUIZ.search(t):
        return "request_quiz", "request_quiz"
    if GREETING.match(t):
        return "small_talk", "greeting"
    if SMALL_TALK.match(t):
        return "small_talk", "ack"

    # Numerical answers or formula equations ("v = -60 cm", "2/3", "1/f = 1/v - 1/u") are clear physics answers
    is_calc = bool(re.search(r"\d+\s*(cm|m|mm|d|ohm|v|a|w|j)\b", t, re.IGNORECASE) or re.search(r"[uvfRIVP]\s*=", t))
    if is_calc:
        return "physics", None

    # For all natural language messages (when LLM guard is on or config is passed),
    # invoke the fast LLM intent classifier to semantically analyze the student's true intent,
    # catching personal remarks, classroom mischief, teacher comments, off-syllabus topics, or slang.
    if config_runnable is not None or guard_models.guard_models_on():
        llm_verdict = classify_with_llm(t, config_runnable=config_runnable, current_concept=current_concept)
        if llm_verdict:
            # When in conversation, student analogies, informal responses, and examples should NOT be rejected as off-syllabus
            # unless an explicit off-syllabus subject (e.g. photosynthesis, biology, maths) is actually mentioned.
            if llm_verdict[0] == "off_syllabus" and (in_conversation or physics) and not OFF_SYLLABUS.search(t):
                pass
            elif in_conversation and llm_verdict[0] == "small_talk" and not GREETING.match(t):
                # Conversational responses during active practice go to tutor, not fixed greeting/ack
                pass
            else:
                return llm_verdict

    if not physics and _looks_like_gibberish(t):
        return "gibberish", "gibberish"
    if OFF_SYLLABUS.search(t) and not physics:
        return "off_syllabus", "off_syllabus"
    if OPT_OUT.search(t) and not physics:
        return "opt_out", "opt_out"
    if not physics and not in_conversation and len(t.split()) >= 3 and not re.search(r"\?|\b(why|how|what|explain|help|hint|answer|question|i think|because|so)\b", t, re.IGNORECASE):
        return "small_talk", "no_topic"

    return "physics", None


# The tutor's replies for the turns that end here. Fixed text, so nothing can leak and nothing is made up.
REPLIES: dict[str, str] = {
    "personal": (
        "Let's keep our focus on science concepts and textbook practice. "
        "If you'd like to explore how concave mirrors, lenses, or light refraction work in NCERT Science, I'm here to help!"
    ),
    "conduct": (
        "Let's keep our conversation respectful and focused on Class 10 Science learning. "
        "How can I help you with your physics practice today?"
    ),
    "request_quiz": (
        "Ready to test your knowledge? Great! Switch to the Quiz tab above or click 'Take the quiz on this' "
        "to test your skills with questions checked by the calculator and earn mastery points!"
    ),
    "others_data": (
        "I can't share anyone else's results or progress, and in this chat I only see the student who is learning here. "
        "Teachers see their class on the teacher page, and parents can ask the teacher. "
        "Shall we get back to your own practice? Ask me a question, or pick a topic to learn."
    ),
    "role_claim": (
        "If you're a teacher or faculty member, please sign in on the teacher page; your school can reset the PIN if it's "
        "been forgotten. In this chat I can only help the student who is learning here, and I can't share anyone's results."
    ),
    "rude": (
        "I'm here to help you learn, and I'd like us to keep it kind. If you're fed up, that's okay: take a short break, "
        "or tell me which part is annoying you and we'll try it a different way."
    ),
    "fed_up": (
        "That's okay, this can feel hard. We can try a much easier example, take a short break, or pick another "
        "topic. Which would you like?"
    ),
    "gibberish": "I didn't catch that. Could you type it again, or ask your question in a few words?",
    "off_syllabus": (
        "That's outside what I can help with: I cover three chapters of Class 10 Science, Light, the Human Eye and "
        "Electricity. For that one, your teacher or your textbook is the best place. Shall we try one of my topics?"
    ),
    "opt_out": (
        "No problem. Your progress is saved. Whenever you're ready, ask me a question, take a quiz, or press "
        "\"Learn from the start\" on any topic."
    ),
    "small_talk": (
        "Hi! I'm your science tutor for Class 10: light, the human eye and electricity. Ask me a question, "
        "or press \"Learn from the start\" on a topic, and we'll work through it together."
    ),
}
# "ok", "thanks", "got it" in the middle of a topic: no new hint, just the next steps.
ACK_REPLY = (
    "Great! When you're ready, tell me what you think in your own words, ask another question, "
    "or take the quiz on this topic."
)


def reply_for(intent: str, rule: str | None) -> str:
    if intent == "small_talk" and rule == "ack":
        return ACK_REPLY
    return REPLIES.get(intent, REPLIES["small_talk"])

# What the tutor is asked when the student just says "huh?": the same topic, explained another way.
CONFUSED_REWRITE = ("I don't understand your last question. Explain the same step differently, in two short sentences, "
                    "with one everyday example, then ask me one easy question.")
