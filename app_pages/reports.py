# דוחות בקרה (UC-21): מעקב החלטות, היעדרויות, תמונת מצב ישיבות, ציות (מניין ותדירות) ויומן הפעולות.
# כל דוח נבנה ב-JOIN או מתצוגה (View) במסד, בלי טבלאות נוספות.
import csv
import io
from datetime import date, timedelta

import streamlit as st

from board import db, ui

STATUS_DEC = {"open": "פתוחה", "in_progress": "בביצוע", "done": "בוצעה"}
REASON_HE = {"bereavement": "אבל", "illness": "מחלה", "emergency": "חירום",
             "reserve_duty": "מילואים", "other": "אחר", None: ""}

view = ui.section_menu(["מעקב החלטות", "היעדרויות", "תמונת מצב ישיבות", "ציות: מניין ותדירות", "יומן פעולות"],
                       key="reports_view")

# ================================================================ מעקב החלטות
if view == "מעקב החלטות":
    rows = db.query(
        "SELECT d.text, u.name AS owner, d.due_date, d.status, d.status_note, "
        "d.status <> 'done' AND d.due_date < current_date AS overdue, "
        "m.title AS meeting, f.name AS forum "
        "FROM decisions d JOIN agenda_items ai ON ai.id = d.agenda_item_id "
        "JOIN meetings m ON m.id = ai.meeting_id JOIN forums f ON f.id = m.forum_id "
        "LEFT JOIN users u ON u.id = d.owner_id ORDER BY (d.status = 'done'), d.due_date")
    # מסננים: פורום, אחראי/ת, מצב, ורק החלטות באיחור
    c1, c2, c3, c4 = st.columns([2, 2, 2, 1], vertical_alignment="bottom")
    f_forum = c1.multiselect("פורום", sorted({r["forum"] for r in rows}), placeholder="כל הפורומים")
    f_owner = c2.multiselect("אחראי/ת", sorted({r["owner"] for r in rows if r["owner"]}), placeholder="כל האחראים")
    f_status = c3.multiselect("מצב", list(STATUS_DEC), format_func=STATUS_DEC.get, default=["open", "in_progress"])
    f_late = c4.toggle("רק באיחור")
    rows = [r for r in rows if (not f_forum or r["forum"] in f_forum) and (not f_owner or r["owner"] in f_owner)
            and (not f_status or r["status"] in f_status) and (not f_late or r["overdue"])]
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
    # זו מתחת לזו, כדי שהטבלה המפורטת לא תחרוג מהכרטיס
    with ui.card("absences", "navy"):
        st.markdown("**כל ההיעדרויות**")
        ui.table([{"name": r["user_name"], "date": ui.fmt_date(r["meeting_date"]), "meeting": f"{r['forum']}: {r['title']}",
                   "reason": REASON_HE[r["absence_reason"]], "status": r["status"]} for r in rows],
                 {"name": "דירקטור/ית", "date": "תאריך", "meeting": "ישיבה", "reason": "סיבה", "status": "החלטת היו\"ר"},
                 empty="אין היעדרויות.")
    with ui.card("absence-summary", "gold"):
        st.markdown("**סיכום לכל דירקטור/ית**")
        ui.table(list(summary.values()), {"name": "דירקטור/ית", "total": "היעדרויות", "unjustified": "לא מוצדקות"})
    st.caption("היעדרות לא מוצדקת אינה מסירה מהדירקטור אחריות להחלטות שהתקבלו בישיבה. "
               "המערכת אינה אוספת מסמכים רפואיים.")

# ================================================================ תמונת מצב ישיבות
elif view == "תמונת מצב ישיבות":
    rows = db.query(
        "SELECT m.id, m.meeting_at, f.name AS forum, m.title, m.status, "
        "(SELECT count(*) FROM agenda_items ai WHERE ai.meeting_id = m.id) AS items, "
        # נושא להחלטה שחסרים בו 3 רכיבים או יותר מתבנית החובה (כולל ניהול הסיכון)
        "(SELECT count(*) FROM agenda_items ai WHERE ai.meeting_id = m.id AND ai.item_type = 'decision' AND "
        " (ai.decision_required IS NULL)::int + (ai.alternatives IS NULL)::int + (ai.no_go_option IS NULL)::int + "
        " (ai.risks IS NULL)::int + (ai.negative_scenario IS NULL)::int + (ai.risk_level IS NULL)::int + "
        " (ai.risk_mitigation IS NULL)::int + (ai.risk_owner_id IS NULL)::int + (ai.risk_indicators IS NULL)::int >= 3"
        ") AS incomplete, "
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
                   "status": ui.STATUS_HE[r["status"]], "items": str(r["items"]), "incomplete": r["incomplete"],
                   "signed": f"{r['signed']} מתוך {r['participants']}", "conflicts": r["conflicts"],
                   "minutes": MINUTES_HE.get(r["minutes_status"], "")} for r in rows],
                 {"date": "מועד", "forum": "פורום", "title": "ישיבה", "status": "מצב", "items": "נושאים",
                  "incomplete": "נושאים חסרים", "signed": "חתמו על הצהרה", "conflicts": "עניין אישי",
                  "minutes": "פרוטוקול"})
    st.caption("הדוח מחבר ב-JOIN את טבלאות הישיבות, סדר היום, ההשתתפות והתשובות לכל נושא. "
               "\"נושאים חסרים\": נושאים להחלטה שחסרים בהם 3 רכיבים או יותר מתבנית החובה, כולל ניהול הסיכון.")

