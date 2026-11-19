# מסך 2: דף הבית "המשימות שלי" (UC-17). דף אחד לכולם, והתוכן משתנה לפי התפקיד.
import streamlit as st

from board import db, ui

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

to_sign = db.query(
    "SELECT m.id, m.meeting_at, f.name AS forum, m.title, a.declaration_sent_at "
    "FROM attendance a JOIN meetings m ON m.id = a.meeting_id JOIN forums f ON f.id = m.forum_id "
    "WHERE a.user_id = :u AND a.declaration_sent_at IS NOT NULL AND a.declaration_signed_at IS NULL "
    "AND m.meeting_at >= now() ORDER BY m.meeting_at", u=uid)

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
st.subheader(f"שלום, {user['name']}")
st.caption(f"{user['job_title'] or ui.ROLE_HE[role]}  ·  {ui.ROLE_HE[role]}")

with st.container(horizontal=True):
    st.metric("ישיבות קרובות", len(meetings), border=True, icon=":material/event:")
    st.metric("טפסי הצהרה לחתימה", len(to_sign), border=True, icon=":material/draw:")
    st.metric("תזכורות פתוחות", len(reminders), border=True, icon=":material/notifications:")
    st.metric(requests_label, sum(1 for r in requests if r["status"] in ("open", "in_progress")),
              border=True, icon=":material/request_quote:")

# ---------------------------------------------------------------- טפסים לחתימה (הכי דחוף)
if to_sign:
    with st.container(border=True):
        st.markdown("**:material/draw: טפסי הצהרת ניגוד עניינים שממתינים לחתימתך**")
        for f in to_sign:
            st.warning(f"{f['forum']}: \"{f['title']}\", {ui.fmt_date(f['meeting_at'])}. "
                       "כל עוד הטופס לא נחתם, לא ניתן להצביע בישיבה, ותישלח תזכורת כל יום.",
                       icon=":material/assignment_late:")

# ---------------------------------------------------------------- תזכורות
left, right = st.columns([3, 2])
with right, st.container(border=True):
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

# ---------------------------------------------------------------- ישיבות
with left, st.container(border=True):
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
                                  "ממתין לחתימה" if m["declaration_sent_at"] else "טרם נשלח")
        rows.append(row)
    cols = {"date": "מועד", "forum": "פורום", "title": "ישיבה", "status": "מצב", "mode": "אופן"}
    cols.update({"distributed": "חומר", "unsigned": "טרם חתמו"} if sees_all_meetings
                else {"rsvp": "אישור הגעה", "declaration": "טופס הצהרה"})
    ui.table(rows, cols, alt="ישיבות קרובות")

# ---------------------------------------------------------------- החלטות ובקשות
c1, c2 = st.columns(2)
with c1, st.container(border=True):
    st.markdown("**:material/task_alt: החלטות באחריותי**")
    ui.table([{"text": d["text"], "due": ui.fmt_date(d["due_date"]),
               "status": ("באיחור" if d["overdue"] else {"open": "פתוחה", "in_progress": "בביצוע"}[d["status"]])}
              for d in my_decisions],
             {"text": "החלטה", "due": "מועד", "status": "מצב"}, alt="החלטות באחריותי")
with c2, st.container(border=True):
    st.markdown(f"**:material/request_quote: {requests_label}**")
    status_he = {"open": "פתוחה", "in_progress": "בטיפול", "fulfilled": "נשלחה", "rejected": "נדחתה"}
    rows = [{"title": r["title"], "who": r.get("requester", ""), "due": ui.fmt_date(r["due_date"]),
             "status": "באיחור" if r["overdue"] and r["status"] in ("open", "in_progress")
             else status_he[r["status"]]} for r in requests]
    cols = {"title": "בקשה", "due": "מועד מענה", "status": "מצב"}
    if role == "cfo":
        cols = {"title": "בקשה", "who": "מבקש/ת", "due": "מועד מענה", "status": "מצב"}
    ui.table(rows, cols, alt=requests_label)
