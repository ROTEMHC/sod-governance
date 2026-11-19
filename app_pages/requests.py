# מסך 6: בקשות לדוחות (UC-23, UC-24, UC-25)
# דירקטור, יו"ר או מנכ"ל מבקשים דוח. סמנכ"ל הכספים מטפל בבקשה ושולח את הדוח מתוך המערכת,
# והדוח מוצג לכל חברי הפורום של הישיבה, לא רק למבקש ("בקשה אחת, כולם רואים").
from datetime import date, timedelta

import streamlit as st

from board import auth, db, ui

user = st.session_state.user
uid = user["id"]
can_submit = auth.can(user, "submit_request")
can_handle = auth.can(user, "handle_requests")
can_view_all = auth.can(user, "view_requested_reports") and user["role"] in ("admin", "cfo", "chair", "management")

# דוחות שדירקטורים מבקשים בדרך כלל. אפשר גם להקליד דוח אחר.
REPORT_TYPES = [
    "דוח גיול לקוחות", "דוח הרכב מלאי וגיול מלאי", "דוח קניות לפי ספק", "תחזית תזרים מזומנים",
    "דוח רווחיות לפי סניף", "דוח רווחיות לפי מגזר", "פירוט הוצאות מכירה ושיווק",
    "פירוט הוצאות מימון", "דוח שכר ומצבת עובדים", "דוח חובות מסופקים", "תקציב מול ביצוע",
]

STATUS_HE = {"open": "פתוחה", "in_progress": "בטיפול", "fulfilled": "נשלחה", "rejected": "נדחתה"}
SOURCE_HE = {"priority": "Priority", "upload": "העלאה ידנית", None: ""}


def add_business_days(start: date, days: int) -> date:
    """ימי עבודה בישראל: ראשון עד חמישי (שישי ושבת אינם נספרים)."""
    d = start
    while days > 0:
        d += timedelta(days=1)
        if d.weekday() not in (4, 5):     # 4 = שישי, 5 = שבת
            days -= 1
    return d


def notify(user_id, rule, severity, message, related_type, related_id, key):
    db.execute("INSERT INTO reminders (user_id, rule, severity, message, related_type, related_id, dedupe_key, channel) "
               "VALUES (:u, :r, :s, :m, :t, :i, :k, 'app') ON CONFLICT (dedupe_key) DO NOTHING",
               u=user_id, r=rule, s=severity, m=message, t=related_type, i=related_id, k=key)


def status_label(r) -> str:
    if r["status"] in ("open", "in_progress") and r["overdue"]:
        return "באיחור"
    return STATUS_HE[r["status"]]


tabs = []
if can_submit:
    tabs.append("בקשה חדשה")
if can_handle:
    tabs.append("תור הטיפול שלי")
tabs.append("דוחות שהתבקשו")
if can_submit:
    tabs.append("הבקשות שלי")
view = ui.side_menu(tabs, key="requests_view")

