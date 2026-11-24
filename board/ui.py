"""רכיבי ממשק משותפים: עברית מימין לשמאל, צבעי המותג, כרטיסים, טבלאות ותגיות מצב."""
import re
from datetime import date, datetime, timedelta, timezone
from html import escape
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "assets" / "logo.png"
LOGO_TAGLINE = ROOT / "assets" / "logo_tagline.png"
TAGLINE = "בסוד ישרים ועדה"

# צבעי המותג, לפי הלוגו
NAVY, TEAL, GOLD = "#1F3864", "#14857A", "#B8901E"

ROLE_HE = {
    "admin": "מנהל/ת מערכות מידע", "secretary": "מזכיר/ת החברה", "chair": "יו\"ר הדירקטוריון",
    "director": "דירקטור/ית", "cfo": "סמנכ\"ל/ית כספים", "management": "הנהלה",
    "advisor": "יועץ/ת חיצוני/ת",
}
RSVP_HE = {"yes": "מגיע/ה", "no": "לא מגיע/ה", "remote": "מרחוק", None: "טרם אישר/ה"}
STATUS_HE = {"proposed": "מועד מוצע", "scheduled": "מתוכננת", "held": "התקיימה",
             "closed": "נסגרה", "cancelled": "בוטלה"}
MODE_HE = {"physical": "פיזית", "remote": "מרחוק", "hybrid": "משולבת"}
SEVERITY_ICON = {"critical": ":material/error:", "warning": ":material/warning:", "info": ":material/info:"}

# צבע התגית לפי הערך: ירוק = תקין, צהוב = ממתין, אדום = דורש טיפול
BADGE = {
    "ok": {"הופץ", "נחתם", "מגיע/ה", "מרחוק", "נכח/ה", "בתוקף", "בוצעה", "נשלחה", "מוצדקת", "מתוכננת", "התקיימה"},
    "wait": {"טרם אישר/ה", "טרם נשלח", "פתוחה", "בטיפול", "בביצוע", "מועד מוצע", "ממתין להחלטת היו\"ר"},
    "bad": {"טרם הופץ", "באיחור", "נעדר/ה", "עניין אישי", "ממתין לחתימה", "לא מגיע/ה", "נדחתה", "לא מוצדקת", "חסרה סיבת היעדרות"},
}


def rtl() -> None:
    """עברית מימין לשמאל וצבעי המותג. Streamlit אינו תומך בכיוון מימין לשמאל, ולכן נדרש CSS."""
    st.html(f"""<style>
    .stApp, [data-testid="stSidebar"], [data-testid="stHeader"] {{ direction: rtl; }}
    .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp p, .stApp li, .stApp label,
    [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"],
    [data-testid="stMetricLabel"], [data-testid="stMetricValue"], [data-testid="stAlertContainer"] {{
        text-align: right !important; }}
    input, textarea {{ direction: rtl; text-align: right; }}

    /* כותרות בכחול המותג */
    .stApp h1, .stApp h2, .stApp h3 {{ color: {NAVY} !important; }}

    /* כרטיסים: רקע בהיר ופס צבע עליון */
    [class*="st-key-card"] {{ background: #F7FAFD; border-top: 4px solid {TEAL} !important; }}
    [class*="st-key-card-gold"] {{ border-top-color: {GOLD} !important; }}
    [class*="st-key-card-navy"] {{ border-top-color: {NAVY} !important; }}
    [class*="st-key-card-red"] {{ border-top-color: #C0392B !important; background: #FFF8F7; }}

    /* לוגו גדול בראש התפריט */
    /* רק בתפריט הצד; בשורה העליונה הצרה הלוגו נשאר בגודל הרגיל, כדי שלא ייחתך */
    [data-testid="stSidebarLogo"] {{ height: 96px !important; max-height: 96px !important;
        width: auto !important; max-width: 100% !important; }}
    [data-testid="stSidebarHeader"] {{ height: auto !important; padding-top: 18px; padding-bottom: 6px; }}

    /* תפריט הפרופיל: קבוע בפינה השמאלית העליונה של המסך */
    .st-key-topbar {{ position: fixed; top: 10px; left: 18px; right: auto; z-index: 999990;
        width: max-content !important; max-width: 40vw; }}
    .st-key-topbar * {{ width: max-content !important; white-space: nowrap; overflow: visible !important; }}
    .st-key-topbar button p {{ font-weight: 600; color: {NAVY}; }}
    .st-key-topbar [data-testid="stIconMaterial"] {{ font-size: 1.7rem; color: {NAVY}; }}
    /* החלפת סיסמה נמצאת בתפריט הפרופיל, ולא בתפריט הצד */
    [data-testid="stSidebarNav"] li:has(a[href$="change_password"]) {{ display: none; }}

    /* מדדים בראש הדף */
    [class*="st-key-kpi"] {{ background: linear-gradient(135deg, {NAVY} 0%, #2E5597 100%);
        border-radius: 12px; padding: 14px 18px; }}
    [class*="st-key-kpi"] [data-testid="stMetricLabel"] p,
    [class*="st-key-kpi"] [data-testid="stMetricLabel"] span {{ color: #DCE6F5 !important; }}
    [class*="st-key-kpi"] [data-testid="stMetricValue"] {{ color: #FFFFFF !important; }}
    [class*="st-key-kpi-alert"] {{ background: linear-gradient(135deg, {GOLD} 0%, #D4AF37 100%); }}

    /* טבלאות בעברית */
    table.sod {{ width: 100%; border-collapse: collapse; direction: rtl; font-size: 0.92rem; }}
    table.sod th {{ background: {NAVY}; color: #fff; text-align: right; padding: 8px 10px;
        font-weight: 600; }}
    table.sod td {{ text-align: right; padding: 7px 10px; border-bottom: 1px solid #E3E8F0; }}
    table.sod tr:nth-child(even) td {{ background: #F4F7FB; }}
    .badge {{ display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.82rem;
        font-weight: 600; white-space: nowrap; }}
    .badge.ok {{ background: #E3F4EF; color: #0F6B5F; }}
    .badge.wait {{ background: #FDF3D7; color: #8A6A0E; }}
    .badge.bad {{ background: #FBE3E0; color: #A42A1E; }}
    .badge.num {{ background: #FBE3E0; color: #A42A1E; }}
    .note {{ color: {TEAL}; border-bottom: 1px dotted {TEAL}; cursor: help; position: relative; outline: none; }}
    /* חלונית הביאור: נפתחת מיד במעבר עכבר או בלחיצה (גם בטלפון) */
    .note .tip {{ display: none; position: absolute; z-index: 1000; top: 130%; left: 0; width: 340px;
        max-width: 80vw; background: {NAVY}; color: #fff; padding: 10px 12px; border-radius: 8px;
        font-size: 0.85rem; line-height: 1.5; font-weight: 400; text-align: right; direction: rtl;
        white-space: normal; box-shadow: 0 6px 18px rgba(0,0,0,.25); border-top: 3px solid {GOLD}; }}
    .note:hover .tip, .note:focus .tip {{ display: block; }}
    table.sod, [data-testid="stHtml"] {{ overflow: visible !important; }}
    table.sod td.num {{ direction: ltr; text-align: right; }}
    </style>""")


