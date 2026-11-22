# מסך 3: ישיבות (UC-08, UC-10, UC-12, UC-13). לכל ישיבה: סדר יום, מסמכים, משתתפים, פרוטוקול ונושאים פתוחים.
# כל משתמש רואה רק ישיבות של פורום שהוא חבר בו או שהוזמן אליהן. יו"ר, מזכירות ומנהל מערכות רואים את כולן.
import hashlib
from datetime import date, datetime, time, timedelta, timezone

import streamlit as st

from board import auth, db, ui

user = st.session_state.user
uid, role = user["id"], user["role"]
sees_all = role in ("admin", "secretary", "chair")

DOC_TYPE_HE = {"meeting_material": "חומר ישיבה", "conflict_declaration": "טופס הצהרה חתום",
               "requested_report": "דוח שהתבקש", "absence_proof": "אסמכתה להיעדרות",
               "field_check": "ממצאי בדיקת שטח"}
CLASS_HE = {"internal": "פנימי", "confidential": "סודי", "secret": "סודי ביותר"}
MINUTES_HE = {"none": "טרם נכתב", "draft": "טיוטה", "circulated": "הופץ להערות", "approved": "אושר ונחתם"}
DEC_HE = {"open": "פתוחה", "in_progress": "בביצוע", "done": "בוצעה"}
REQ_HE = {"open": "פתוחה", "in_progress": "בטיפול", "fulfilled": "נשלחה", "rejected": "נדחתה"}

can_manage = auth.can(user, "manage_meetings")      # מזכירות, יו"ר ומנהל מערכות
can_approve = auth.can(user, "approve_minutes")     # יו"ר בלבד


def sign_banner(meeting: dict) -> None:
    """תזכורת בולטת, אם המשתמש משתתף בישיבה קרובה ועוד לא חתם על טופס ההצהרה."""
    me = db.one("SELECT declaration_signed_at FROM v_meeting_participants WHERE meeting_id = :m AND user_id = :u",
                m=meeting["id"], u=uid)
    if auth.can(user, "sign_declaration") and me and not me.get("declaration_signed_at") and meeting["status"] == "scheduled":
        with st.container(horizontal=True, vertical_alignment="center"):
            st.error("טרם חתמת על טופס הצהרת ניגוד העניינים לישיבה זו. בלי חתימה לא ניתן להצביע.",
                     icon=":material/assignment_late:")
            if st.button("לחתימה על הטופס", icon=":material/draw:", type="primary", key=f"sign_go_{meeting['id']}"):
                st.session_state["sign_open"] = meeting["id"]
                st.switch_page("app_pages/calendar.py")


# ---------------------------------------------------------------- קביעת ישיבה חדשה
if can_manage:
    with st.expander("קביעת ישיבה חדשה", icon=":material/add_circle:",
                     expanded=st.session_state.pop("open_new_meeting", False)):
        forums = db.query("SELECT id, name FROM forums ORDER BY forum_type, name")
        with st.form("new_meeting", border=False):
            c1, c2 = st.columns(2)
            forum_id = c1.selectbox("פורום", [f["id"] for f in forums],
                                    format_func=lambda i: next(f["name"] for f in forums if f["id"] == i))
            title = c2.text_input("נושא הישיבה")
            c3, c4, c5 = st.columns(3)
            new_date = c3.date_input("תאריך", date.today() + timedelta(days=14), format="DD/MM/YYYY")
            new_time = c4.time_input("שעה", time(9, 0), step=900)
            status = c5.selectbox("מצב", ["scheduled", "proposed"], format_func=ui.STATUS_HE.get,
                                  help="מועד מוצע: המשתתפים מסמנים אם המועד מתאים להם, ואז מאשרים אותו.")
            c6, c7, c8 = st.columns(3)
            location = c6.text_input("מקום", "חדר הדירקטוריון, מטה החברה")
            mode = c7.selectbox("אופן", list(ui.MODE_HE), format_func=ui.MODE_HE.get)
            deadline = c8.number_input("הפצת חומר: ימים לפני הישיבה", 1, 30, 5)
            if st.form_submit_button("קביעת הישיבה", type="primary", icon=":material/event_available:"):
                when_at = datetime.combine(new_date, new_time, tzinfo=ui.israel_tz())
                if not title.strip():
                    st.error("יש לכתוב את נושא הישיבה.")
                elif when_at < datetime.now(timezone.utc):
                    st.error("המועד כבר עבר.")
                else:
                    row = db.one("INSERT INTO meetings (forum_id, title, meeting_at, location, mode, status, "
                                 "materials_deadline_days, created_by) VALUES (:f, :t, :at, :loc, :mode, :s, :d, :u) "
                                 "RETURNING id", f=forum_id, t=title.strip(), at=when_at, loc=location.strip() or None,
                                 mode=mode, s=status, d=deadline, u=uid)
                    for p in db.query("SELECT user_id FROM forum_members WHERE forum_id = :f", f=forum_id):
                        db.execute("INSERT INTO reminders (user_id, rule, severity, message, related_type, related_id, "
                                   "dedupe_key) VALUES (:u, 'meeting_new', 'info', :msg, 'meeting', :m, :k) "
                                   "ON CONFLICT (dedupe_key) DO NOTHING", u=p["user_id"], m=row["id"],
                                   msg=f"נקבעה ישיבה: {title.strip()}, {ui.fmt_date(when_at)}. יש לאשר הגעה ב\"היומן שלי\".",
                                   k=f"meeting_new:{row['id']}:{p['user_id']}")
                    db.audit(uid, "meeting_created", "meeting", row["id"], f"{title.strip()} | {ui.fmt_date(when_at)}")
                    st.session_state["meeting_when"] = "קרובות"
                    st.session_state["meeting_pick"] = row["id"]
                    st.toast("הישיבה נקבעה וחברי הפורום קיבלו הודעה. עכשיו אפשר להוסיף נושאים לסדר היום.",
                             icon=":material/check_circle:")
                    st.rerun()