# ================================================================ ציות: מניין ותדירות (UC-21)
elif view == "ציות: מניין ותדירות":
    st.caption("בקרה על הדרישות שמגנות על הדירקטוריון: הדירקטוריון מתכנס לפחות פעם ברבעון, בכל ישיבה יש מניין, "
               "החומר מופץ בזמן, כל המשתתפים חותמים על הצהרה, והפרוטוקול נחתם.")
    quorum_pct = db.setting_int("quorum_percent", 50)
    min_board = db.setting_int("board_min_meetings_per_quarter", 1)

    # ---- תדירות: ישיבות שהתקיימו בכל פורום, בארבעת הרבעונים האחרונים
    today = date.today()
    quarters = []
    for k in range(3, -1, -1):
        q_index = (today.year * 4 + (today.month - 1) // 3) - k
        y, q = divmod(q_index, 4)
        quarters.append((y, q + 1))
    freq = db.query(
        "SELECT f.id, f.name, f.forum_type, f.mandatory, extract(year FROM m.meeting_at)::int AS y, "
        "extract(quarter FROM m.meeting_at)::int AS q, count(m.id) AS n "
        "FROM forums f LEFT JOIN meetings m ON m.forum_id = f.id AND m.status IN ('held','closed') "
        "GROUP BY f.id, f.name, f.forum_type, f.mandatory, y, q ORDER BY f.forum_type, f.name")
    forums = {}
    for r in freq:
        fr = forums.setdefault(r["id"], {"name": r["name"], "board": r["forum_type"] == "board",
                                         "mandatory": r["mandatory"], "counts": {}})
        if r["y"]:
            fr["counts"][(r["y"], r["q"])] = r["n"]
    rows, gaps = [], 0
    for fr in forums.values():
        row = {"forum": fr["name"] + (" (חובה)" if fr["mandatory"] else "")}
        for y, q in quarters:
            n = fr["counts"].get((y, q), 0)
            current = (y, q) == quarters[-1]          # הרבעון הנוכחי עוד לא נגמר
            if fr["board"] and n < min_board and not current:
                row[f"{y}q{q}"] = "באיחור"
                gaps += 1
            else:
                row[f"{y}q{q}"] = str(n)
        rows.append(row)
    with ui.card("frequency", "red" if gaps else "navy"):
        st.markdown(f"**תדירות ישיבות לפי רבעון** · הדירקטוריון חייב להתכנס לפחות {min_board} פעם ברבעון")
        ui.table(rows, {"forum": "פורום", **{f"{y}q{q}": f"רבעון {q}/{y}" for y, q in quarters}})
        st.caption("\"באיחור\": רבעון שהסתיים בלי ישיבת דירקטוריון. הרבעון הנוכחי אינו נבדק עד סופו.")

    # ---- לכל ישיבה שהתקיימה: מניין, הפצת חומר בזמן, הצהרות ופרוטוקול
    held = db.query(
        "SELECT m.id, m.meeting_at, m.title, f.name AS forum, m.materials_distributed_at, "
        "m.materials_distributed_at <= m.meeting_at - make_interval(days => m.materials_deadline_days) AS on_time, "
        "m.materials_deadline_days, m.minutes_status, "
        "(SELECT count(*) FROM forum_members fm WHERE fm.forum_id = m.forum_id) AS members, "
        "(SELECT count(*) FROM attendance a JOIN forum_members fm ON fm.forum_id = m.forum_id AND fm.user_id = a.user_id "
        " WHERE a.meeting_id = m.id AND a.attended IN ('physical','remote')) AS present, "
        "(SELECT count(*) FROM v_meeting_participants p WHERE p.meeting_id = m.id) AS participants, "
        "(SELECT count(*) FROM v_meeting_participants p WHERE p.meeting_id = m.id AND p.declaration_signed_at IS NOT NULL) AS signed "
        "FROM meetings m JOIN forums f ON f.id = m.forum_id "
        "WHERE m.status IN ('held','closed') OR (m.meeting_at < now() AND m.status = 'scheduled') "
        "ORDER BY m.meeting_at DESC")
    rows, problems = [], 0
    for r in held:
        has_quorum = r["members"] and r["present"] * 100 >= quorum_pct * r["members"]
        checks = {
            "quorum": f"{r['present']} מתוך {r['members']}" if has_quorum else "אין מניין",
            "materials": "הופץ" if r["on_time"] else ("באיחור" if r["materials_distributed_at"] else "טרם הופץ"),
            "declarations": "נחתם" if r["signed"] == r["participants"] else f"חסרים {r['participants'] - r['signed']}",
            "minutes": "נחתם" if r["minutes_status"] == "approved" else "ממתין לחתימה",
        }
        problems += sum(v in ("אין מניין", "באיחור", "טרם הופץ", "ממתין לחתימה") or v.startswith("חסרים")
                        for v in checks.values())
        rows.append({"date": ui.fmt_date(r["meeting_at"]), "meeting": f"{r['forum']}: {r['title']}", **checks})
    with st.container(horizontal=True):
        ui.kpi("cmp-held", "ישיבות שנבדקו", len(held), ":material/fact_check:")
        ui.kpi("cmp-problems", "ממצאים לטיפול", problems, ":material/report:", alert=problems > 0)
        ui.kpi("cmp-freq", "רבעונים בלי ישיבת דירקטוריון", gaps, ":material/event_busy:", alert=gaps > 0)
    with ui.card("compliance", "navy"):
        st.markdown(f"**בדיקת ציות לכל ישיבה** · מניין: לפחות {quorum_pct}% מחברי הפורום נכחו")
        ui.table(rows, {"date": "מועד", "meeting": "ישיבה", "quorum": "מניין (נכחו)", "materials": "חומר הופץ בזמן",
                        "declarations": "הצהרות", "minutes": "פרוטוקול"}, empty="אין ישיבות שהתקיימו.")
        st.caption("המניין מחושב לפי הנוכחות שאישרו היו\"ר או המזכירות. אחוז המניין והתדירות המינימלית "
                   "נקבעים בהגדרות המערכת, לפי תקנון החברה.")

# ================================================================ יומן פעולות (UC-21)
else:
    st.caption("כל פעולה במערכת נרשמת כאן: כניסות, צפייה ושליחת מסמכים, חתימות, בקשות, החלטות ושאלות לסוכן. "
               "היומן אינו ניתן לעריכה או למחיקה, גם לא בידי מנהל המערכת, ולכן הוא משמש ראיה לתהליך.")
    users = db.query("SELECT id, name FROM users ORDER BY name")
    actions = [r["action"] for r in db.query("SELECT DISTINCT action FROM audit_log ORDER BY action")]
    c1, c2, c3 = st.columns([2, 2, 2])
    period = c1.date_input("תקופה", (date.today() - timedelta(days=30), date.today()), format="DD/MM/YYYY")
    who = c2.multiselect("משתמש/ת", [u["id"] for u in users], placeholder="כל המשתמשים",
                         format_func=lambda i: next(u["name"] for u in users if u["id"] == i))
    what = c3.multiselect("פעולה", actions, placeholder="כל הפעולות")
    start, end = (period if isinstance(period, tuple) and len(period) == 2 else (period[0], period[0]) if period
                  else (date.today(), date.today()))
    sql = ("SELECT l.ts, u.name, l.action, l.entity, l.entity_id, l.details FROM audit_log l "
           "LEFT JOIN users u ON u.id = l.user_id WHERE l.ts >= :s AND l.ts < :e ")
    params = {"s": start, "e": end + timedelta(days=1)}
    if who:
        sql += "AND l.user_id = ANY(:who) "
        params["who"] = who
    if what:
        sql += "AND l.action = ANY(:what) "
        params["what"] = what
    log = db.query(sql + "ORDER BY l.ts DESC LIMIT 2000", **params)
    with st.container(horizontal=True):
        ui.kpi("log-n", "פעולות בתקופה", len(log), ":material/history:")
        ui.kpi("log-fail", "כניסות שנכשלו", sum("fail" in r["action"] or "lock" in r["action"] for r in log),
               ":material/lock:", alert=any("lock" in r["action"] for r in log))
        ui.kpi("log-ai", "שאלות לסוכן ה-AI", sum(r["action"] == "ai_question" for r in log), ":material/psychology:")
    with ui.card("audit", "navy"):
        ui.table([{"ts": ui.fmt_date(r["ts"]), "who": r["name"] or "מערכת", "action": r["action"],
                   "entity": f"{r['entity'] or ''} {r['entity_id'] or ''}".strip(),
                   "details": (r["details"] or "")[:160]} for r in log[:300]],
                 {"ts": "מועד", "who": "משתמש/ת", "action": "פעולה", "entity": "על מה", "details": "פרטים"},
                 empty="אין פעולות בתקופה שנבחרה.")
        if len(log) > 300:
            st.caption(f"מוצגות 300 הפעולות האחרונות מתוך {len(log)}. לרשימה המלאה: ייצוא לקובץ.")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["מועד", "משתמש/ת", "פעולה", "ישות", "מזהה", "פרטים"])
    for r in log:
        writer.writerow([ui.fmt_date(r["ts"]), r["name"] or "", r["action"], r["entity"] or "", r["entity_id"] or "",
                         r["details"] or ""])
    st.download_button("ייצוא לקובץ (CSV)", buf.getvalue().encode("utf-8-sig"), file_name="audit_log.csv",
                       mime="text/csv", icon=":material/download:")
