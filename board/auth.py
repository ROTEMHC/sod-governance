"""כניסה מאובטחת בשלושה שלבים (UC-01, UC-26) והחלפת סיסמה (UC-22).

שלב 1: שם משתמש וסיסמה. שלב 2: אימות ערוץ (טלפון או דוא"ל, שחייב להתאים לרשומה).
שלב 3: קוד חד-פעמי (OTP) בן 6 ספרות, תקף 5 דקות לכל היותר, ונמחק מיד אחרי השימוש.
"""
import base64
import hashlib
import hmac
import os
import re
import secrets
import string

from board import db

GENERIC_ERROR = "שם משתמש או סיסמה שגויים."


# ------------------------------------------------------------------ גיבוב
def hash_secret(secret: str) -> str:
    """גיבוב scrypt עם מלח אקראי. נשמר רק הגיבוב, אף פעם לא הערך עצמו."""
    salt = os.urandom(16)
    n, r, p = 2 ** 14, 8, 1
    dk = hashlib.scrypt(secret.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_secret(secret: str, stored: str | None) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(secret.encode(), salt=base64.b64decode(salt_b64),
                            n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (AttributeError, ValueError):
        return False


# ------------------------------------------------------------------ עזר
def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    return (name[:2] + "•" * max(1, len(name) - 2) + "@" + domain) if domain else email


def mask_phone(phone: str) -> str:
    return "•" * max(0, len(phone) - 3) + phone[-3:]


def _norm_phone(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    return "972" + digits[1:] if digits.startswith("0") else digits


# ------------------------------------------------------------------ שלב 1
def check_password(username: str, password: str) -> tuple[dict | None, str | None]:
    """מחזיר (משתמש, None) בהצלחה, או (None, הודעת שגיאה)."""
    u = db.one("SELECT id, username, name, role, job_title, active, password_hash, "
               "failed_attempts, locked_until, locked_until > now() AS is_locked, "
               "ceil(extract(epoch FROM (locked_until - now())) / 60)::int AS lock_minutes_left "
               "FROM users WHERE username = :u", u=username.strip())
    if u is None or not u["active"]:
        return None, GENERIC_ERROR          # לא חושפים אם המשתמש קיים
    if u["is_locked"]:
        db.audit(u["id"], "login_blocked", "user", u["id"], "ניסיון כניסה לחשבון נעול")
        return None, f"החשבון נעול. ניתן לנסות שוב בעוד {u['lock_minutes_left']} דקות, או לפנות למנהל/ת מערכות המידע."
    if not verify_secret(password, u["password_hash"]):
        register_failure(u["id"], "סיסמה שגויה")
        return None, GENERIC_ERROR
    return u, None


def register_failure(user_id: int, reason: str) -> None:
    """ניסיון כושל: מונה עולה, ובהגעה לסף החשבון ננעל לזמן מוגדר."""
    threshold = db.setting_int("lockout_threshold", 5)
    minutes = db.setting_int("lockout_minutes", 30)
    row = db.one("UPDATE users SET failed_attempts = failed_attempts + 1, "
                 "locked_until = CASE WHEN failed_attempts + 1 >= :t "
                 "THEN now() + make_interval(mins => CAST(:m AS int)) ELSE locked_until END "
                 "WHERE id = :id RETURNING failed_attempts, locked_until IS NOT NULL "
                 "AND locked_until > now() AS locked", t=threshold, m=minutes, id=user_id)
    db.audit(user_id, "login_failed", "user", user_id, reason)
    if row and row["locked"]:
        db.audit(None, "account_locked", "user", user_id, f"נעילה ל-{minutes} דקות")


# ------------------------------------------------------------------ שלב 2
def check_channel(user_id: int, channel: str, value: str) -> tuple[str | None, str | None]:
    """בודק שהטלפון או הדוא"ל תואמים לרשומה. מחזיר (יעד ממוסך, None) או (None, שגיאה)."""
    u = db.one("SELECT email, phone FROM users WHERE id = :id", id=user_id)
    if channel == "email":
        ok = u["email"] and value.strip().lower() == u["email"].lower()
        target = mask_email(u["email"]) if ok else None
    else:
        ok = u["phone"] and _norm_phone(value) == _norm_phone(u["phone"])
        target = mask_phone(u["phone"]) if ok else None
    if not ok:
        register_failure(user_id, "ערוץ לא תואם")
        return None, "הפרטים אינם תואמים לרשומה במערכת."
    return target, None


# ------------------------------------------------------------------ שלב 3
def send_otp(user_id: int, channel: str) -> str:
    """יוצר קוד בן 6 ספרות, שומר רק את הגיבוב שלו, ומחזיר את הקוד לשליחה."""
    ttl = min(db.setting_int("otp_ttl_minutes", 5), 5)   # המסד אוכף מקסימום 5 דקות
    code = "".join(secrets.choice(string.digits) for _ in range(6))
    db.execute("UPDATE users SET otp_hash = :h, otp_channel = :c, "
               "otp_expires_at = now() + make_interval(mins => CAST(:m AS int)), otp_attempts = 0 WHERE id = :id",
               h=hash_secret(code), c=channel, m=ttl, id=user_id)
    db.audit(user_id, "otp_sent", "user", user_id, "נשלח קוד ב-" + ("SMS" if channel == "sms" else "דוא\"ל"))
    return code


def verify_otp(user_id: int, code: str) -> tuple[bool, str | None]:
    u = db.one("SELECT otp_hash, otp_attempts, otp_expires_at < now() AS expired "
               "FROM users WHERE id = :id", id=user_id)
    if not u or not u["otp_hash"]:
        return False, "לא נמצא קוד פעיל. יש לבקש קוד חדש."
    if u["expired"]:
        _clear_otp(user_id)
        return False, "תוקף הקוד פג (5 דקות). יש לבקש קוד חדש."
    if verify_secret(code.strip(), u["otp_hash"]):
        _clear_otp(user_id)                      # קוד חד-פעמי: נמחק מיד אחרי השימוש
        db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = :id", id=user_id)
        db.audit(user_id, "login_success", "user", user_id, None)
        return True, None
    attempts = u["otp_attempts"] + 1
    if attempts >= 3:
        _clear_otp(user_id)
        register_failure(user_id, "קוד אימות שגוי 3 פעמים")
        return False, "הקוד שגוי 3 פעמים. יש לבקש קוד חדש."
    db.execute("UPDATE users SET otp_attempts = :a WHERE id = :id", a=attempts, id=user_id)
    return False, f"הקוד שגוי. נותרו {3 - attempts} ניסיונות."


def _clear_otp(user_id: int) -> None:
    db.execute("UPDATE users SET otp_hash = NULL, otp_channel = NULL, otp_expires_at = NULL, "
               "otp_attempts = 0 WHERE id = :id", id=user_id)


# ------------------------------------------------------------------ אחרי הכניסה
def load_session_user(user_id: int) -> dict:
    user = db.one("SELECT id, username, name, role, job_title, is_external, must_change, "
                  "password_changed_at + make_interval(days => CAST(:d AS int)) < now() AS password_expired, "
                  "(password_changed_at + make_interval(days => CAST(:d AS int)))::date - current_date AS days_to_expiry "
                  "FROM users WHERE id = :id", id=user_id, d=db.setting_int("password_max_age_days", 30))
    # ההרשאות נטענות מטבלת permissions: לפי התפקיד, ועוד הרשאות אישיות שלא פגו
    user["actions"] = {r["action"] for r in db.query(
        "SELECT DISTINCT action FROM permissions WHERE (role = :r OR user_id = :u) "
        "AND document_id IS NULL AND (expires_at IS NULL OR expires_at > now())",
        r=user["role"], u=user_id)}
    return user


def can(user: dict, action: str) -> bool:
    """האם למשתמש יש הרשאה לפעולה (לפי טבלת permissions)."""
    return action in user.get("actions", set())


def password_problems(pw: str) -> list[str]:
    """מדיניות סיסמה: אורך מינימלי, אות גדולה, אות קטנה, ספרה ותו מיוחד."""
    min_len = db.setting_int("password_min_length", 12)
    rules = [
        (len(pw) >= min_len, f"לפחות {min_len} תווים"),
        (re.search(r"[A-Z]", pw), "אות גדולה באנגלית"),
        (re.search(r"[a-z]", pw), "אות קטנה באנגלית"),
        (re.search(r"\d", pw), "ספרה"),
        (re.search(r"[^A-Za-z0-9]", pw), "תו מיוחד (למשל ! או #)"),
    ]
    return [msg for ok, msg in rules if not ok]


def change_password(user_id: int, current: str, new: str) -> str | None:
    """מחליף סיסמה. מחזיר הודעת שגיאה, או None בהצלחה."""
    u = db.one("SELECT password_hash FROM users WHERE id = :id", id=user_id)
    if not verify_secret(current, u["password_hash"]):
        return "הסיסמה הנוכחית שגויה."
    problems = password_problems(new)
    if problems:
        return "הסיסמה החדשה חייבת לכלול: " + ", ".join(problems) + "."
    keep = db.setting_int("password_history_count", 5)
    history = db.query("SELECT password_hash FROM password_history WHERE user_id = :id "
                       "ORDER BY changed_at DESC LIMIT :n", id=user_id, n=keep)
    if verify_secret(new, u["password_hash"]) or any(verify_secret(new, h["password_hash"]) for h in history):
        return f"אי אפשר לחזור על אחת מ-{keep} הסיסמאות האחרונות."
    db.execute("INSERT INTO password_history (user_id, password_hash) VALUES (:id, :h)",
               id=user_id, h=u["password_hash"])
    db.execute("DELETE FROM password_history WHERE user_id = :id AND id NOT IN "
               "(SELECT id FROM password_history WHERE user_id = :id ORDER BY changed_at DESC LIMIT :n)",
               id=user_id, n=keep)
    db.execute("UPDATE users SET password_hash = :h, password_changed_at = now(), must_change = false "
               "WHERE id = :id", h=hash_secret(new), id=user_id)
    db.audit(user_id, "password_changed", "user", user_id, None)
    return None