# ---------------------------------------------------------------- בחירת ישיבה
when = st.segmented_control("ישיבות", ["קרובות", "שהתקיימו", "כולן"],
                            default=None if "meeting_when" in st.session_state else "קרובות",
                            required=True, label_visibility="collapsed", key="meeting_when")
time_filter = {"קרובות": "AND m.meeting_at >= now() AND m.status IN ('proposed','scheduled')",
               "שהתקיימו": "AND (m.meeting_at < now() OR m.status IN ('held','closed'))",
               "כולן": ""}[when]
access = "" if sees_all else ("AND m.id IN (SELECT meeting_id FROM v_meeting_participants WHERE user_id = :u)")
meetings = db.query(
    "SELECT m.id, m.title, m.meeting_at, m.status, m.mode, m.location, m.minutes_body, m.minutes_status, "
    "m.minutes_approved_at, ap.name AS approved_by, m.materials_distributed_at, f.name AS forum "
    "FROM meetings m JOIN forums f ON f.id = m.forum_id LEFT JOIN users ap ON ap.id = m.minutes_approved_by "
    f"WHERE m.status <> 'cancelled' {time_filter} {access} "
    "ORDER BY m.meeting_at " + ("DESC" if when == "שהתקיימו" else ""), u=uid)

if not meetings:
    st.info("אין ישיבות להצגה.", icon=":material/event_busy:")
    st.stop()

if st.session_state.get("meeting_pick") not in [x["id"] for x in meetings]:
    st.session_state.pop("meeting_pick", None)
meeting_id = st.selectbox(
    "בחירת ישיבה", [m["id"] for m in meetings], key="meeting_pick",
    format_func=lambda i: next(f"{ui.fmt_date(m['meeting_at'])} · {m['forum']}: {m['title']}"
                               for m in meetings if m["id"] == i))
m = next(x for x in meetings if x["id"] == meeting_id)

# ---------------------------------------------------------------- כותרת הישיבה
with ui.card("meeting-head", "navy"):
    st.markdown(f"### {m['forum']}: {m['title']}")
    ui.table([{"when": ui.fmt_date(m["meeting_at"]), "status": ui.STATUS_HE[m["status"]],
               "mode": ui.MODE_HE[m["mode"]], "where": m["location"] or "",
               "materials": "הופץ" if m["materials_distributed_at"] else "טרם הופץ",
               "minutes": MINUTES_HE.get(m["minutes_status"], "")}],
             {"when": "מועד", "status": "מצב", "mode": "אופן", "where": "מקום",
              "materials": "חומר", "minutes": "פרוטוקול"})
sign_banner(m)


def notify_participants(rule: str, severity: str, message: str, key: str) -> None:
    for p in db.query("SELECT user_id FROM v_meeting_participants WHERE meeting_id = :m", m=meeting_id):
        if p["user_id"] != uid:
            db.execute("INSERT INTO reminders (user_id, rule, severity, message, related_type, related_id, dedupe_key) "
                       "VALUES (:u, :r, :s, :msg, 'meeting', :m, :k) ON CONFLICT (dedupe_key) DO NOTHING",
                       u=p["user_id"], r=rule, s=severity, msg=message, m=meeting_id, k=f"{key}:{p['user_id']}")


