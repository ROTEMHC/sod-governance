"""שכבת הנתונים: חיבור למסד PostgreSQL ב-Supabase.

החיבור נעשה מצד השרת בלבד, עם הכתובת שבקובץ .streamlit/secrets.toml.
כל השאילתות עם פרמטרים (:name), אף פעם לא בשרשור מחרוזות, כדי למנוע SQL Injection.
"""
import ssl
import threading
import urllib.parse
from pathlib import Path

import pg8000.native
import streamlit as st


def _connect_params():
    url = st.secrets["postgres"]["url"]
    u = urllib.parse.urlparse(url)
    return dict(
        user=urllib.parse.unquote(u.username or ""),
        password=urllib.parse.unquote(u.password or ""),
        host=u.hostname,
        port=u.port or 5432,
        database=(u.path or "/postgres").lstrip("/") or "postgres",
    )


@st.cache_resource
def _shared():
    """חיבור אחד משותף, עם נעילה: pg8000 אינו בטוח לשימוש מכמה תהליכונים בבת אחת."""
    return {"conn": None, "lock": threading.Lock()}


CA_FILE = Path(__file__).resolve().parent.parent / "certs" / "supabase-ca.crt"


def _ssl_context() -> ssl.SSLContext:
    """החיבור מוצפן ומאומת. תעודת השרת של Supabase חתומה ברשות האישורים של Supabase עצמה,
    ולכן מאמתים אותה מול קובץ התעודה הציבורי שלהם (certs/supabase-ca.crt)."""
    ctx = ssl.create_default_context()
    if CA_FILE.exists():
        ctx.load_verify_locations(cafile=str(CA_FILE))
    return ctx


def _open():
    return pg8000.native.Connection(ssl_context=_ssl_context(), timeout=30, **_connect_params())


# ---------------------------------------------------------------- הודעות שגיאה ברורות למשתמש
class UserError(Exception):
    """שגיאה שמוצגת למשתמש בעברית, בלי פרטים טכניים. הפרטים הטכניים נשמרים ביומן."""

    def __init__(self, message: str, technical: str = ""):
        super().__init__(message)
        self.technical = technical


# הפרות של חוקים עסקיים שהמסד אוכף (שם האילוץ ← הסבר למשתמש)
CONSTRAINT_HE = {
    "absence_needs_reason": "כשלא מגיעים לישיבה, חובה לבחור סיבת היעדרות.",
    "other_reason_needs_note": "בסיבת היעדרות \"אחר\" חובה לפרט.",
    "absence_review_complete": "החלטה על היעדרות חייבת לכלול גם את מי שהחליט/ה.",
    "signed_declaration_complete": "לא ניתן לחתום: חסרה תשובה לאחד הנושאים, אישור קריאת החומר או קוד האימות.",
    "signed_form_has_hash": "טופס חתום חייב לכלול חותמת שלמות.",
    "field_check_linked_to_item": "ממצא בדיקת שטח חייב להיות מקושר לנושא מסוים בסדר היום.",
    "conflict_needs_details": "כשמסמנים \"יש לי עניין אישי\", חובה לפרט מהו.",
    "no_vote_with_conflict": "מי שהצהיר/ה על עניין אישי בנושא אינו/ה רשאי/ת להצביע עליו.",
    "users_username_key": "שם המשתמש הזה כבר קיים במערכת.",
    "users_email_key": "כתובת הדוא\"ל הזו כבר רשומה למשתמש אחר.",
    "users_phone_key": "מספר הטלפון הזה כבר רשום למשתמש אחר.",
}
# הודעות מטריגרים במסד (קטע מההודעה ← הסבר למשתמש)
TRIGGER_HE = {
    "cannot vote before signing": "לא ניתן להצביע לפני חתימה על טופס הצהרת ניגוד העניינים לישיבה.",
    "append-only": "יומן הפעולות אינו ניתן לשינוי או למחיקה.",
    "OTP validity": "תוקף קוד האימות אינו יכול לעלות על 5 דקות.",
}
COLUMN_HE = {
    "rsvp": "אישור הגעה", "attended": "נוכחות", "absence_reason": "סיבת היעדרות", "status": "מצב",
    "mode": "אופן הישיבה", "item_type": "סוג הנושא", "risk_level": "עוצמת הסיכון", "vote": "הצבעה",
    "materials_deadline_days": "ימי הפצת החומר", "classification": "סיווג", "doc_type": "סוג המסמך",
    "role": "תפקיד", "minutes_status": "מצב הפרוטוקול", "severity": "חומרה", "channel": "ערוץ",
    "position": "מספר הנושא", "otp_attempts": "ניסיונות קוד", "failed_attempts": "ניסיונות כניסה",
    "title": "נושא", "text": "נוסח", "due_date": "מועד", "meeting_at": "מועד הישיבה", "name": "שם",
}
REFRESH = " רענן/י את המסך (F5) ונסה/י שוב."


