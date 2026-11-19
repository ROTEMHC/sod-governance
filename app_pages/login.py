# מסך 1: כניסה מאובטחת בשלושה שלבים (UC-01, UC-26)
import time

import streamlit as st

from board import auth, ui

ui.brand(center=True)

state = st.session_state
step = state.setdefault("login_step", "password")
STEPS = {"password": 1, "channel": 2, "otp": 3}


def reset_login():
    for k in ("login_step", "pending_user", "otp_target", "demo_code", "otp_channel"):
        state.pop(k, None)


_, mid, _ = st.columns([1, 2, 1])
with mid, st.container(border=True):
    st.subheader("כניסה למערכת")
    st.progress(STEPS[step] / 3, text=f"שלב {STEPS[step]} מתוך 3")

    # ---------------------------------------------------------- שלב 1: שם משתמש וסיסמה
    if step == "password":
        with st.form("login_password"):
            username = st.text_input("שם משתמש", autocomplete="username")
            password = st.text_input("סיסמה", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("המשך", type="primary", width="stretch",
                                              icon=":material/login:")
        if submitted:
            user, err = auth.check_password(username, password)
            if err:
                st.error(err)
            else:
                state.pending_user = {"id": user["id"], "name": user["name"]}
                state.login_step = "channel"
                st.rerun()

    # ---------------------------------------------------------- שלב 2: אימות ערוץ
    elif step == "channel":
        st.write(f"שלום {state.pending_user['name']}. לאימות זהותך, הזן/י את הטלפון או הדוא\"ל "
                 "הרשומים במערכת, ונשלח אליהם קוד חד-פעמי.")
        channel = st.segmented_control(
            "לאן לשלוח את הקוד?", ["sms", "email"], required=True, default="sms",
            format_func=lambda c: "SMS לטלפון" if c == "sms" else "דוא\"ל")
        with st.form("login_channel"):
            if channel == "sms":
                # שדה טקסט רגיל: שדה הטלפון של Streamlit מוסיף קידומת של ארה"ב (+1)
                value = st.text_input("מספר הטלפון שלך", placeholder="050-0000000", autocomplete="tel")
            else:
                value = st.text_input("כתובת הדוא\"ל שלך", placeholder="name@company.co.il",
                                      autocomplete="email")
            submitted = st.form_submit_button("שליחת קוד", type="primary", width="stretch",
                                              icon=":material/send:")
        if submitted:
            target, err = auth.check_channel(state.pending_user["id"], channel, value)
            if err:
                st.error(err)
            else:
                state.demo_code = auth.send_otp(state.pending_user["id"], channel)
                state.otp_target, state.otp_channel = target, channel
                state.login_step = "otp"
                st.rerun()
        st.button("חזרה", on_click=reset_login, icon=":material/arrow_forward:")

    # ---------------------------------------------------------- שלב 3: קוד חד-פעמי
    elif step == "otp":
        st.success(f"נשלח קוד בן 6 ספרות אל {state.otp_target}. הקוד תקף 5 דקות.",
                   icon=":material/mark_email_read:")
        st.info(f"הקוד שנשלח: **{state.demo_code}**", title="מצב הדגמה: אין חיבור לשירות SMS",
                icon=":material/science:")
        with st.form("login_otp"):
            code = st.text_input("קוד אימות", max_chars=6, autocomplete="one-time-code")
            submitted = st.form_submit_button("כניסה", type="primary", width="stretch",
                                              icon=":material/verified_user:")
        if submitted:
            ok, err = auth.verify_otp(state.pending_user["id"], code)
            if ok:
                state.user = auth.load_session_user(state.pending_user["id"])
                state.last_activity = time.time()
                reset_login()
                st.rerun()
            else:
                st.error(err)
                if "חדש" in err:
                    state.login_step = "channel"
        with st.container(horizontal=True):
            if st.button("שליחת קוד חדש", icon=":material/refresh:"):
                state.demo_code = auth.send_otp(state.pending_user["id"], state.otp_channel)
                st.rerun()
            st.button("ביטול", on_click=reset_login, icon=":material/close:")

st.caption("הכניסה מאובטחת בשלושה שלבים. כל ניסיון כניסה נרשם ביומן הפעולות.",
           text_alignment="center")