# ---------------------------------------------------------------- עריכת פרטי הישיבה: מועד, מקום, אופן ומצב
if can_manage and m["status"] not in ("closed", "cancelled"):
    with st.expander("שינוי מועד או פרטי הישיבה", icon=":material/edit_calendar:",
                     expanded=st.session_state.pop("open_edit_meeting", False)):
        STATUS_EDIT = ["proposed", "scheduled", "held", "cancelled"]
        old_at = ui.local(m["meeting_at"])
        with st.form(f"edit_meeting_{meeting_id}", border=False):
            c1, c2 = st.columns(2)
            new_date = c1.date_input("תאריך", old_at.date(), format="DD/MM/YYYY")
            new_time = c2.time_input("שעה", old_at.time().replace(tzinfo=None), step=900)
            c3, c4, c5 = st.columns(3)
            new_loc = c3.text_input("מקום", m["location"] or "")
            new_mode = c4.selectbox("אופן", list(ui.MODE_HE), index=list(ui.MODE_HE).index(m["mode"]),
                                    format_func=ui.MODE_HE.get)
            new_status = c5.selectbox("מצב", STATUS_EDIT, index=STATUS_EDIT.index(m["status"]),
                                      format_func=ui.STATUS_HE.get)
            reason = st.text_input("סיבת השינוי (תישלח למשתתפים)")
            if st.form_submit_button("שמירת השינויים", type="primary", icon=":material/save:"):
                new_at = datetime.combine(new_date, new_time, tzinfo=ui.israel_tz())
                moved = new_at != old_at
                if (moved or new_status == "cancelled") and not reason.strip():
                    st.error("בשינוי מועד או בביטול יש לכתוב את הסיבה.")
                else:
                    # בדיקה אופטימית: מעדכנים רק אם אף אחד לא שינה את הישיבה מאז שהמסך נטען
                    if not db.one("UPDATE meetings SET meeting_at = :at, location = :loc, mode = :mode, status = :s "
                                  "WHERE id = :m AND meeting_at = :old_at AND status = :old_s RETURNING id",
                                  at=new_at, loc=new_loc.strip() or None, mode=new_mode, s=new_status,
                                  m=meeting_id, old_at=m["meeting_at"], old_s=m["status"]):
                        raise db.UserError("פרטי הישיבה עודכנו בינתיים בידי משתמש/ת אחר/ת, ולכן השינוי שלך לא נשמר."
                                           + db.REFRESH, "optimistic lock: meetings")
                    if moved:   # המועד השתנה: אישורי ההגעה הקודמים כבר לא תקפים
                        db.execute("UPDATE attendance SET rsvp = NULL, rsvp_at = NULL, absence_reason = NULL, "
                                   "absence_note = NULL, absence_justified = NULL, absence_reviewed_by = NULL "
                                   "WHERE meeting_id = :m AND attended IS NULL", m=meeting_id)
                    what = (f"הישיבה \"{m['title']}\" הוזזה מ-{ui.fmt_date(old_at)} ל-{ui.fmt_date(new_at)}. "
                            "יש לאשר הגעה מחדש." if moved else
                            f"הישיבה \"{m['title']}\" בוטלה." if new_status == "cancelled" else
                            f"פרטי הישיבה \"{m['title']}\" עודכנו.")
                    notify_participants("meeting_changed", "warning" if moved or new_status == "cancelled" else "info",
                                        what + (f" סיבה: {reason.strip()}" if reason.strip() else ""),
                                        f"meeting_changed:{meeting_id}:{new_at.isoformat()}:{new_status}")
                    db.audit(uid, "meeting_updated", "meeting", meeting_id, what + f" | {reason.strip()}")
                    st.toast("השינויים נשמרו והמשתתפים קיבלו הודעה.", icon=":material/check_circle:")
                    st.rerun()
        st.caption("בשינוי מועד: אישורי ההגעה מתאפסים, כל משתתף מקבל תזכורת לאשר מחדש, "
                   "והורדה מחדש של קובץ היומן מעדכנת את הפגישה ביומן האישי.")

tab_agenda, tab_docs, tab_people, tab_minutes, tab_open = st.tabs(
    [":material/list_alt: סדר יום", ":material/folder: מסמכים", ":material/group: משתתפים",
     ":material/description: פרוטוקול", ":material/pending_actions: נושאים פתוחים"])

