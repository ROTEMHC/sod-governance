# מסך 2: דף הבית "המשימות שלי" (UC-17). דף אחד לכולם, והתוכן משתנה לפי התפקיד.
import streamlit as st

from board import auth, db, ui

user = st.session_state.user
uid, role = user["id"], user["role"]
sees_all_meetings = role in ("admin", "secretary", "chair")

if user["days_to_expiry"] is not None and 0 <= user["days_to_expiry"] <= 5:
    st.warning(f"הסיסמה שלך תפוג בעוד {user['days_to_expiry']} ימים.", icon=":material/key:")

# ---------------------------------------------------------------- נתונים
if sees_all_meetings:
    meetings = db.query(
        "SELECT m.id, m.meeting_at, f.name AS forum, m.title, m.status, m.mode, "
        "m.materials_distributed_at IS NOT NULL AS distributed, "
        "(SELECT count(*) FROM attendance a WHERE a.meeting_id = m.id AND a.declaration_signed_at IS NULL "
        " AND a.declaration_sent_at IS NOT NULL) AS unsigned "
        "FROM meetings m JOIN forums f ON f.id = m.forum_id "
        "WHERE m.status IN ('proposed','scheduled') AND m.meeting_at >= now() ORDER BY m.meeting_at")
else:
    meetings = db.query(
        "SELECT m.id, m.meeting_at, p.forum, p.title, m.status, m.mode, p.rsvp, p.is_forum_member, "
        "p.declaration_signed_at, a.declaration_sent_at "
        "FROM v_meeting_participants p JOIN meetings m ON m.id = p.meeting_id "
        "LEFT JOIN attendance a ON a.meeting_id = p.meeting_id AND a.user_id = p.user_id "
        "WHERE p.user_id = :u AND m.status IN ('proposed','scheduled') AND m.meeting_at >= now() "
        "ORDER BY m.meeting_at", u=uid)

# כל ישיבה קרובה (שנקבעה) שהמשתמש משתתף בה ועוד לא חתם בה על טופס ההצהרה
to_sign = db.query(
    "SELECT m.id, m.meeting_at, p.forum, p.title FROM v_meeting_participants p JOIN meetings m ON m.id = p.meeting_id "
    "WHERE p.user_id = :u AND p.declaration_signed_at IS NULL AND m.status = 'scheduled' AND m.meeting_at >= now() "
    "ORDER BY m.meeting_at", u=uid) if auth.can(user, "sign_declaration") else []

reminders = db.query(
    "SELECT id, severity, message, created_at FROM reminders WHERE user_id = :u AND read_at IS NULL "
    "ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, created_at DESC",
    u=uid)

my_decisions = db.query(
    "SELECT d.id, d.text, d.due_date, d.status, d.due_date < current_date AS overdue "
    "FROM decisions d WHERE d.owner_id = :u AND d.status <> 'done' ORDER BY d.due_date", u=uid)

if role == "cfo":
    requests = db.query(
        "SELECT r.id, r.title, u.name AS requester, r.due_date, r.status, r.due_date < current_date AS overdue "
        "FROM document_requests r JOIN users u ON u.id = r.requested_by "
        "WHERE r.assigned_to = :u AND r.status IN ('open','in_progress') ORDER BY r.due_date", u=uid)
    requests_label = "בקשות שממתינות לטיפולך"
else:
    requests = db.query(
        "SELECT r.id, r.title, r.due_date, r.status, r.due_date < current_date AS overdue "
        "FROM document_requests r WHERE r.requested_by = :u ORDER BY r.requested_at DESC", u=uid)
    requests_label = "הבקשות שלי לדוחות"

# ---------------------------------------------------------------- כותרת ומדדים
role_he = ui.ROLE_HE[role]
job = user["job_title"]
st.subheader(f"שלום, {user['name']}")
st.caption(job if job and job != role_he else role_he)

open_requests = sum(1 for r in requests if r["status"] in ("open", "in_progress"))
with st.container(horizontal=True):
    ui.kpi("meetings", "ישיבות קרובות", len(meetings), ":material/event:")
    ui.kpi("sign", "טפסי הצהרה לחתימה", len(to_sign), ":material/draw:", alert=bool(to_sign))
    ui.kpi("reminders", "תזכורות פתוחות", len(reminders), ":material/notifications:",
           alert=any(r["severity"] == "critical" for r in reminders))
    ui.kpi("requests", requests_label, open_requests, ":material/request_quote:",
           alert=any(r["overdue"] and r["status"] in ("open", "in_progress") for r in requests))

