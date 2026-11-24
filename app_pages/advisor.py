# מסך: הזימונים שלי (יועץ/ת חיצוני/ת). תצוגה רזה: רק הנושאים שהמזכירות הזמינה אליהם את היועץ/ת,
# ורק בתקופת ההזמנה. לפני צפייה בחומר: הצהרת ניגוד עניינים והתחייבות לסודיות, בחתימה עם קוד חד-פעמי.
import hashlib
import hmac

import streamlit as st

from board import auth, db, ui

user = st.session_state.user
uid = user["id"]

st.caption("כאן מוצגים רק הנושאים שהוזמנת אליהם, ורק עד מועד תפוגת ההזמנה. "
           "החומר מוצג בתוך המערכת בלבד, וכל צפייה נרשמת ביומן הפעולות.")

invites = db.query(
    "SELECT p.expires_at, ai.id AS item_id, ai.title, ai.summary, ai.decision_required, "
    "m.id AS meeting_id, m.title AS meeting, m.meeting_at, m.mode, m.location, m.status, f.name AS forum, "
    "pr.name AS presenter, r.has_conflict, r.conflict_details, r.declared_at "
    "FROM permissions p JOIN agenda_items ai ON ai.id = p.agenda_item_id "
    "JOIN meetings m ON m.id = ai.meeting_id JOIN forums f ON f.id = m.forum_id "
    "LEFT JOIN users pr ON pr.id = ai.presenter_id "
    "LEFT JOIN item_responses r ON r.agenda_item_id = ai.id AND r.user_id = :u "
    "WHERE p.user_id = :u AND p.action = 'advise_item' AND (p.expires_at IS NULL OR p.expires_at > now()) "
    "AND m.status <> 'cancelled' ORDER BY m.meeting_at", u=uid)

if not invites:
    st.info("אין כרגע זימונים פעילים. כשהמזכירות תזמין אותך לנושא, הוא יופיע כאן.",
            icon=":material/event_busy:")
    st.stop()