# ================================================================ סדר יום ותבנית החובה
with tab_agenda:
    items = db.query(
        "SELECT ai.*, u.name AS presenter, ro.name AS risk_owner, "
        "(SELECT count(*) FROM item_responses r WHERE r.agenda_item_id = ai.id AND r.has_conflict) AS conflicts, "
        "(SELECT count(*) FROM item_responses r WHERE r.agenda_item_id = ai.id AND r.vote = 'for') AS v_for, "
        "(SELECT count(*) FROM item_responses r WHERE r.agenda_item_id = ai.id AND r.vote = 'against') AS v_against, "
        "(SELECT count(*) FROM item_responses r WHERE r.agenda_item_id = ai.id AND r.vote = 'abstain') AS v_abstain "
        "FROM agenda_items ai LEFT JOIN users u ON u.id = ai.presenter_id "
        "LEFT JOIN users ro ON ro.id = ai.risk_owner_id "
        "WHERE ai.meeting_id = :m ORDER BY ai.position", m=meeting_id)
    if not items:
        st.caption("עדיין אין נושאים בסדר היום.")
    # תבנית החובה לנושא להחלטה. החלק השני הוא ניהול הסיכון: "הפרוטוקול צריך להראות שהסיכונים זוהו,
    # נשקלו וטופלו" (חיים כהן, מפגש 14).
    REQUIRED = [("decision_required", "ההחלטה הנדרשת"), ("alternatives", "חלופות"),
                ("no_go_option", "אפשרות לא לבצע"), ("risks", "סיכונים"), ("negative_scenario", "תרחיש שלילי"),
                ("risk_level", "עוצמת הסיכון"), ("risk_mitigation", "דרכי טיפול בסיכון"),
                ("risk_owner", "בעל הסיכון"), ("risk_indicators", "מדדי התראה")]
    RISK_HE = {"low": "נמוכה", "medium": "בינונית", "high": "גבוהה"}

    def shown(it, col):
        return RISK_HE.get(it[col]) if col == "risk_level" else it[col]

    for it in items:
        missing = [label for col, label in REQUIRED if not it[col]] if it["item_type"] == "decision" else []
        color = "red" if len(missing) >= 3 else ("gold" if missing else "teal")
        with ui.card(f"item-{it['id']}", color):
            kind = {"decision": "להחלטה", "discussion": "לדיון", "info": "לעדכון"}[it["item_type"]]
            st.markdown(f"**{it['position']}. {it['title']}** · {kind} · מציג/ה: {it['presenter'] or '—'}")
            if it["summary"]:
                st.write(it["summary"])
            if it["item_type"] == "decision":
                with st.container(horizontal=True):
                    for col, label in REQUIRED:
                        st.badge(label, icon=":material/check:" if it[col] else ":material/close:",
                                 color="green" if it[col] else "red")
                if missing:
                    st.caption(f"חסרים רכיבי חובה: {', '.join(missing)}." +
                               (" הנושא מסומן כחסר, כי חסרים 3 רכיבים או יותר." if len(missing) >= 3 else ""))
                if it["risk_level"] == "high":
                    st.badge("סיכון בעוצמה גבוהה", icon=":material/crisis_alert:", color="red")
                with st.expander("פירוט תבנית החובה"):
                    for col, label in REQUIRED:
                        if col == "risk_level":
                            st.markdown("**ניהול הסיכון**")
                        st.markdown(f"**{label}:** {shown(it, col) or ':red[חסר]'}")
                if it["non_delegable"]:
                    st.caption(":material/gavel: סמכות שאינה ניתנת להאצלה לוועדה.")
            with st.container(horizontal=True):
                if it["conflicts"]:
                    st.badge(f"עניין אישי: {it['conflicts']}", icon=":material/warning:", color="orange")
                if it["v_for"] or it["v_against"] or it["v_abstain"]:
                    st.badge(f"בעד {it['v_for']} · נגד {it['v_against']} · נמנע {it['v_abstain']}",
                             icon=":material/how_to_vote:", color="blue")

    # ---- הוספת נושא לסדר היום, עם תבנית החובה לנושא להחלטה
    if can_manage and m["status"] in ("proposed", "scheduled"):
        with st.expander("הוספת נושא לסדר היום", icon=":material/playlist_add:"):
            presenters = db.query("SELECT id, name, job_title FROM users WHERE active AND role IN "
                                  "('management','cfo','chair','secretary') ORDER BY name")
            KIND = {"decision": "להחלטה", "discussion": "לדיון", "info": "לעדכון"}
            kind = st.segmented_control("סוג הנושא", list(KIND), format_func=KIND.get, default="decision",
                                        required=True, key=f"new_item_kind_{meeting_id}")
            with st.form(f"new_item_{meeting_id}", border=False):
                c1, c2 = st.columns([3, 2])
                title = c1.text_input("נושא")
                presenter = c2.selectbox("מציג/ה", [p["id"] for p in presenters], index=None, placeholder="בחירה",
                                         format_func=lambda i: next(f"{p['name']}" + (f" ({p['job_title']})" if p["job_title"] else "")
                                                                    for p in presenters if p["id"] == i))
                summary = st.text_area("תקציר", height=80)
                fields = {}
                if kind == "decision":
                    st.caption("תבנית החובה לנושא להחלטה. נושא שחסרים בו 3 רכיבים או יותר מסומן כחסר.")
                    for col, label in REQUIRED[:5]:
                        fields[col] = st.text_area(label, height=68)
                    st.markdown("**ניהול הסיכון**")
                    r1, r2 = st.columns(2)
                    fields["risk_level"] = r1.segmented_control("עוצמת הסיכון", list(RISK_HE), format_func=RISK_HE.get,
                                                                help="מה הנזק אם הסיכון יתממש")
                    fields["risk_owner_id"] = r2.selectbox(
                        "בעל הסיכון", [p["id"] for p in presenters], index=None, placeholder="בחירה",
                        format_func=lambda i: next(p["name"] for p in presenters if p["id"] == i))
                    fields["risk_mitigation"] = st.text_area("דרכי טיפול בסיכון", height=68,
                                                             placeholder="מניעה, ביטוח, גידור, ביצוע בשלבים או תוכנית מגירה")
                    fields["risk_indicators"] = st.text_area("מדדי התראה", height=68,
                                                             placeholder="איך נדע בזמן שהסיכון מתממש, ומתי עוצרים")
                    non_delegable = st.checkbox("סמכות שאינה ניתנת להאצלה לוועדה")
                if st.form_submit_button("הוספה לסדר היום", type="primary", icon=":material/add:"):
                    if not title.strip():
                        st.error("יש לכתוב את הנושא.")
                    else:
                        pos = (items[-1]["position"] + 1) if items else 1
                        row = db.one(
                            "INSERT INTO agenda_items (meeting_id, position, title, item_type, presenter_id, summary, "
                            "decision_required, alternatives, no_go_option, risks, negative_scenario, risk_level, "
                            "risk_mitigation, risk_owner_id, risk_indicators, non_delegable) "
                            "VALUES (:m, :pos, :t, :k, :p, :s, :dr, :alt, :ng, :r, :neg, :rl, :rm, :ro, :ri, :nd) "
                            "RETURNING id",
                            rl=fields.get("risk_level"), ro=fields.get("risk_owner_id"),
                            rm=(fields.get("risk_mitigation") or "").strip() or None,
                            ri=(fields.get("risk_indicators") or "").strip() or None,
                            m=meeting_id, pos=pos, t=title.strip(), k=kind, p=presenter, s=summary.strip() or None,
                            dr=(fields.get("decision_required") or "").strip() or None,
                            alt=(fields.get("alternatives") or "").strip() or None,
                            ng=(fields.get("no_go_option") or "").strip() or None,
                            r=(fields.get("risks") or "").strip() or None,
                            neg=(fields.get("negative_scenario") or "").strip() or None,
                            nd=kind == "decision" and non_delegable)
                        db.audit(uid, "agenda_item_added", "agenda_item", row["id"], title.strip())
                        st.toast("הנושא נוסף לסדר היום.", icon=":material/check_circle:")
                        st.rerun()