# ================================================================ בקשה חדשה (UC-23)
if view == "בקשה חדשה":
    if user["role"] in ("admin", "secretary", "chair", "management", "cfo"):
        meetings = db.query("SELECT m.id, m.title, f.name AS forum, m.meeting_at FROM meetings m "
                            "JOIN forums f ON f.id = m.forum_id WHERE m.status = 'scheduled' "
                            "AND m.meeting_at >= now() ORDER BY m.meeting_at")
    else:
        meetings = db.query("SELECT p.meeting_id AS id, p.title, p.forum, m.meeting_at "
                            "FROM v_meeting_participants p JOIN meetings m ON m.id = p.meeting_id "
                            "WHERE p.user_id = :u AND m.status = 'scheduled' AND m.meeting_at >= now() "
                            "ORDER BY m.meeting_at", u=uid)
    cfo = db.one("SELECT id, name FROM users WHERE role = 'cfo' AND active ORDER BY id LIMIT 1")
    due = add_business_days(date.today(), db.setting_int("request_due_default_days", 5))

    with ui.card("new-request"):
        st.markdown("**:material/add_circle: בקשה לדוח או למסמך שאינו זמין לך**")
        st.caption(f"הבקשה תנותב ל{cfo['name']} (סמנכ\"ל הכספים), עם מועד מענה {ui.fmt_date(due)} "
                   "(5 ימי עבודה). הדוח שיישלח יוצג לכל חברי הפורום של הישיבה.")
        if "request_done" in st.session_state:   # אחרי שליחה: הודעת אישור וניקוי שם הדוח
            st.success(st.session_state.pop("request_done"), icon=":material/check_circle:")
            st.session_state.pop("req_title", None)
        # שם הדוח וסוג התקופה מחוץ לטופס, כדי ששדות התקופה יתחלפו מיד לפי הבחירה
        title = st.selectbox(
            "איזה דוח או מסמך?", REPORT_TYPES, index=None, accept_new_options=True, key="req_title",
            placeholder="בחירה מהרשימה, או הקלדת שם של דוח אחר")
        period_kind = st.segmented_control("לאיזו תקופה?", ["רבעון", "שנה", "טווח תאריכים"],
                                           default="רבעון", required=True)
        today = date.today()
        years = list(range(today.year, today.year - 5, -1))
        with st.form("new_request", clear_on_submit=True):
            if period_kind == "רבעון":
                q_col, y_col = st.columns(2)
                quarter = q_col.selectbox("רבעון", [1, 2, 3, 4], index=(today.month - 1) // 3,
                                          format_func=lambda q: f"רבעון {q}")
                year = y_col.selectbox("שנה", years)
                period = f"רבעון {quarter}, {year}"
            elif period_kind == "שנה":
                year = st.selectbox("שנה", years)
                period = f"שנת {year}"
            else:
                rng = st.date_input("מתאריך עד תאריך", value=(date(today.year, 1, 1), today),
                                    max_value=today, format="DD/MM/YYYY")
                period = (f"{rng[0]:%d/%m/%Y}–{rng[1]:%d/%m/%Y}"
                          if isinstance(rng, tuple) and len(rng) == 2 else "")
            meeting_id = st.selectbox(
                "לקראת איזו ישיבה?", [None] + [m["id"] for m in meetings],
                format_func=lambda i: "לא קשור לישיבה מסוימת" if i is None else next(
                    f"{m['forum']}: {m['title']} ({ui.fmt_date(m['meeting_at'])})" for m in meetings if m["id"] == i))
            reason = st.text_area("למה הדוח נחוץ? (חובה)",
                                  placeholder="למשל: הלקוחות גדלו מהר מהמכירות, ונדרש לבדוק את איכות הגבייה לפני אישור הדוחות.")
            sent = st.form_submit_button("שליחת הבקשה", type="primary", icon=":material/send:")
        if sent:
            title = (title or "").strip()
            if not title or not reason.strip():
                st.error("חובה לבחור דוח ולמלא נימוק.")
            elif not period:
                st.error("יש לבחור תאריך התחלה ותאריך סיום.")
            else:
                row = db.one("INSERT INTO document_requests (requested_by, assigned_to, title, period, reason, due_date, meeting_id) "
                             "VALUES (:by, :to, :t, :p, :r, :d, :m) RETURNING id",
                             by=uid, to=cfo["id"], t=title, p=period,
                             r=reason.strip(), d=due, m=meeting_id)
                db.audit(uid, "request_submitted", "document_request", row["id"], f"{title} ({period})")
                notify(cfo["id"], "request_new", "info", f"בקשה חדשה מ{user['name']}: \"{title}\" ({period}). מועד מענה: {ui.fmt_date(due)}.",
                       "document_request", row["id"], f"request_new:{row['id']}:{cfo['id']}")
                # שרשרת ההסלמה נכתבת לפי מי שביקש: לא אומרים ליו"ר שהבקשה "תעבור ליו"ר"
                is_ceo = user["role"] == "management" and auth.can(user, "submit_request")
                if user["role"] == "chair":
                    chain = "המנכ\"ל יקבל התראה, ואחריו תקבל/י התראה גם את/ה, כיו\"ר"
                elif is_ceo:
                    chain = "תקבל/י התראה, ואחרייך גם היו\"ר"
                else:
                    chain = "המנכ\"ל יקבל התראה, ואחריו היו\"ר"
                st.session_state.request_done = (f"הבקשה \"{title}\" ({period}) נשלחה ל{cfo['name']}. "
                                                 f"אם לא תיענה עד {ui.fmt_date(due)}, {chain}.")
                st.rerun()