def brand(center: bool = False) -> None:
    """הלוגו והסלוגן בראש העמוד."""
    if center:
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            # הלוגו והסלוגן בתמונה אחת, כדי שהסלוגן יהיה צמוד ללוגו
            st.image(str(LOGO_TAGLINE), width="stretch", alt=f"SOD Governance, {TAGLINE}")
    else:
        # בראש התפריט, בגדול: הלוגו עם הסלוגן (הגודל נקבע ב-CSS שב-rtl)
        st.logo(str(LOGO_TAGLINE), size="large", icon_image=str(LOGO))


def topbar(user: dict, on_logout, password_page) -> None:
    """תפריט הפרופיל: אייקון ושם בפינה השמאלית העליונה של המסך. בלחיצה: החלפת סיסמה והתנתקות."""
    with st.container(key="topbar"):
        with st.popover(user["name"], icon=":material/account_circle:", type="tertiary"):
            st.markdown(f"**{user['name']}**  \n:gray[{ROLE_HE[user['role']]}]")
            st.page_link(password_page, label="החלפת סיסמה", icon=":material/lock_reset:")
            st.button("התנתקות", on_click=on_logout, icon=":material/logout:", type="tertiary", key="logout_btn")


def section_menu(options: list[str], key: str) -> str:
    """מעבר בין חלקי המסך: כפתורים לרוחב, ורק החלק שנבחר מוצג."""
    return st.segmented_control(key, options, default=options[0], required=True, key=key,
                                label_visibility="collapsed")


def card(name: str, color: str = "teal"):
    """כרטיס עם רקע בהיר ופס צבע עליון. color: teal / gold / navy / red."""
    suffix = "" if color == "teal" else f"-{color}"
    return st.container(border=True, key=f"card{suffix}-{name}")


def kpi(name: str, label: str, value, icon: str, alert: bool = False) -> None:
    """מדד בראש הדף, על רקע בצבע המותג. alert=True מדגיש בזהב מדד שדורש טיפול."""
    with st.container(key=f"kpi{'-alert' if alert else ''}-{name}"):
        st.metric(label, value, icon=icon)


def israel_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Jerusalem")
    except Exception:   # אין מסד אזורי זמן במחשב: שעון חורף של ישראל
        return timezone(timedelta(hours=2))


def local(d: datetime) -> datetime:
    """שעה לפי שעון ישראל. המסד שומר שעות ב-UTC, והשרת בענן רץ ב-UTC."""
    return d if d.tzinfo is None else d.astimezone(israel_tz())


def fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return local(d).strftime("%d/%m/%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    return str(d)


def _cell(value) -> str:
    if isinstance(value, dict):   # ערך עם הסבר שמופיע במעבר עכבר (למשל תמצית ביאור)
        return (f'<span class="note" tabindex="0">{escape(value["text"])} ⓘ'
                f'<span class="tip">{escape(value["tip"])}</span></span>')
    text = "" if value is None else str(value)
    for kind, words in BADGE.items():
        if text in words:
            return f'<span class="badge {kind}">{escape(text)}</span>'
    if isinstance(value, int) and value > 0 and not isinstance(value, bool):
        return f'<span class="badge num">{value}</span>'
    if re.fullmatch(r"[+\-−]?[\d,.]+%?", text):   # מספר או אחוז: נשמר בסדר משמאל לימין (‎+6.19%)
        return f'<bdi dir="ltr">{escape(text)}</bdi>'
    return escape(text)


def table(rows: list[dict], columns: dict[str, str], *, empty: str = "אין נתונים להצגה.") -> None:
    """טבלה בעברית מימין לשמאל, עם תגיות צבע לערכי מצב (ירוק, צהוב, אדום)."""
    if not rows:
        st.caption(empty)
        return
    head = "".join(f"<th>{escape(h)}</th>" for h in columns.values())
    body = "".join("<tr>" + "".join(f"<td>{_cell(r.get(k))}</td>" for k in columns) + "</tr>"
                   for r in rows)
    st.html(f'<table class="sod"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')