# ================================================================ לשונית המסמכים
with tab_docs:
    docs = db.query(
        "SELECT d.id, d.doc_type, d.filename, d.classification, d.uploaded_at, d.content_sha256, "
        "u.name AS uploader, u.job_title, d.uploaded_by, ai.position, ai.title AS item_title "
        "FROM documents d LEFT JOIN users u ON u.id = d.uploaded_by "
        "LEFT JOIN agenda_items ai ON ai.id = d.agenda_item_id "
        "WHERE d.meeting_id = :m ORDER BY d.doc_type, ai.position NULLS FIRST, d.uploaded_at", m=meeting_id)

    def visible(d) -> bool:
        if d["doc_type"] == "conflict_declaration":      # טופס חתום: החותם, והגורמים שמנהלים את הישיבה
            return d["uploaded_by"] == uid or sees_all
        if d["doc_type"] == "absence_proof":             # אסמכתה חסויה
            return d["uploaded_by"] == uid or role in ("secretary", "chair")
        return True

    docs = [d for d in docs if visible(d)]
    if not docs:
        st.caption("אין מסמכים לישיבה זו.")
    groups = [("meeting_material", "חומרי הישיבה"), ("requested_report", "דוחות שהתבקשו (גלויים לכל חברי הפורום)"),
              ("field_check", "ממצאי בדיקות שטח"), ("conflict_declaration", "טפסי הצהרה חתומים"),
              ("absence_proof", "אסמכתאות היעדרות (חסוי)")]
    for dtype, title in groups:
        rows = [d for d in docs if d["doc_type"] == dtype]
        if not rows:
            continue
        with ui.card(f"docs-{dtype}", "navy" if dtype == "meeting_material" else "teal"):
            st.markdown(f"**{title}**")
            ui.table([{"file": d["filename"],
                       "item": f"{d['position']}. {d['item_title']}" if d["position"] else "כללי",
                       "by": f"{d['uploader']}" + (f" ({d['job_title']})" if d["job_title"] else ""),
                       "when": ui.fmt_date(d["uploaded_at"]), "cls": CLASS_HE.get(d["classification"], ""),
                       "seal": {"text": "חותמת שלמות", "tip": f"SHA-256: {d['content_sha256']}"} if d["content_sha256"] else ""}
                      for d in rows],
                     {"file": "מסמך", "item": "נושא", "by": "הועלה בידי", "when": "מועד", "cls": "סיווג", "seal": ""})
    st.caption("בסביבת ההדגמה מוצגים פרטי המסמך (שם, סיווג, חותמת שלמות) בלי הקובץ עצמו. בסביבת הייצור "
               "המסמכים יוצגו בתוך המערכת בלבד, עם סימן מים של שם הצופה, וכל צפייה תירשם ביומן הפעולות.")

