"""רכיבי ממשק משותפים: כיוון מימין לשמאל, כותרת עם הלוגו, ופורמטים בעברית."""
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "assets" / "logo.png"
LOGO_TAGLINE = ROOT / "assets" / "logo_tagline.png"
TAGLINE = "בסוד ישרים ועדה"

ROLE_HE = {
    "admin": "מנהל/ת מערכות מידע", "secretary": "מזכיר/ת החברה", "chair": "יו\"ר הדירקטוריון",
    "director": "דירקטור/ית", "cfo": "סמנכ\"ל/ית כספים", "management": "הנהלה",
}
RSVP_HE = {"yes": "מגיע/ה", "no": "לא מגיע/ה", "remote": "מרחוק", None: "טרם אישר/ה"}
STATUS_HE = {"proposed": "מועד מוצע", "scheduled": "מתוכננת", "held": "התקיימה",
             "closed": "נסגרה", "cancelled": "בוטלה"}
MODE_HE = {"physical": "פיזית", "remote": "מרחוק", "hybrid": "משולבת"}
SEVERITY_ICON = {"critical": ":material/error:", "warning": ":material/warning:", "info": ":material/info:"}


def rtl() -> None:
    """Streamlit אינו תומך בעברית מימין לשמאל, ולכן נדרש CSS מינימלי לכיוון הטקסט."""
    st.html("""<style>
    .stApp, [data-testid="stSidebar"], [data-testid="stHeader"] { direction: rtl; }
    [data-testid="stDataFrame"], [data-testid="stTable"] { direction: ltr; }
    input, textarea { direction: rtl; text-align: right; }
    </style>""")


def brand(center: bool = False) -> None:
    """הלוגו והסלוגן בראש העמוד."""
    if center:
        _, mid, _ = st.columns([1, 2, 1])
        with mid:
            # הלוגו והסלוגן בתמונה אחת, כדי שהסלוגן יהיה צמוד ללוגו
            st.image(str(LOGO_TAGLINE), width="stretch", alt=f"SOD Governance, {TAGLINE}")
    else:
        st.logo(str(LOGO), size="large")
        st.sidebar.markdown(f"**:orange[{TAGLINE}]**", text_alignment="center")


def fmt_date(d) -> str:
    if d is None:
        return ""
    if isinstance(d, datetime):
        return d.strftime("%d/%m/%Y %H:%M")
    if isinstance(d, date):
        return d.strftime("%d/%m/%Y")
    return str(d)


def table(rows: list[dict], columns: dict[str, str], *, alt: str, height="auto") -> None:
    """מציג טבלה בעברית: העמודה הראשונה מוצגת בצד ימין, כמו בטבלה עברית רגילה."""
    if not rows:
        st.caption("אין נתונים להצגה.")
        return
    df = pd.DataFrame(rows)[list(columns)].rename(columns=columns)
    df = df[df.columns[::-1]]   # היפוך הסדר: הטבלה עצמה נכתבת משמאל לימין
    st.dataframe(df, hide_index=True, width="stretch", height=height, alt=alt)