def _field(e_fields: dict) -> str:
    col = e_fields.get("c") or ""
    if not col:   # אילוץ בדיקה בשם אוטומטי: <טבלה>_<עמודה>_check
        name = e_fields.get("n") or ""
        col = next((c for c in COLUMN_HE if name.endswith(f"_{c}_check") or name.endswith(f"_{c}_fkey")), "")
    return COLUMN_HE.get(col, "")


def _friendly(err: Exception) -> UserError:
    """מתרגם שגיאת מסד להודעה ברורה בעברית: מה קרה ומה לעשות."""
    f = err.args[0] if err.args and isinstance(err.args[0], dict) else {}
    code, msg, constraint = f.get("C", ""), f.get("M", str(err)), f.get("n", "")
    technical = f"{code} {constraint} {msg}".strip()
    field = _field(f)
    if constraint in CONSTRAINT_HE:
        return UserError(CONSTRAINT_HE[constraint], technical)
    for part, text in TRIGGER_HE.items():
        if part in msg:
            return UserError(text, technical)
    if code == "23514":   # ערך שאינו מהערכים המותרים
        return UserError(f"הערך שנבחר{' בשדה ' + field if field else ''} אינו מהערכים המותרים.", technical)
    if code == "23502":   # שדה חובה ריק
        return UserError(f"חסר שדה חובה{': ' + field if field else ''}.", technical)
    if code == "23505":   # כפילות
        return UserError("הרשומה הזו כבר קיימת במערכת, אולי משתמש/ת אחר/ת שמר/ה אותה זה עתה." + REFRESH, technical)
    if code == "23503":   # הפניה לרשומה שאינה קיימת
        return UserError(f"הפריט שנבחר{' (' + field + ')' if field else ''} כבר לא קיים: "
                         "ייתכן שמשתמש/ת אחר/ת מחק/ה או שינה אותו בינתיים." + REFRESH, technical)
    if code in ("22P02", "22003", "22007", "22008", "22001", "22023"):   # סוג נתון שאינו מתאים
        return UserError(f"הערך שהוזן{' בשדה ' + field if field else ''} אינו מתאים לסוג השדה "
                         "(למשל טקסט במקום מספר, תאריך לא תקין, או טקסט ארוך מדי).", technical)
    if code in ("40001", "40P01", "55P03"):   # התנגשות עם פעולה של משתמש אחר
        return UserError("משתמש/ת אחר/ת עדכן/ה את אותו מידע באותו רגע. השינוי שלך לא נשמר." + REFRESH, technical)
    if code == "42501":   # אין הרשאה במסד
        return UserError("אין לך הרשאה לפעולה הזו.", technical)
    return UserError("הפעולה לא הושלמה בגלל תקלה במסד הנתונים. הפרטים נשמרו לצוות התמיכה.", technical)


def query(sql: str, **params) -> list[dict]:
    """מריץ שאילתה ומחזיר רשימת שורות כ-dict. מתחבר מחדש אם החיבור נפל.
    כל שגיאה מתורגמת ל-UserError עם הודעה ברורה בעברית."""
    shared = _shared()
    with shared["lock"]:
        for attempt in (1, 2):
            try:
                if shared["conn"] is None:
                    shared["conn"] = _open()
                conn = shared["conn"]
                rows = conn.run(sql, **params)
                cols = [c["name"] for c in (conn.columns or [])]
                return [dict(zip(cols, r)) for r in rows] if cols and rows else []
            except pg8000.exceptions.DatabaseError as e:
                raise _friendly(e) from e
            except (pg8000.exceptions.InterfaceError, OSError, ConnectionError) as e:
                shared["conn"] = None
                if attempt == 2:
                    raise UserError("אין כרגע חיבור למסד הנתונים. נסה/י שוב בעוד דקה, ואם זה נמשך פנה/י "
                                    "למנהל/ת מערכות המידע.", f"{type(e).__name__}: {e}") from e


def one(sql: str, **params) -> dict | None:
    rows = query(sql, **params)
    return rows[0] if rows else None


def execute(sql: str, **params) -> None:
    query(sql, **params)


def audit(user_id, action, entity=None, entity_id=None, details=None) -> None:
    """רישום ביומן הפעולות. היומן אינו ניתן לעריכה או למחיקה (נאכף בטריגר במסד)."""
    execute("INSERT INTO audit_log (user_id, action, entity, entity_id, details) "
            "VALUES (:u, :a, :e, :i, :d)", u=user_id, a=action, e=entity, i=entity_id, d=details)


@st.cache_data(ttl=60)
def settings() -> dict:
    """הגדרות המערכת מטבלת settings (מתעדכן כל דקה)."""
    return {r["key"]: r["value"] for r in query("SELECT key, value FROM settings")}


def setting_int(key: str, default: int) -> int:
    try:
        return int(settings().get(key, default))
    except (TypeError, ValueError):
        return default