# ================================================================ משתתפים
with tab_people:
    people = db.query(
        "SELECT p.user_id, p.user_name, p.role, p.is_forum_member, p.rsvp, p.attended, p.declaration_signed_at, "
        "a.declaration_sent_at, a.has_personal_interest, a.absence_reason, a.absence_justified "
        "FROM v_meeting_participants p "
        "LEFT JOIN attendance a ON a.meeting_id = p.meeting_id AND a.user_id = p.user_id "
        "WHERE p.meeting_id = :m ORDER BY p.is_forum_member DESC, p.user_name", m=meeting_id)
    REASON_HE = {"bereavement": "אבל", "illness": "מחלה", "emergency": "חירום",
                 "reserve_duty": "מילואים", "other": "אחר", None: ""}
    ATT_HE = {"physical": "נכח/ה", "remote": "מרחוק", "absent": "נעדר/ה", None: ""}
    rows = []
    for p in people:
        decl = ("נחתם" if p["declaration_signed_at"] else
                "ממתין לחתימה" if p["declaration_sent_at"] else "טרם נשלח")
        absence = REASON_HE[p["absence_reason"]]
        if p["absence_reason"]:
            absence += " · " + ("ממתין להחלטת היו\"ר" if p["absence_justified"] is None
                                else "מוצדקת" if p["absence_justified"] else "לא מוצדקת")
        rows.append({"name": p["user_name"], "kind": "חבר/ת פורום" if p["is_forum_member"] else "מוזמן/ת מההנהלה",
                     "rsvp": ui.RSVP_HE.get(p["rsvp"]), "attended": ATT_HE.get(p["attended"], ""),
                     "decl": decl, "interest": "יש" if p["has_personal_interest"] else "",
                     "absence": absence})
    with ui.card("people", "navy"):
        ui.table(rows, {"name": "שם", "kind": "סוג", "rsvp": "אישור הגעה", "attended": "נוכחות",
                        "decl": "טופס הצהרה", "interest": "עניין אישי", "absence": "היעדרות"})

    # ---- אישור נוכחות בפועל: מי שמנהל/ת ישיבות מסמן/ת מי נכח. ההחלטה אם היעדרות מוצדקת
    # שמורה למי שיש לו/ה הרשאת review_absence (היו"ר). שתי הבדיקות מטבלת ההרשאות, לא לפי שם התפקיד.
    can_review = auth.can(user, "review_absence")
    started = ui.local(m["meeting_at"]) <= ui.local(datetime.now(timezone.utc))
    if can_manage and (started or m["status"] in ("held", "closed")):
        with ui.card("confirm-attendance", "gold"):
            st.markdown("**אישור נוכחות בפועל**")
            st.caption("ברירת המחדל לפי אישור ההגעה ולפי מי שהצטרף מרחוק בקוד אימות. "
                       + ("את/ה גם קובע/ת אם היעדרות מוצדקת." if can_review
                          else "ההחלטה אם היעדרות מוצדקת שמורה ליו\"ר."))
            ATT = {"physical": "נכח/ה", "remote": "מרחוק", "absent": "נעדר/ה"}
            with st.form(f"attendance_{meeting_id}", border=False):
                choices = {}
                for p in people:
                    guess = p["attended"] or {"yes": "physical", "remote": "remote", "no": "absent"}.get(p["rsvp"])
                    c1, c2, c3 = st.columns([2, 3, 3], vertical_alignment="center")
                    c1.markdown(f"**{p['user_name']}**" + ("" if p["is_forum_member"] else "  \n:gray[מוזמן/ת]"))
                    att = c2.segmented_control("נוכחות", list(ATT), format_func=ATT.get, default=guess,
                                               key=f"att_{meeting_id}_{p['user_id']}", label_visibility="collapsed")
                    just = None
                    if can_review:
                        label = f"היעדרות ({REASON_HE[p['absence_reason']] or 'ללא סיבה'})"
                        current = {True: "מוצדקת", False: "לא מוצדקת"}.get(p["absence_justified"])
                        just = c3.segmented_control(label, ["מוצדקת", "לא מוצדקת"], default=current,
                                                    key=f"just_{meeting_id}_{p['user_id']}")
                    choices[p["user_id"]] = (att, just)
                if st.form_submit_button("שמירת הנוכחות", type="primary", icon=":material/how_to_reg:"):
                    for pid, (att, just) in choices.items():
                        if att:
                            db.execute("INSERT INTO attendance (meeting_id, user_id, attended) VALUES (:m, :u, :a) "
                                       "ON CONFLICT (meeting_id, user_id) DO UPDATE SET attended = EXCLUDED.attended",
                                       m=meeting_id, u=pid, a=att)
                        if can_review and att == "absent" and just:
                            db.execute("UPDATE attendance SET absence_justified = :j, absence_reviewed_by = :r "
                                       "WHERE meeting_id = :m AND user_id = :u",
                                       j=just == "מוצדקת", r=uid, m=meeting_id, u=pid)
                    db.audit(uid, "attendance_confirmed", "meeting", meeting_id,
                             ", ".join(f"{pid}:{a or '-'}" for pid, (a, _) in choices.items()))
                    st.toast("הנוכחות נשמרה.", icon=":material/check_circle:")
                    st.rerun()