for inv in invites:
    item = inv["item_id"]
    with ui.card(f"invite-{item}", "navy"):
        st.markdown(f"### {inv['title']}")
        st.caption(f"{inv['forum']}: {inv['meeting']} · {ui.fmt_date(inv['meeting_at'])} · "
                   f"{ui.MODE_HE[inv['mode']]} · {inv['location'] or ''}  \n"
                   f"מציג/ה: {inv['presenter'] or '—'} · **הגישה בתוקף עד {ui.fmt_date(inv['expires_at'])}**")

        # ---- לפני החומר: הצהרת ניגוד עניינים והתחייבות לסודיות
        if not inv["declared_at"]:
            st.warning("לפני הצפייה בחומר יש לחתום על הצהרה.", icon=":material/draw:")
            ans = st.radio("עניין אישי בנושא", ["אין לי עניין אישי בנושא", "יש לי עניין אישי בנושא"],
                           index=None, key=f"adv_coi_{item}")
            details = st.text_input("מהו העניין האישי? (חובה)", key=f"adv_det_{item}") \
                if ans == "יש לי עניין אישי בנושא" else ""
            secret = st.checkbox("אני מתחייב/ת לשמור בסוד את כל המידע שאקבל, לא להעביר אותו לאחרים "
                                 "ולא להזין אותו לכלים חיצוניים", key=f"adv_nda_{item}")
            ready = ans is not None and secret and (ans == "אין לי עניין אישי בנושא" or bool(details.strip()))
            code_key = f"adv_code_{item}"
            if st.button("שליחת קוד לחתימה", key=f"adv_send_{item}", icon=":material/sms:", disabled=not ready):
                st.session_state[code_key] = auth.send_otp(uid, "sms")
            if code_key in st.session_state:
                st.info(f"הקוד שנשלח: **{st.session_state[code_key]}**",
                        title="מצב הדגמה: אין חיבור לשירות SMS", icon=":material/sms:")
                code = st.text_input("קוד החתימה", max_chars=6, key=f"adv_in_{item}")
                if st.button("חתימה", type="primary", key=f"adv_ok_{item}", icon=":material/verified:"):
                    ok, err = auth.verify_otp(uid, code, purpose="advisor_declaration_otp_verified")
                    if not ok:
                        st.error(err)
                    else:
                        conflict = ans == "יש לי עניין אישי בנושא"
                        db.execute("INSERT INTO item_responses (agenda_item_id, user_id, has_conflict, conflict_details) "
                                   "VALUES (:i, :u, :c, :d) ON CONFLICT (agenda_item_id, user_id) DO UPDATE SET "
                                   "has_conflict = EXCLUDED.has_conflict, conflict_details = EXCLUDED.conflict_details, "
                                   "declared_at = now()", i=item, u=uid, c=conflict, d=details.strip() or None)
                        db.audit(uid, "advisor_declaration", "agenda_item", item,
                                 ("עניין אישי: " + details.strip()) if conflict else "אין עניין אישי; התחייבות לסודיות")
                        del st.session_state[code_key]
                        st.rerun()
            continue

        if inv["has_conflict"]:   # עניין אישי: החומר אינו מוצג עד החלטת היו"ר
            st.error(f"הצהרת על עניין אישי בנושא ({inv['conflict_details']}). החומר אינו מוצג עד שהיו\"ר "
                     "או המזכירות יחליטו אם להמשיך את השתתפותך.", icon=":material/block:")
            continue

        # ---- החומר של הנושא בלבד
        if not st.session_state.get(f"adv_logged_{item}"):
            db.audit(uid, "advisor_view_item", "agenda_item", item, inv["title"])
            st.session_state[f"adv_logged_{item}"] = True
        if inv["summary"]:
            st.markdown(f"**תקציר:** {inv['summary']}")
        if inv["decision_required"]:
            st.markdown(f"**ההחלטה הנדרשת:** {inv['decision_required']}")
        docs = db.query("SELECT filename, doc_type, classification, uploaded_at, content_sha256 FROM documents "
                        "WHERE agenda_item_id = :i AND doc_type IN ('meeting_material', 'requested_report', 'field_check') "
                        "ORDER BY uploaded_at", i=item)
        TYPE_HE = {"meeting_material": "חומר ישיבה", "requested_report": "דוח שהתבקש", "field_check": "ממצאי בדיקת שטח"}
        ui.table([{"file": d["filename"], "type": TYPE_HE[d["doc_type"]], "when": ui.fmt_date(d["uploaded_at"])}
                  for d in docs], {"file": "מסמך", "type": "סוג", "when": "הועלה"},
                 empty="עדיין לא הועלה חומר לנושא.")

        # ---- השתתפות מרחוק: רק אחרי סיסמה וקוד, כמו לכל משתתף
        if inv["mode"] in ("remote", "hybrid") and inv["status"] == "scheduled":
            room_key = f"adv_room_{item}"
            if st.session_state.get(room_key):
                st.link_button("כניסה לחדר הישיבה", st.session_state[room_key], icon=":material/videocam:", type="primary")
            else:
                with st.expander("הצטרפות מרחוק", icon=":material/videocam:"):
                    pw = st.text_input("הסיסמה שלך במערכת", type="password", key=f"adv_pw_{item}")
                    jkey = f"adv_join_code_{item}"
                    if jkey not in st.session_state and st.button("אימות ושליחת קוד", key=f"adv_pw_ok_{item}"):
                        ok_user, err = auth.check_password(user["username"], pw)
                        if ok_user:
                            st.session_state[jkey] = auth.send_otp(uid, "sms")
                            st.rerun()
                        else:
                            st.error(err)
                    if jkey in st.session_state:
                        st.info(f"הקוד שנשלח: **{st.session_state[jkey]}**",
                                title="מצב הדגמה: אין חיבור לשירות SMS", icon=":material/sms:")
                        code = st.text_input("קוד אימות", max_chars=6, key=f"adv_join_in_{item}")
                        if st.button("אימות וכניסה", key=f"adv_join_ok_{item}"):
                            ok, err = auth.verify_otp(uid, code, purpose="remote_join_verified")
                            if ok:
                                key = (st.secrets.get("video", {}).get("secret") or st.secrets["postgres"]["url"]).encode()
                                room = hmac.new(key, f"meeting-{inv['meeting_id']}".encode(), hashlib.sha256).hexdigest()[:20]
                                st.session_state[room_key] = f"https://meet.jit.si/SOD-{room}"
                                del st.session_state[jkey]
                                db.audit(uid, "remote_join", "meeting", inv["meeting_id"], "יועץ/ת חיצוני/ת, אחרי סיסמה וקוד")
                                st.rerun()
                            else:
                                st.error(err)

st.caption("זקוק/ה לחומר נוסף? פנה/י למזכירות החברה. אין אפשרות להוריד מסמכים או לשתף אותם מחוץ למערכת.")
