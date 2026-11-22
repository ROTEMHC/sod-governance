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
    "auditors_kam_2024_2025.txt": "דוחות רואי החשבון המבקרים לשנים 2024 ו-2025",
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
              ("תרחיש שלילי", "negative_scenario"), ("עוצמת הסיכון", "risk_level"),
              ("דרכי טיפול בסיכון", "risk_mitigation"), ("בעל הסיכון", "risk_owner"), ("מדדי התראה", "risk_indicators")]
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


# ---------------------------------------------------------------- מצב מצומצם: ניתוח לפי כללים, בלי מודל שפה
# כל נושא מזוהה לפי מילות מפתח בכותרת ובתקציר, ולכל נושא יש בדיקות, שאלות ודוחות מומלצים משלו.
def _pct(k: str) -> str:
    return f"{fin.growth(k):+.1%}"


TOPICS = [
    {"name": "עסקה עם בעל עניין", "words": ["בעל עניין", "בעל שליטה", "צד קשור", "עסקה עם"],
     "query": "עסקאות עם בעלי שליטה בעלי עניין צדדים קשורים חכירה שכירות",
     "gaps": [("ניגוד עניינים ומחיר שוק",
               "בעסקה עם בעל עניין עיקר הסיכון הוא שהתנאים לא יהיו בתנאי שוק. החומר צריך להראות השוואה "
               "לחלופות ולמחיר שוק, ולא רק את ההצעה של בעל העניין.", "סעיף הסיכונים בנושא; ביאור צדדים קשורים"),
              ("רואי החשבון סימנו את החכירות מבעל השליטה כעניין מפתח בביקורת",
               "התחייבות החכירה מול בעל השליטה הייתה כ-882 מיליון ש\"ח בסוף 2025 (כ-816 מיליון ב-2024), ודמי השכירות "
               "ששולמו לו כ-86 מיליון ש\"ח בשנה. עסקה נוספת מגדילה חשיפה שכבר מהותית, ולכן נדרשת בחינה מעמיקה במיוחד.",
               "דוח רואי החשבון המבקרים (Deloitte ו-BDSK) לשנים 2024 ו-2025, ענייני מפתח בביקורת")],
     "questions": ["האם ועדת הביקורת דנה בעסקה ואישרה אותה לפני הדירקטוריון, והאם היא מסווגת כעסקה חריגה?",
                   "אם בעל העניין הוא בעל שליטה: האם נדרש גם אישור האסיפה הכללית ברוב מיוחד, ומה מסלול האישור לפי היועץ המשפטי?",
                   "עסקה לחמש שנים: האם עסקה עם בעל שליטה לתקופה של יותר משלוש שנים מחייבת אישור מחדש (סעיף 275 לחוק החברות)?",
                   "מה דמי השכירות לעומת שלושת המבנים החלופיים, ומי בדק זאת באופן בלתי תלוי?",
                   "אילו דירקטורים הצהירו על עניין אישי בעסקה, והאם הם לא ישתתפו בהצבעה?"],
     "reports": [("שמאות בלתי תלויה לדמי השכירות", "לפני ההחלטה",
                  "כדי לוודא שהמחיר בתנאי שוק, ולא להסתמך על נתוני הצד הקשור."),
                 ("השוואת הצעות משלושת המבנים החלופיים", "לפני ההחלטה",
                  "החלופה צוינה בתבנית אך אין לה נתונים: עלות, מיקום, זמינות."),
                 ("השפעת העסקה על התחייבויות החכירה והרווח (IFRS 16)", "חמש שנות החוזה",
                  "שכירות לחמש שנים נרשמת כהתחייבות במאזן ומשפיעה על הוצאות המימון והפחת.")]},
    {"name": "מלאי", "words": ["מלאי", "ספירה"],
     "query": "מלאי ספירת מלאי הפחתה ירידת ערך ימי מלאי",
     "gaps": [("המלאי גדל מהר יותר מהמכירות",
               f"המלאי גדל ב-{_pct('inventory')} בעוד שהמכירות גדלו ב-{_pct('sales')}. ימי המלאי: "
               f"{fin.inventory_days():.1f}. גידול כזה עלול להעיד על מלאי איטי או על צורך בהפחתה.", "ביאור 9: מלאי"),
              ("רואי החשבון סימנו את המלאי כעניין מפתח בביקורת",
               "בשתי השנים (323 מיליון ש\"ח ב-2024, 409 מיליון ב-2025) המלאי הוגדר עניין מפתח, כי קיומו והערכתו "
               "דורשים שיקול דעת: ספירות בסניפים ובמרכזים הלוגיסטיים, והפרשה לחוסרים במלאי שלא נספר בסוף השנה.",
               "דוח רואי החשבון המבקרים לשנים 2024 ו-2025, ענייני מפתח בביקורת")],
     "questions": ["איזה חלק מהגידול במלאי נובע מסניפים חדשים, ואיזה חלק ממלאי איטי בסניפים קיימים?",
                   "מה גיול המלאי, וכמה מלאי מעל 90 יום?",
                   "מה היו ממצאי הספירה האחרונה, ומה הפער בין הספירה לרישום?",
                   "האם נבחנה ירידת ערך, ומה ההפרשה לפחת ולפריטים שפג תוקפם?"],
     "reports": [("גיול מלאי לפי קטגוריה וסניף", "הרבעון האחרון", "מאפשר לזהות מלאי איטי לפני שהוא הופך להפסד."),
                 ("ממצאי ספירת המלאי והפערים", "הספירה האחרונה", "בדיקה בפועל של המלאי שבדוחות.")]},
    {"name": "דוחות כספיים", "words": ["דוחות", "דוח כספי", "רבעון"],
     "query": "רווח נקי הוצאות מימון רווח גולמי הסברי הדירקטוריון",
     "gaps": [("המכירות עלו אך הרווח הנקי ירד",
               f"מכירות {_pct('sales')}, רווח נקי {_pct('net_profit')}. הסיבה העיקרית: הוצאות המימון "
               f"({_pct('finance_net')}) והוצאות המכירה. ברבעון הרביעי גם פיצוי חד-פעמי על נזקי מלחמה.",
               "דוח רווח והפסד; דוח הדירקטוריון סעיף 1.3.6")],
     "questions": ["מה חלק ההכנסות החד-פעמיות ברווח, ומה הרווח בלעדיהן?",
                   "מה גרם לעלייה בהוצאות המימון, ומה מדיניות הגידור מול הדולר?",
                   "האם רואה החשבון המבקר העלה הערות או הדגשים, ומה נכתב במכתב ההנהלה?"],
     "reports": [("מכתב ההנהלה של רואה החשבון המבקר", "השנה האחרונה", "חושף ליקויי בקרה שאינם מופיעים בדוחות."),
                 ("גשר רווח רבעוני: מה הוסיף ומה גרע", "4 רבעונים", "מפריד בין שינוי עונתי לשינוי מתמשך.")]},
    {"name": "הרחבה והשקעה", "words": ["סניפים", "הרחבת", "השקעה", "רכישת"],
     "query": "סניפים חדשים פתיחת סניפים השקעות רכוש קבוע תוכנית",
     "gaps": [("חסרים נתוני כדאיות",
               "בהשקעה צריך לראות עלות, תשואה צפויה ותקופת החזר. פתיחה מואצת של סניפים כבר הורידה את הרווחיות "
               "במגזר גוד פארם לפי דוח הדירקטוריון.", "דוח הדירקטוריון, הסברי הרבעון הרביעי")],
     "questions": ["האם ההמלצה לאשר נשענת על הזמן והכסף שכבר הושקעו בבדיקה? אלה עלויות שקועות, ואינן "
                   "סיבה להמשיך (גיל פרץ, מפגש 13). מה החלופה הטובה ביותר אם לא נאשר?",
                   "מה ההשקעה הכוללת לכל סניף, ומתי הוא צפוי להגיע לרווח?",
                   "מה הביצועים בפועל של הסניפים שנפתחו בשנתיים האחרונות לעומת התוכנית?",
                   "איך תמומן ההשקעה, ומה ההשפעה על יחס החוב וההון?"],
     "reports": [("תוכנית עסקית ותקופת החזר לכל סניף", "5 שנים", "בסיס להחלטה מושכלת על השקעה."),
                 ("ביצועי סניפים חדשים מול תוכנית", "שנתיים אחרונות", "בודק אם ההנחות של ההנהלה התממשו בעבר.")]},
    {"name": "סייבר", "words": ["סייבר", "חדירה", "אבטחת מידע"],
     "query": "סייבר אבטחת מידע מערכות מידע סיכונים",
     "gaps": [("נושא לעדכון בלבד",
               "סייבר מוצג לעדכון, אך הדירקטוריון אחראי לפקח על הסיכון. כדאי לבקש לוח זמנים לסגירת הפערים.",
               "דוח הדירקטוריון, גורמי סיכון")],
     "questions": ["כמה פערים קריטיים נמצאו במבדק החדירה, ומתי ייסגרו?",
                   "האם יש ביטוח סייבר, ומה הכיסוי שלו?", "האם בוצע תרגיל התאוששות מאירוע סייבר השנה?"],
     "reports": [("ממצאי מבדק החדירה ותוכנית סגירת הפערים", "המבדק האחרון", "מעקב אחר ביצוע ולא רק עדכון.")]},
    {"name": "תקציב", "words": ["תקציב"],
     "query": "תחזית תקציב השקעות הוצאות שכר מכירות",
     "gaps": [("חסרה השוואה לביצוע בפועל",
               "תקציב נבחן מול הביצוע של השנה הקודמת: מכירות, שכר, הוצאות מימון והשקעות.", "דוחות 2025")],
     "questions": ["מה ההנחות לגידול המכירות ולעליית השכר, ועל מה הן מבוססות?",
                   "איך התקציב מתמודד עם עליית הוצאות המימון שנראתה ב-2025?",
                   "מה תרחיש הבסיס ומה התרחיש השלילי?"],
     "reports": [("תקציב מול ביצוע 2025", "2025", "מראה עד כמה התקציבים הקודמים היו מדויקים.")]},
    {"name": "ביקורת", "words": ["מבקר", "ביקורת"],
     "query": "מבקר פנימי ביקורת בקרות",
     "gaps": [], "questions": ["אילו ממצאים מהותיים עלו, ומי אחראי לתיקון ועד מתי?",
                               "האם ממצאים מביקורות קודמות טופלו?"],
     "reports": [("מעקב תיקון ליקויים מביקורות קודמות", "שנתיים אחרונות", "בודק שהממצאים לא נשארים על הנייר.")]},
]