# ================================================================ פרוטוקול
with tab_minutes:
    status = m["minutes_status"]
    with ui.card("minutes", "gold" if status != "approved" else "teal"):
        st.markdown(f"**מצב הפרוטוקול:** {MINUTES_HE.get(status, '')}")
        if status == "approved":
            st.caption(f"אושר ונחתם בידי {m['approved_by']} · {ui.fmt_date(m['minutes_approved_at'])}. "
                       "פרוטוקול חתום משמש ראיה לכאורה למה שנאמר בישיבה, ונשמר לפחות 7 שנים.")
        editable = can_manage and status != "approved"
        if m["minutes_body"] and not editable:
            st.markdown(m["minutes_body"])
        elif not editable:
            st.caption("הפרוטוקול ייכתב בזמן הישיבה או אחריה, בידי מזכירות החברה.")

        # ---- כתיבת הפרוטוקול: טיוטה, הפצה להערות המשתתפים, ואישור וחתימה של היו"ר
        if editable:
            st.caption("שלבים: טיוטה ← הפצה להערות המשתתפים ← אישור וחתימה של היו\"ר. "
                       "אחרי החתימה הפרוטוקול נעול לעריכה.")
            with st.form(f"minutes_{meeting_id}", border=False):
                body = st.text_area("נוסח הפרוטוקול", m["minutes_body"] or "", height=320,
                                    placeholder="נכחו: ...\nנושא 1: מה הוצג, אילו שאלות נשאלו, אילו חלופות נבחנו, "
                                                "מה הוחלט ומי הסתייג.\nנושא 2: ...")
                c1, c2 = st.columns(2)
                save = c1.form_submit_button("שמירת טיוטה", icon=":material/save:", width="stretch")
                send = c2.form_submit_button("הפצה להערות המשתתפים", icon=":material/forward_to_inbox:",
                                             type="primary", width="stretch")
                if save or send:
                    if not body.strip():
                        st.error("הפרוטוקול ריק.")
                    else:
                        new_status = "circulated" if send else ("draft" if status in ("none", "draft") else status)
                        # בדיקה אופטימית: שמירה רק אם הנוסח לא שונה בידי אחר/ת, והפרוטוקול עוד לא נחתם
                        if not db.one("UPDATE meetings SET minutes_body = :b, minutes_status = :s WHERE id = :m "
                                      "AND minutes_status <> 'approved' AND minutes_body IS NOT DISTINCT FROM :old "
                                      "RETURNING id", b=body.strip(), s=new_status, m=meeting_id,
                                      old=m["minutes_body"]):
                            raise db.UserError("הפרוטוקול שונה או נחתם בידי משתמש/ת אחר/ת בזמן שערכת, ולכן הנוסח "
                                               "שלך לא נשמר. העתק/י את הנוסח שלך לפני הרענון, כדי לא לאבד אותו." + db.REFRESH,
                                               "optimistic lock: minutes")
                        db.audit(uid, "minutes_" + ("circulated" if send else "saved"), "meeting", meeting_id, None)
                        if send:
                            notify_participants("minutes_circulated", "info",
                                                f"טיוטת הפרוטוקול של \"{m['title']}\" הופצה להערות.",
                                                f"minutes:{meeting_id}:{datetime.now(timezone.utc):%Y%m%d%H%M}")
                        st.toast("הפרוטוקול הופץ למשתתפים." if send else "הטיוטה נשמרה.",
                                 icon=":material/check_circle:")
                        st.rerun()
        if can_approve and status == "circulated":
            # חתימת היו"ר: אישור שקרא + קוד SMS חד-פעמי, כמו בטופס ניגוד העניינים
            code_key = f"minutes_code_{meeting_id}"
            ok = st.checkbox("קראתי את הפרוטוקול, והוא משקף נאמנה את מה שנאמר והוחלט בישיבה",
                             key=f"approve_ok_{meeting_id}")
            if st.button("שליחת קוד לחתימה", icon=":material/sms:", disabled=not ok, key=f"approve_{meeting_id}"):
                st.session_state[code_key] = auth.send_otp(uid, "sms")
            if code_key in st.session_state:
                st.info(f"הקוד שנשלח: **{st.session_state[code_key]}**",
                        title="מצב הדגמה: אין חיבור לשירות SMS", icon=":material/sms:")
                code = st.text_input("קוד החתימה", max_chars=6, key=f"minutes_code_in_{meeting_id}")
                if st.button("חתימה על הפרוטוקול", type="primary", icon=":material/verified:",
                             key=f"minutes_sign_{meeting_id}"):
                    verified, err = auth.verify_otp(uid, code, purpose="minutes_otp_verified")
                    if not verified:
                        st.error(err)
                    else:
                        # חותמת שלמות: גיבוב של הנוסח החתום, כדי שאפשר יהיה להוכיח שלא שונה אחר כך
                        sha = hashlib.sha256((m["minutes_body"] or "").encode("utf-8")).hexdigest()
                        # היו"ר חותם/ת רק על הנוסח שקרא/ה: אם הנוסח שונה בינתיים, החתימה נחסמת
                        if not db.one("UPDATE meetings SET minutes_status = 'approved', minutes_approved_by = :u, "
                                      "minutes_approved_at = now() WHERE id = :m AND minutes_status = 'circulated' "
                                      "AND minutes_body IS NOT DISTINCT FROM :old RETURNING id",
                                      u=uid, m=meeting_id, old=m["minutes_body"]):
                            del st.session_state[code_key]
                            raise db.UserError("הנוסח של הפרוטוקול שונה מאז שקראת אותו, ולכן החתימה לא בוצעה. "
                                               "חתימה נעשית רק על הנוסח שנקרא." + db.REFRESH,
                                               "optimistic lock: minutes approval")
                        db.audit(uid, "minutes_approved", "meeting", meeting_id, f"נחתם בקוד SMS | SHA-256: {sha}")
                        notify_participants("minutes_approved", "info", f"הפרוטוקול של \"{m['title']}\" אושר ונחתם.",
                                            f"minutes_approved:{meeting_id}")
                        del st.session_state[code_key]
                        st.toast("הפרוטוקול נחתם.", icon=":material/verified:")
                        st.rerun()
        elif status == "circulated":
            st.caption("הפרוטוקול הופץ להערות וממתין לאישור היו\"ר. הערות שולחים למזכירות החברה.")
    decisions = db.query(
        "SELECT ai.position, ai.title AS item, d.text, u.name AS owner, d.due_date, d.status, "
        "d.status <> 'done' AND d.due_date < current_date AS overdue "
        "FROM decisions d JOIN agenda_items ai ON ai.id = d.agenda_item_id LEFT JOIN users u ON u.id = d.owner_id "
        "WHERE ai.meeting_id = :m ORDER BY ai.position", m=meeting_id)
    if decisions:
        with ui.card("minutes-decisions", "navy"):
            st.markdown("**החלטות שהתקבלו בישיבה**")
            ui.table([{"item": f"{d['position']}. {d['item']}", "text": d["text"], "owner": d["owner"] or "",
                       "due": ui.fmt_date(d["due_date"]),
                       "status": "באיחור" if d["overdue"] else DEC_HE[d["status"]]} for d in decisions],
                     {"item": "נושא", "text": "החלטה", "owner": "אחראי/ת", "due": "מועד", "status": "מצב"})
    reservations = db.query(
        "SELECT ai.position, ai.title, u.name, r.reservation FROM item_responses r "
        "JOIN agenda_items ai ON ai.id = r.agenda_item_id JOIN users u ON u.id = r.user_id "
        "WHERE ai.meeting_id = :m AND r.reservation IS NOT NULL ORDER BY ai.position", m=meeting_id)
    if reservations:
        with ui.card("reservations", "gold"):
            st.markdown("**הסתייגויות שנרשמו**")
            for r in reservations:
                st.markdown(f"- **{r['name']}** (נושא {r['position']}, {r['title']}): {r['reservation']}")

