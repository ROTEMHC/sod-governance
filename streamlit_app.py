"""SOD Governance: מערכת לניהול דירקטוריונים.

הרצה: python -m streamlit run streamlit_app.py
"""
import time

import streamlit as st

from board import auth, db, ui

st.set_page_config(page_title="SOD Governance", page_icon="assets/logo.png", layout="wide")
ui.rtl()

state = st.session_state

# ---------------------------------------------------------------- חיבור למסד
try:
    has_db = "postgres" in st.secrets
except Exception:   # אין קובץ secrets.toml בכלל
    has_db = False
if not has_db:
    ui.brand(center=True)
    st.error("חסר קובץ החיבור למסד הנתונים: .streamlit/secrets.toml. "
             "יש להעתיק את secrets.toml.example ולהדביק את הכתובת מ-Supabase.",
             title="המערכת לא מחוברת למסד", icon=":material/database:")
    st.stop()


def logout(reason: str | None = None):
    if state.get("user"):
        db.audit(state.user["id"], "logout", "user", state.user["id"], reason)
    for k in list(state.keys()):
        del state[k]
    if reason:
        state.logout_reason = reason


# ---------------------------------------------------------------- ניתוק אחרי חוסר פעילות
if state.get("user"):
    timeout = db.setting_int("session_timeout_minutes", 15) * 60
    if time.time() - state.get("last_activity", time.time()) > timeout:
        logout("ניתוק אוטומטי אחרי חוסר פעילות")
    else:
        state.last_activity = time.time()

# ---------------------------------------------------------------- ניווט לפי מצב ותפקיד
if not state.get("user"):
    if state.get("logout_reason"):
        st.toast(state.pop("logout_reason"), icon=":material/logout:")
    page = st.navigation([st.Page("app_pages/login.py", title="כניסה", icon=":material/login:")],
                         position="hidden")
elif state.user["must_change"] or state.user["password_expired"]:
    ui.brand()
    page = st.navigation([st.Page("app_pages/change_password.py", title="החלפת סיסמה",
                                  icon=":material/lock_reset:")], position="hidden")
    st.title("החלפת סיסמה")
else:
    ui.brand()
    if "actions" not in state.user:          # משתמש שנכנס לפני שנוספה טעינת ההרשאות
        state.user = auth.load_session_user(state.user["id"])
    u = state.user
    main_pages = [st.Page("app_pages/home.py", title="המשימות שלי", icon=":material/home:", default=True),
                  st.Page("app_pages/calendar.py", title="היומן שלי", icon=":material/calendar_month:"),
                  st.Page("app_pages/meetings.py", title="ישיבות ופרוטוקולים", icon=":material/event_note:")]
    # כל מסך מוצג רק למי שיש לו הרשאה מתאימה בטבלת permissions
    if auth.can(u, "submit_request") or auth.can(u, "handle_requests") or auth.can(u, "view_requested_reports"):
        main_pages.append(st.Page("app_pages/requests.py", title="בקשות לדוחות", icon=":material/request_quote:"))
    if auth.can(u, "view_dashboard"):
        main_pages.append(st.Page("app_pages/dashboard.py", title="דשבורד כספי", icon=":material/monitoring:"))
        main_pages.append(st.Page("app_pages/agent.py", title="היועץ של סוד (AI)", icon=":material/psychology:"))
    if auth.can(u, "view_audit_log"):
        main_pages.append(st.Page("app_pages/reports.py", title="דוחות בקרה", icon=":material/summarize:"))
    pages = {
        "": main_pages,
        "החשבון שלי": [st.Page("app_pages/change_password.py", title="החלפת סיסמה",
                                icon=":material/lock_reset:")],
    }
    page = st.navigation(pages, position="sidebar")
    ui.topbar(state.user, logout)
    st.title(page.title)

page.run()
