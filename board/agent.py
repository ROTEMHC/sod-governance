"""סוכן ה-AI של SOD (UC-19): יועץ לכל דיון בסדר היום.

איך הוא עובד:
1. "למד" את הדוחות: כל דוח ציבורי בתיקייה corpus/ מחולק לעמודים, ולכל שאלה נשלפים רק העמודים הרלוונטיים.
2. מקבל את הנושא מסדר היום (ההחלטה הנדרשת, חלופות, סיכונים) ואת הנתונים הכספיים המאומתים.
3. מחזיר: תקציר, פערים מהותיים בדוחות, שאלות מומלצות להנהלה ודוחות נוספים ששווה לבקש. כל ממצא עם מקור.

אבטחה: למודל נשלחים רק הנושא והקטעים הרלוונטיים מהדוחות הציבוריים, לא מסמכים פנימיים ולא פרטים אישיים.
כל שאלה ותשובה נשמרות ביומן הפעולות כראיה שהדירקטור בדק ושאל.
"""
import json
import math
import re
from collections import Counter
from pathlib import Path

import anthropic
import streamlit as st

from board import financials as fin

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"
MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SOURCES = {  # שם הקובץ → שם הדוח כפי שיוצג בהפניות
    "rami_levy_periodic_2025.txt": "הדוח התקופתי של רמי לוי לשנת 2025",
}

_WORD = re.compile(r"[֐-׿A-Za-z0-9]{2,}")
_PREFIXES = "והבלמשכ"


# ---------------------------------------------------------------- "לימוד" הדוחות: חלוקה לעמודים ואינדקס
def _terms(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(text.lower()):
        out.append(w)
        if len(w) > 3 and w[0] in _PREFIXES:   # "במלאי" → גם "מלאי"
            out.append(w[1:])
    return out


@st.cache_resource
def corpus() -> dict:
    pages = []
    for path in sorted(CORPUS_DIR.glob("*.txt")):
        parts = re.split(r"\n--- p(\d+)\n", "\n" + path.read_text(encoding="utf-8"))
        for i in range(1, len(parts) - 1, 2):
            text = parts[i + 1].strip()
            if len(text) > 200:
                pages.append({"source": SOURCES.get(path.name, path.stem), "page": int(parts[i]),
                              "text": text, "tf": Counter(_terms(text))})
    df = Counter()
    for p in pages:
        df.update(p["tf"].keys())
    return {"pages": pages, "df": df, "n": len(pages)}


def retrieve(query: str, k: int = 8, max_chars: int = 40000) -> list[dict]:
    """העמודים הרלוונטיים ביותר לשאלה (tf-idf פשוט)."""
    c = corpus()
    q = set(_terms(query))
    scored = []
    for p in c["pages"]:
        score = sum((1 + math.log(p["tf"][t])) * math.log(c["n"] / (1 + c["df"][t]))
                    for t in q if p["tf"][t])
        if score > 0:
            scored.append((score, p))
    scored.sort(key=lambda x: -x[0])
    chosen, total = [], 0
    for _, p in scored[:k]:
        if total + len(p["text"]) > max_chars:
            continue
        chosen.append(p)
        total += len(p["text"])
    return chosen


# ---------------------------------------------------------------- חיבור ל-Claude
def available() -> bool:
    try:
        return bool(st.secrets.get("anthropic", {}).get("api_key"))
    except Exception:
        return False


@st.cache_resource
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=st.secrets["anthropic"]["api_key"])


SYSTEM = """אתה "היועץ של סוד", סוכן AI במערכת SOD Governance לניהול דירקטוריונים.
אתה מסייע לדירקטורים של סל הארץ קמעונאות בע"מ להתכונן לדיון ולקבל החלטה מיודעת.
הנתונים הכספיים של החברה מבוססים על הדוחות הציבוריים של רמי לוי שיווק השקמה.

כללי עבודה:
- ענה בעברית, בשפה עניינית ופשוטה, כמו יועץ שמדבר עם דירקטור.
- הסתמך רק על המידע שסופק: הנושא מסדר היום, הנתונים הכספיים המאומתים והקטעים מהדוחות. אם אין מספיק מידע, אמור זאת במפורש ואל תנחש.
- הנתונים המאומתים קודמים לקטעים מהדוחות: חלק מהמספרים בקטעים חולצו מקובץ PDF ועלולים להופיע בסדר ספרות שגוי.
- לכל ממצא ציין מקור: מספר ביאור, סעיף בדוח הדירקטוריון או מספר עמוד.
- אתה ממליץ בלבד. ההחלטה והאחריות נשארות אצל הדירקטוריון. אל תמליץ כיצד להצביע.
- התמקד במה שדירקטור צריך לשאול ולבדוק: פערים, מגמות חריגות, מידע חסר, והקשר בין המספרים לנושא הדיון."""

BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "gaps", "questions", "reports"],
    "properties": {
        "summary": {"type": "string", "description": "2-3 משפטים: על מה הדיון ומה חשוב לדירקטור לדעת"},
        "gaps": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "detail", "source"],
            "properties": {"title": {"type": "string"}, "detail": {"type": "string"}, "source": {"type": "string"}}}},
        "questions": {"type": "array", "items": {"type": "string"}},
        "reports": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["title", "period", "why"],
            "properties": {"title": {"type": "string"}, "period": {"type": "string"}, "why": {"type": "string"}}}},
    },
}


def _verified_figures() -> str:
    lines = [f"{fin.LABELS.get(k, k)}: 2024={v[2024]:,.1f}, 2025={v[2025]:,.1f} (מיליוני ש\"ח)"
             for k, v in fin.DATA.items() if k in fin.LABELS]
    lines += [f"ביאור – {fin.LABELS[k]} ({n[0]}): {n[1]}" for k, n in fin.NOTES.items() if k in fin.LABELS]
    lines += ["ממצאי הניתוח המחושב:"] + [f"- {re.sub(r'[*]', '', t)}" for t in fin.agent_explanation()]
    return "\n".join(lines)


def _item_text(item: dict | None) -> str:
    if not item:
        return "שאלה כללית על הדוחות הכספיים (לא נבחר נושא מסדר היום)."
    fields = [("נושא", "title"), ("סוג", "item_type"), ("תקציר", "summary"), ("ההחלטה הנדרשת", "decision_required"),
              ("חלופות", "alternatives"), ("אפשרות לא לבצע", "no_go_option"), ("סיכונים", "risks"),
              ("תרחיש שלילי", "negative_scenario")]
    return "\n".join(f"{label}: {item.get(key) or 'לא צוין'}" for label, key in fields)


def _context(item: dict | None, query: str) -> tuple[str, list[dict]]:
    pages = retrieve(query)
    excerpts = "\n\n".join(f"<excerpt source=\"{p['source']}\" page=\"{p['page']}\">\n{p['text']}\n</excerpt>"
                           for p in pages)
    text = (f"<agenda_item>\n{_item_text(item)}\n</agenda_item>\n\n"
            f"<verified_figures>\n{_verified_figures()}\n</verified_figures>\n\n"
            f"<report_excerpts>\n{excerpts}\n</report_excerpts>")
    return text, pages


def brief(item: dict | None) -> tuple[dict, list[dict]]:
    """סקירה מובנית לדיון: תקציר, פערים, שאלות ודוחות לבקש."""
    query = " ".join(str(item.get(k) or "") for k in ("title", "summary", "decision_required", "risks")) if item \
        else "רווח מלאי ספקים לקוחות מזומנים הוצאות מימון"
    context, pages = _context(item, query)
    response = _client().beta.messages.create(
        model=MODEL, max_tokens=16000, system=SYSTEM,
        betas=[FALLBACK_BETA], fallbacks="default",
        output_config={"format": {"type": "json_schema", "schema": BRIEF_SCHEMA}},
        messages=[{"role": "user", "content": context + "\n\nהכן סקירה לדירקטור לקראת הדיון בנושא הזה: "
                   "תקציר, פערים מהותיים שאתה רואה בדוחות, 4-6 שאלות חשובות להנהלה, "
                   "ו-2-4 דוחות נוספים שכדאי לבקש (דוחות שאינם קיימים בחומר), עם נימוק לכל אחד."}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("הסוכן לא יכול היה לענות על הבקשה הזו.")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), pages


def chat_stream(item: dict | None, history: list[dict], question: str):
    """שאלת המשך חופשית, עם תשובה בהזרמה (טקסט שמופיע תוך כדי כתיבה)."""
    context, _ = _context(item, question + " " + (item or {}).get("title", ""))
    messages = [{"role": "user", "content": context + "\n\nאני דירקטור ויש לי שאלות על הנושא."},
                {"role": "assistant", "content": "בשמחה. מה תרצה לדעת?"}]
    messages += history + [{"role": "user", "content": question}]
    with _client().beta.messages.stream(
        model=MODEL, max_tokens=8000, system=SYSTEM,
        betas=[FALLBACK_BETA], fallbacks="default", messages=messages,
    ) as stream:
        yield from stream.text_stream