# ================================================================ תור הטיפול (UC-24)
elif view == "תור הטיפול שלי":
    queue = db.query(
        "SELECT r.*, u.name AS requester, r.due_date < current_date AS overdue, "
        "m.title AS meeting_title, f.name AS forum "
        "FROM document_requests r JOIN users u ON u.id = r.requested_by "
        "LEFT JOIN meetings m ON m.id = r.meeting_id LEFT JOIN forums f ON f.id = m.forum_id "
        "WHERE r.assigned_to = :u AND r.status IN ('open','in_progress') ORDER BY r.due_date", u=uid)
    if not queue:
        st.success("אין בקשות שממתינות לטיפולך.", icon=":material/inbox:")
    for r in queue:
        color = "red" if r["overdue"] else "teal"
        with ui.card(f"q-{r['id']}", color):
            st.markdown(f"**{r['title']}**" + (f" · {r['period']}" if r["period"] else ""))
            ui.table([{"who": r["requester"], "meeting": f"{r['forum']}: {r['meeting_title']}" if r["meeting_id"] else "—",
                       "due": ui.fmt_date(r["due_date"]), "status": status_label(r)}],
                     {"who": "מבקש/ת", "meeting": "ישיבה", "due": "מועד מענה", "status": "מצב"})
            st.markdown(f"**נימוק:** {r['reason']}")
            if r["status"] == "open":
                if st.button("התחלת טיפול", key=f"start_{r['id']}", icon=":material/play_arrow:"):
                    db.execute("UPDATE document_requests SET status = 'in_progress' WHERE id = :id", id=r["id"])
                    db.audit(uid, "request_in_progress", "document_request", r["id"], None)
                    st.rerun()
            send_tab, reject_tab = st.tabs(["שליחת הדוח", "דחיית הבקשה"])
            with send_tab:
                with st.form(f"fulfill_{r['id']}"):
                    source = st.segmented_control("מקור הדוח", ["priority", "upload"], default="priority",
                                                  required=True, format_func=lambda s: SOURCE_HE[s])
                    file = st.file_uploader("קובץ הדוח (PDF או Excel)", type=["pdf", "xlsx", "xls", "csv"])
                    note = st.text_input("הערה למבקש/ת (רשות)")
                    ok = st.form_submit_button("שליחה לכל חברי הפורום", type="primary", icon=":material/send:")
                if ok:
                    filename = file.name if file else f"{r['title']}.pdf"
                    doc = db.one("INSERT INTO documents (doc_type, meeting_id, filename, stored_path, classification, uploaded_by) "
                                 "VALUES ('requested_report', :m, :f, :p, 'secret', :u) RETURNING id",
                                 m=r["meeting_id"], f=filename, p=f"requests/{r['id']}/{filename}", u=uid)
                    db.execute("UPDATE document_requests SET status = 'fulfilled', handled_at = now(), source = :s, "
                               "response_note = :n, document_id = :d WHERE id = :id",
                               s=source, n=note or None, d=doc["id"], id=r["id"])
                    db.audit(uid, "request_fulfilled", "document_request", r["id"],
                             "נשלח מ-Priority" if source == "priority" else "הועלה ידנית")
                    # בקשה אחת, כולם רואים: הודעה לכל חברי הפורום של הישיבה, ולמבקש/ת
                    members = db.query("SELECT fm.user_id FROM forum_members fm JOIN meetings m ON m.forum_id = fm.forum_id "
                                       "JOIN users u ON u.id = fm.user_id AND u.active WHERE m.id = :m",
                                       m=r["meeting_id"]) if r["meeting_id"] else []
                    for target in {x["user_id"] for x in members} | {r["requested_by"]}:
                        notify(target, "request_fulfilled", "info",
                               f"מסמך חדש: \"{r['title']}\" (לבקשת {r['requester']}).",
                               "document", doc["id"], f"newdoc:{doc['id']}:{target}")
                    st.success("הדוח נשלח ומוצג לכל חברי הפורום.", icon=":material/check_circle:")
                    st.rerun()
                st.caption("בגרסת ההדגמה נשמרים פרטי המסמך. אחסון הקבצים עצמם יחובר בשלב הבא.")
            with reject_tab:
                with st.form(f"reject_{r['id']}"):
                    why = st.text_area("נימוק הדחייה (חובה)")
                    no = st.form_submit_button("דחיית הבקשה", icon=":material/block:")
                if no:
                    if not why.strip():
                        st.error("חובה לנמק דחייה.")
                    else:
                        db.execute("UPDATE document_requests SET status = 'rejected', handled_at = now(), "
                                   "response_note = :n WHERE id = :id", n=why.strip(), id=r["id"])
                        db.audit(uid, "request_rejected", "document_request", r["id"], why.strip())
                        notify(r["requested_by"], "request_rejected", "warning",
                               f"הבקשה \"{r['title']}\" נדחתה: {why.strip()}", "document_request", r["id"],
                               f"request_rejected:{r['id']}")
                        st.rerun()