# ================================================================ נושאים פתוחים
with tab_open:
    st.caption("כל מה שעדיין לא נסגר מהישיבה הזו: החלטות שטרם בוצעו, בקשות לדוחות שטרם נענו, וטפסים שטרם נחתמו.")
    open_dec = [d for d in decisions if d["status"] != "done"] if decisions else []
    open_req = db.query(
        "SELECT r.title, r.period, u.name AS requester, r.due_date, r.status, r.due_date < current_date AS overdue "
        "FROM document_requests r JOIN users u ON u.id = r.requested_by "
        "WHERE r.meeting_id = :m AND r.status IN ('open','in_progress') ORDER BY r.due_date", m=meeting_id)
    unsigned = [p for p in people if p["declaration_sent_at"] and not p["declaration_signed_at"]]
    with st.container(horizontal=True):
        ui.kpi("open-dec", "החלטות פתוחות", len(open_dec), ":material/task_alt:",
               alert=any(d["overdue"] for d in open_dec))
        ui.kpi("open-req", "בקשות לדוחות פתוחות", len(open_req), ":material/request_quote:",
               alert=any(r["overdue"] for r in open_req))
        ui.kpi("open-sign", "טפסים שטרם נחתמו", len(unsigned), ":material/draw:", alert=bool(unsigned))
    if open_dec:
        with ui.card("open-decisions", "red" if any(d["overdue"] for d in open_dec) else "teal"):
            st.markdown("**החלטות פתוחות**")
            ui.table([{"text": d["text"], "owner": d["owner"] or "", "due": ui.fmt_date(d["due_date"]),
                       "status": "באיחור" if d["overdue"] else DEC_HE[d["status"]]} for d in open_dec],
                     {"text": "החלטה", "owner": "אחראי/ת", "due": "מועד", "status": "מצב"})
    if open_req:
        with ui.card("open-requests"):
            st.markdown("**בקשות לדוחות שטרם נענו**")
            ui.table([{"title": r["title"], "period": r["period"] or "", "who": r["requester"],
                       "due": ui.fmt_date(r["due_date"]),
                       "status": "באיחור" if r["overdue"] else REQ_HE[r["status"]]} for r in open_req],
                     {"title": "דוח", "period": "תקופה", "who": "מבקש/ת", "due": "מועד מענה", "status": "מצב"})
    if unsigned:
        with ui.card("open-unsigned", "red"):
            st.markdown("**טרם חתמו על טופס ההצהרה**")
            st.write(", ".join(p["user_name"] for p in unsigned) + ". הם יקבלו תזכורת כל יום, ולא יוכלו להצביע עד שיחתמו.")
    if not (open_dec or open_req or unsigned):
        st.success("אין נושאים פתוחים בישיבה זו.", icon=":material/check_circle:")
