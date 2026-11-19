# דוחות בקרה (UC-21): מעקב החלטות, היעדרויות ותמונת מצב של הישיבות.
# כל דוח נבנה ב-JOIN או מתצוגה (View) במסד, בלי טבלאות נוספות.
import streamlit as st

from board import db, ui

STATUS_DEC = {"open": "פתוחה", "in_progress": "בביצוע", "done": "בוצעה"}
REASON_HE = {"bereavement": "אבל", "illness": "מחלה", "emergency": "חירום",
             "reserve_duty": "מילואים", "other": "אחר", None: ""}

view = ui.side_menu(["מעקב החלטות", "היעדרויות", "תמונת מצב ישיבות"], key="reports_view")

# ================================================================ מעקב החלטות
if view == "מעקב החלטות":
    rows = db.query(
        "SELECT d.text, u.name AS owner, d.due_date, d.status, d.status_note, "
        "d.status <> 'done' AND d.due_date < current_date AS overdue, "
        "m.title AS meeting, f.name AS forum "
        "FROM decisions d JOIN agenda_items ai ON ai.id = d.agenda_item_id "
        "JOIN meetings m ON m.id = ai.meeting_id JOIN forums f ON f.id = m.forum_id "
        "LEFT JOIN users u ON u.id = d.owner_id ORDER BY (d.status = 'done'), d.due_date")
    total, done = len(rows), sum(r["status"] == "done" for r in rows)
    late = sum(bool(r["overdue"]) for r in rows)
    with st.container(horizontal=True):
        ui.kpi("dec-total", "החלטות במעקב", total, ":material/task_alt:")
        ui.kpi("dec-done", "בוצעו", done, ":material/check_circle:")
        ui.kpi("dec-late", "באיחור", late, ":material/schedule:", alert=late > 0)
        ui.kpi("dec-rate", "שיעור ביצוע", f"{done / total:.0%}" if total else "—", ":material/percent:")
    with ui.card("decisions", "navy"):
        ui.table([{"text": r["text"], "meeting": f"{r['forum']}: {r['meeting']}", "owner": r["owner"] or "",
                   "due": ui.fmt_date(r["due_date"]),
                   "status": "באיחור" if r["overdue"] else STATUS_DEC[r["status"]],
                   "note": r["status_note"] or ""} for r in rows],
                 {"text": "החלטה", "meeting": "ישיבה", "owner": "אחראי/ת", "due": "מועד",
                  "status": "מצב", "note": "עדכון אחרון"}, empty="אין החלטות במעקב.")
    st.caption("החלטה באיחור מסלימה אוטומטית ליו\"ר. היעד: 85% מההחלטות מבוצעות עד המועד.")

# ================================================================ היעדרויות
elif view == "היעדרויות":
    rows = db.query("SELECT * FROM v_absence_report ORDER BY user_name, meeting_date")
    summary = {}
    for r in rows:
        s = summary.setdefault(r["user_name"], {"name": r["user_name"], "total": 0, "unjustified": 0})
        s["total"] += 1
        s["unjustified"] += r["status"] == "לא מוצדקת"
    left, right = st.columns([3, 2])
    with left, ui.card("absences", "navy"):
        st.markdown("**כל ההיעדרויות**")
        ui.table([{"name": r["user_name"], "date": ui.fmt_date(r["meeting_date"]), "meeting": f"{r['forum']}: {r['title']}",
                   "reason": REASON_HE[r["absence_reason"]], "status": r["status"]} for r in rows],
                 {"name": "דירקטור/ית", "date": "תאריך", "meeting": "ישיבה", "reason": "סיבה", "status": "החלטת היו\"ר"},
                 empty="אין היעדרויות.")
    with right, ui.card("absence-summary", "gold"):
        st.markdown("**סיכום לכל דירקטור/ית**")
        ui.table(list(summary.values()), {"name": "דירקטור/ית", "total": "היעדרויות", "unjustified": "לא מוצדקות"})
    st.caption("היעדרות לא מוצדקת אינה מסירה מהדירקטור אחריות להחלטות שהתקבלו בישיבה. "
               "המערכת אינה אוספת מסמכים רפואיים.")

# ================================================================ תמונת מצב ישיבות
else:
    rows = db.query(
        "SELECT m.id, m.meeting_at, f.name AS forum, m.title, m.status, "
        "(SELECT count(*) FROM agenda_items ai WHERE ai.meeting_id = m.id) AS items, "
        "(SELECT count(*) FROM v_meeting_participants p WHERE p.meeting_id = m.id) AS participants, "
        "(SELECT count(*) FROM v_meeting_participants p WHERE p.meeting_id = m.id "
        " AND p.declaration_signed_at IS NOT NULL) AS signed, "
        "(SELECT count(*) FROM item_responses r JOIN agenda_items ai ON ai.id = r.agenda_item_id "
        " WHERE ai.meeting_id = m.id AND r.has_conflict) AS conflicts, "
        "m.minutes_status FROM meetings m JOIN forums f ON f.id = m.forum_id "
        "WHERE m.status <> 'cancelled' ORDER BY m.meeting_at")
    MINUTES_HE = {"none": "אין", "draft": "טיוטה", "circulated": "הופץ להערות", "approved": "אושר"}
    with ui.card("overview", "navy"):
        ui.table([{"date": ui.fmt_date(r["meeting_at"]), "forum": r["forum"], "title": r["title"],
                   "status": ui.STATUS_HE[r["status"]], "items": str(r["items"]),
                   "signed": f"{r['signed']} מתוך {r['participants']}", "conflicts": r["conflicts"],
                   "minutes": MINUTES_HE.get(r["minutes_status"], "")} for r in rows],
                 {"date": "מועד", "forum": "פורום", "title": "ישיבה", "status": "מצב", "items": "נושאים",
                  "signed": "חתמו על הצהרה", "conflicts": "עניין אישי", "minutes": "פרוטוקול"})
    st.caption("הדוח מחבר ב-JOIN את טבלאות הישיבות, סדר היום, ההשתתפות והתשובות לכל נושא.")