# ================================================================ דוחות שהתבקשו
elif view == "דוחות שהתבקשו":
    st.caption("דוח שהתבקש ונשלח מוצג לכל חברי הפורום של הישיבה, כך שכולם מגיעים לדיון עם אותו מידע.")
    reports = db.query(
        "SELECT r.title, r.period, u.name AS requester, r.handled_at, r.source, f.name AS forum, m.title AS meeting_title "
        "FROM document_requests r JOIN users u ON u.id = r.requested_by "
        "LEFT JOIN meetings m ON m.id = r.meeting_id LEFT JOIN forums f ON f.id = m.forum_id "
        "WHERE r.status = 'fulfilled' AND (:see_all OR r.requested_by = :u OR m.forum_id IN "
        "(SELECT forum_id FROM forum_members WHERE user_id = :u)) ORDER BY r.handled_at DESC",
        see_all=can_view_all, u=uid)
    with ui.card("reports", "navy"):
        ui.table([{"title": x["title"], "period": x["period"] or "", "meeting": f"{x['forum']}: {x['meeting_title']}" if x["forum"] else "—",
                   "who": x["requester"], "when": ui.fmt_date(x["handled_at"]), "source": SOURCE_HE[x["source"]]}
                  for x in reports],
                 {"title": "דוח", "period": "תקופה", "meeting": "ישיבה", "who": "לבקשת", "when": "נשלח", "source": "מקור"},
                 empty="עדיין אין דוחות שהתבקשו ונשלחו.")

# ================================================================ הבקשות שלי
elif view == "הבקשות שלי":
    mine = db.query("SELECT r.*, r.due_date < current_date AS overdue FROM document_requests r "
                    "WHERE r.requested_by = :u ORDER BY r.requested_at DESC", u=uid)
    with ui.card("mine"):
        ui.table([{"title": r["title"], "requested": ui.fmt_date(r["requested_at"]), "due": ui.fmt_date(r["due_date"]),
                   "status": status_label(r), "note": r["response_note"] or ""} for r in mine],
                 {"title": "בקשה", "requested": "נשלחה", "due": "מועד מענה", "status": "מצב", "note": "תשובה"},
                 empty="עדיין לא שלחת בקשות.")
