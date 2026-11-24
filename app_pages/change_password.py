# החלפת סיסמה (UC-22): חובה כשהסיסמה פגה או בכניסה הראשונה, ואפשרית בכל עת
import streamlit as st

from board import auth, db

user = st.session_state.user

# אחרי החלפה מוצלחת המסך מתרענן, ולכן ההודעה נשמרת ומוצגת אחרי הרענון. בלי זה המשתמש רואה
# שוב טופס ריק, וחושב שההחלפה נכשלה (תקלה D-07, נמצאה בבדיקה ידנית)
if st.session_state.pop("password_changed", False):
    st.success("הסיסמה הוחלפה בהצלחה. מעכשיו נכנסים עם הסיסמה החדשה.", icon=":material/check_circle:")
    st.page_link("app_pages/advisor.py" if auth.can(st.session_state.user, "advisor_portal") else "app_pages/home.py",
                 label="המשך למערכת", icon=":material/arrow_back:")
    st.stop()

if user["must_change"]:
    st.warning("זו כניסה ראשונה למערכת. יש לבחור סיסמה אישית לפני ההמשך.", icon=":material/key:")
elif user["password_expired"]:
    st.warning("תוקף הסיסמה פג. לפי מדיניות האבטחה יש להחליף סיסמה כל "
               f"{db.setting_int('password_max_age_days', 30)} ימים.", icon=":material/key:")

with st.container(border=True, width=520):
    with st.form("change_password", clear_on_submit=False):
        current = st.text_input("סיסמה נוכחית", type="password", autocomplete="current-password")
        new = st.text_input("סיסמה חדשה", type="password", autocomplete="new-password")
        again = st.text_input("הקלדה חוזרת של הסיסמה החדשה", type="password", autocomplete="new-password")
        submitted = st.form_submit_button("החלפת סיסמה", type="primary", icon=":material/lock_reset:")
    st.caption(f"לפחות {db.setting_int('password_min_length', 12)} תווים, עם אות גדולה, אות קטנה, "
               f"ספרה ותו מיוחד. אי אפשר לחזור על {db.setting_int('password_history_count', 5)} "
               "הסיסמאות האחרונות.")

if submitted:
    if new != again:
        st.error("הסיסמאות החדשות אינן זהות.")
    else:
        err = auth.change_password(user["id"], current, new)
        if err:
            st.error(err)
        else:
            st.session_state.user = auth.load_session_user(user["id"])
            st.session_state.password_changed = True   # ההודעה תוצג אחרי הרענון
            st.rerun()