# ---------------------------------------------------------------- טפסים לחתימה (הכי דחוף)
if to_sign:
    with ui.card("to-sign", "red"):
        st.markdown("**:material/draw: טפסי הצהרת ניגוד עניינים שממתינים לחתימתך**")
        st.caption("כל עוד הטופס לא נחתם, לא ניתן להצביע בישיבה, ותישלח תזכורת כל יום.")
        for f in to_sign:
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f":material/assignment_late: **{f['forum']}: {f['title']}** · {ui.fmt_date(f['meeting_at'])}")
                if st.button("לחתימה על הטופס", key=f"sign_go_{f['id']}", icon=":material/draw:", type="primary"):
                    st.session_state["sign_open"] = f["id"]
                    st.switch_page("app_pages/calendar.py")

# ---------------------------------------------------------------- ישיבות ותזכורות
right, left = st.columns([3, 2])   # בעברית העמודה הראשונה מוצגת מימין
with right, ui.card("meetings", "navy"):
    st.markdown("**:material/event: ישיבות קרובות**")
    rows = []
    for m in meetings:
        row = {"date": ui.fmt_date(m["meeting_at"]), "forum": m["forum"], "title": m["title"],
               "status": ui.STATUS_HE[m["status"]], "mode": ui.MODE_HE[m["mode"]]}
        if sees_all_meetings:
            row["distributed"] = "הופץ" if m["distributed"] else "טרם הופץ"
            row["unsigned"] = m["unsigned"]
        else:
            row["rsvp"] = ui.RSVP_HE.get(m["rsvp"])
            row["declaration"] = ("נחתם" if m["declaration_signed_at"] else
                                  "" if m["status"] == "proposed" else "ממתין לחתימה")
        rows.append(row)
    cols = {"date": "מועד", "forum": "פורום", "title": "ישיבה", "status": "מצב", "mode": "אופן"}
    cols.update({"distributed": "חומר", "unsigned": "טרם חתמו"} if sees_all_meetings
                else {"rsvp": "אישור הגעה", "declaration": "טופס הצהרה"})
    ui.table(rows, cols, empty="אין ישיבות קרובות.")

with left, ui.card("reminders", "gold"):
    st.markdown("**:material/notifications: תזכורות**")
    if not reminders:
        st.caption("אין תזכורות פתוחות.")
    for r in reminders:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"{ui.SEVERITY_ICON[r['severity']]} {r['message']}  \n"
                        f":gray[{ui.fmt_date(r['created_at'])}]")
            if st.button("נקרא", key=f"read_{r['id']}", type="tertiary", icon=":material/done:"):
                db.execute("UPDATE reminders SET read_at = now() WHERE id = :id AND user_id = :u",
                           id=r["id"], u=uid)
                st.rerun()

# ---------------------------------------------------------------- החלטות ובקשות
c1, c2 = st.columns(2)
with c1, ui.card("decisions"):
    st.markdown("**:material/task_alt: החלטות באחריותי**")
    ui.table([{"text": d["text"], "due": ui.fmt_date(d["due_date"]),
               "status": ("באיחור" if d["overdue"] else {"open": "פתוחה", "in_progress": "בביצוע"}[d["status"]])}
              for d in my_decisions],
             {"text": "החלטה", "due": "מועד", "status": "מצב"}, empty="אין החלטות פתוחות באחריותך.")
with c2, ui.card("requests"):
    st.markdown(f"**:material/request_quote: {requests_label}**")
    status_he = {"open": "פתוחה", "in_progress": "בטיפול", "fulfilled": "נשלחה", "rejected": "נדחתה"}
    rows = [{"title": r["title"], "who": r.get("requester", ""), "due": ui.fmt_date(r["due_date"]),
             "status": "באיחור" if r["overdue"] and r["status"] in ("open", "in_progress")
             else status_he[r["status"]]} for r in requests]
    cols = {"title": "בקשה", "due": "מועד מענה", "status": "מצב"}
    if role == "cfo":
        cols = {"title": "בקשה", "who": "מבקש/ת", "due": "מועד מענה", "status": "מצב"}
    ui.table(rows, cols, empty="אין בקשות.")

