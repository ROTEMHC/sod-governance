"""שכבת הנתונים: חיבור למסד PostgreSQL ב-Supabase.

החיבור נעשה מצד השרת בלבד, עם הכתובת שבקובץ .streamlit/secrets.toml.
כל השאילתות עם פרמטרים (:name), אף פעם לא בשרשור מחרוזות, כדי למנוע SQL Injection.
"""
import ssl
import threading
import urllib.parse

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


def _open():
    return pg8000.native.Connection(ssl_context=ssl.create_default_context(), timeout=30,
                                    **_connect_params())


def query(sql: str, **params) -> list[dict]:
    """מריץ שאילתה ומחזיר רשימת שורות כ-dict. מתחבר מחדש אם החיבור נפל."""
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
            except (pg8000.exceptions.InterfaceError, OSError, ConnectionError):
                shared["conn"] = None
                if attempt == 2:
                    raise


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