REQUIRED = [("decision_required", "ההחלטה הנדרשת"), ("alternatives", "חלופות"), ("no_go_option", "אפשרות לא לבצע"),
            ("risks", "סיכונים"), ("negative_scenario", "תרחיש שלילי"), ("risk_level", "עוצמת הסיכון"),
            ("risk_mitigation", "דרכי טיפול בסיכון"), ("risk_owner", "בעל הסיכון"), ("risk_indicators", "מדדי התראה")]


def _snippet(text: str, query: str, width: int = 260) -> str:
    terms = [t for t in _terms(query) if len(t) > 2]
    pos = min((text.find(t) for t in terms if text.find(t) >= 0), default=0)
    s = re.sub(r"\s+", " ", text[max(0, pos - 80): pos + width]).strip()
    return "..." + s + "..."


def offline_brief(item: dict | None, conflicts: int = 0) -> tuple[dict, list[dict]]:
    """סקירה לדיון בלי מודל שפה: לפי תבנית החובה, נושא הדיון והדוחות. אותו מבנה כמו brief()."""
    text = " ".join(str((item or {}).get(k) or "") for k in ("title", "summary", "decision_required", "risks"))
    topics = [t for t in TOPICS if any(w in text for w in t["words"])] if item else [TOPICS[2]]
    gaps, questions, reports = [], [], []
    if item and item.get("item_type") == "decision":
        missing = [label for col, label in REQUIRED if not item.get(col)]
        if missing:
            gaps.append({"title": "חסרים רכיבי חובה בחומר הדיון",
                         "detail": f"חסרים: {', '.join(missing)}. בלי זה קשה להראות שההחלטה התקבלה בשיקול דעת "
                                   "ועל בסיס מידע מספק (כלל שיקול הדעת העסקי). אין החלטה מיודעת בלי ניהול סיכונים: "
                                   "הפרוטוקול צריך להראות שהסיכונים זוהו, נשקלו וטופלו.",
                         "source": "תבנית החובה לנושא להחלטה; חיים כהן, מפגש 14"})
            questions.append("מתי יושלמו " + ", ".join(missing) + "? האם לדחות את ההחלטה עד אז?")
    if conflicts:
        gaps.append({"title": f"{conflicts} משתתפים הצהירו על עניין אישי",
                     "detail": "מי שיש לו עניין אישי לא ישתתף בהצבעה על הנושא. יש לוודא שנשאר מניין חוקי.",
                     "source": "טפסי ההצהרה לישיבה"})
    for t in topics:
        gaps += [{"title": g[0], "detail": g[1], "source": g[2]} for g in t["gaps"]]
        questions += t["questions"]
        reports += [{"title": r[0], "period": r[1], "why": r[2]} for r in t["reports"]]
    query = " ".join(t["query"] for t in topics) or text
    pages = retrieve(query, k=4)
    for p in pages:
        p["snippet"] = _snippet(p["text"], query)
    names = " ו".join(t["name"] for t in topics) or "כללי"
    summary = (f"**{item['title']}**. זיהיתי שהנושא עוסק ב{names}. " if item else
               "סקירה כללית של הדוחות הכספיים. ") + \
              (f"ההחלטה הנדרשת: {item['decision_required'].rstrip('.')}. " if item and item.get("decision_required") else "") + \
              f"מצאתי {len(gaps)} פערים, {len(questions)} שאלות ו-{len(reports)} דוחות שכדאי לבקש."
    return {"summary": summary, "gaps": gaps, "questions": questions, "reports": reports}, pages


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
