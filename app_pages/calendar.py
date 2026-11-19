# מסך: היומן שלי (UC-09, UC-11, UC-14). כל משתתף רואה כאן את הישיבות שלו:
# יומן חודשי, אישור הגעה, היעדרות עם סיבה, טופס הצהרת ניגוד עניינים, הצטרפות מרחוק בקוד אימות,
# ובישיבות שעברו: סימון אם נכח או נעדר (כפי שאישר היו"ר).
import calendar as cal
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from html import escape

import streamlit as st

from board import auth, db, ui

user = st.session_state.user
uid = user["id"]
DEMO = True   # אין חיבור לשירות SMS: הקוד מוצג על המסך, כמו במסך הכניסה

REASON_HE = {"bereavement": "אבל במשפחה", "illness": "מחלה", "emergency": "מקרה חירום",
             "reserve_duty": "שירות מילואים", "other": "אחר (יש לפרט)"}
RSVP_LABEL = {"yes": "מגיע/ה", "remote": "אשתתף מרחוק", "no": "לא אוכל להגיע"}

mine = db.query(
    "SELECT m.id, m.title, m.meeting_at, m.status, m.mode, m.location, f.name AS forum, p.is_forum_member, "
    "a.rsvp, a.attended, a.declaration_signed_at, a.absence_reason, a.absence_note, a.absence_justified, "
    "d.content_sha256, (m.meeting_at < now() OR m.status IN ('held','closed')) AS past "
    "FROM v_meeting_participants p JOIN meetings m ON m.id = p.meeting_id JOIN forums f ON f.id = m.forum_id "
    "LEFT JOIN attendance a ON a.meeting_id = m.id AND a.user_id = p.user_id "
    "LEFT JOIN documents d ON d.id = a.declaration_document_id "
    "WHERE p.user_id = :u AND m.status <> 'cancelled' ORDER BY m.meeting_at", u=uid)
upcoming = [m for m in mine if not m["past"]]
past = [m for m in mine if m["past"]]


def presence(m) -> tuple[str, str]:
    """סימון נוכחות לישיבה שעברה: אייקון + טקסט."""
    if m["attended"] == "physical":
        return "✔", "נכח/ה"
    if m["attended"] == "remote":
        return "💻", "מרחוק"
    if m["attended"] == "absent" or m["rsvp"] == "no":
        return "✖", "נעדר/ה"
    return "⏳", "ממתין לאישור היו\"ר"


def upsert_attendance(meeting_id: int, **cols) -> None:
    names = ", ".join(cols)
    values = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)
    db.execute(f"INSERT INTO attendance (meeting_id, user_id, {names}) VALUES (:mid, :uid, {values}) "
               f"ON CONFLICT (meeting_id, user_id) DO UPDATE SET {updates}", mid=meeting_id, uid=uid, **cols)


# ---------------------------------------------------------------- מדדים
with st.container(horizontal=True):
    ui.kpi("cal-next", "ישיבות קרובות", len(upcoming), ":material/event:")
    ui.kpi("cal-rsvp", "ממתינות לאישור הגעה", sum(1 for m in upcoming if not m["rsvp"]),
           ":material/how_to_reg:", alert=any(not m["rsvp"] for m in upcoming))
    ui.kpi("cal-sign", "טפסי הצהרה לחתימה", sum(1 for m in upcoming if not m["declaration_signed_at"]),
           ":material/draw:", alert=any(not m["declaration_signed_at"] for m in upcoming))
    held = [m for m in past if presence(m)[1] != "ממתין לאישור היו\"ר"]
    rate = round(100 * sum(1 for m in held if m["attended"] in ("physical", "remote")) / len(held)) if held else 0
    ui.kpi("cal-rate", "שיעור הנוכחות שלי", f"{rate}%", ":material/percent:")

tab_month, tab_next, tab_past = st.tabs([":material/calendar_month: יומן חודשי",
                                         ":material/event_upcoming: ישיבות קרובות",
                                         ":material/history: ישיבות שעברו"])

# ================================================================ יומן חודשי
with tab_month:
    today = date.today()
    months = [(today.year + (today.month - 1 + k) // 12, (today.month - 1 + k) % 12 + 1) for k in range(-3, 4)]
    MONTH_HE = ["ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני", "יולי", "אוגוסט", "ספטמבר",
                "אוקטובר", "נובמבר", "דצמבר"]
    year, month = st.selectbox("חודש", months, index=3, format_func=lambda ym: f"{MONTH_HE[ym[1] - 1]} {ym[0]}")
    by_day: dict[date, list] = {}
    for m in mine:
        by_day.setdefault(ui.local(m["meeting_at"]).date(), []).append(m)
    cells = []
    for week in cal.Calendar(firstweekday=6).monthdatescalendar(year, month):   # השבוע מתחיל ביום ראשון
        row = []
        for d in week:
            chips = ""
            for m in by_day.get(d, []):
                t = ui.local(m["meeting_at"]).strftime("%H:%M")
                if m["past"]:
                    icon, text = presence(m)
                    kind = {"נכח/ה": "ok", "מרחוק": "ok", "נעדר/ה": "bad"}.get(text, "wait")
                else:
                    icon = "?" if m["status"] == "proposed" else "●"
                    kind = "prop" if m["status"] == "proposed" else "next"
                    text = ui.STATUS_HE[m["status"]]
                chips += (f'<div class="chip {kind}" title="{escape(m["forum"] + ": " + m["title"] + " · " + text)}">'
                          f'{icon} {t} {escape(m["forum"])}</div>')
            cls = "out" if d.month != month else ("today" if d == today else "")
            row.append(f'<td class="{cls}"><div class="dn">{d.day}</div>{chips}</td>')
        cells.append("<tr>" + "".join(row) + "</tr>")
    head = "".join(f"<th>{n}</th>" for n in ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"])
    st.html(f"""<style>
    table.cal {{ width:100%; border-collapse:collapse; direction:rtl; table-layout:fixed; }}
    table.cal th {{ background:{ui.NAVY}; color:#fff; padding:6px; font-weight:600; }}
    table.cal td {{ vertical-align:top; height:92px; border:1px solid #E3E8F0; padding:4px; }}
    table.cal td.out {{ background:#F4F6F9; color:#A0A8B5; }}
    table.cal td.today {{ background:#FFF9E8; outline:2px solid {ui.GOLD}; }}
    .dn {{ font-size:.8rem; font-weight:600; }}
    .chip {{ font-size:.75rem; border-radius:6px; padding:2px 5px; margin-top:3px; white-space:nowrap;
             overflow:hidden; text-overflow:ellipsis; cursor:help; }}
    .chip.next {{ background:{ui.NAVY}; color:#fff; }} .chip.prop {{ background:#FDF3D7; color:#8A6A0E; }}
    .chip.ok {{ background:#E3F4EF; color:#0F6B5F; }} .chip.bad {{ background:#FBE3E0; color:#A42A1E; }}
    .chip.wait {{ background:#ECEFF4; color:#555; }}
    </style><table class="cal"><thead><tr>{head}</tr></thead><tbody>{''.join(cells)}</tbody></table>""")
    st.caption("● ישיבה מתוכננת · ? מועד מוצע · ✔ נכחתי · 💻 השתתפתי מרחוק · ✖ נעדרתי · ⏳ ממתין לאישור היו\"ר. "
               "מעבר עכבר על ישיבה מציג את הנושא.")

# ================================================================ ישיבות קרובות
with tab_next:
    if not upcoming:
        st.info("אין ישיבות קרובות.", icon=":material/event_busy:")
    for m in upcoming:
        mid = m["id"]
        items = db.query("SELECT id, position, title, item_type FROM agenda_items WHERE meeting_id = :m "
                         "ORDER BY position", m=mid)
        color = "gold" if m["status"] == "proposed" else ("navy" if m["declaration_signed_at"] and m["rsvp"] else "red")
        with ui.card(f"next-{mid}", color):
            st.markdown(f"### {ui.fmt_date(m['meeting_at'])} · {m['forum']}: {m['title']}")
            st.caption(f"{ui.STATUS_HE[m['status']]} · {ui.MODE_HE[m['mode']]} · {m['location'] or ''}"
                       + ("" if m["is_forum_member"] else " · הוזמנת לנושאים הרלוונטיים לתפקידך"))
            if items:
                st.markdown("**על סדר היום:** " + " · ".join(f"{i['position']}. {i['title']}" for i in items))

            # ---- אישור הגעה, ואם לא מגיעים: סיבה חובה
            c1, c2 = st.columns([3, 2])
            with c1:
                choice = st.segmented_control(
                    "אישור הגעה" if m["status"] != "proposed" else "האם המועד המוצע מתאים לך?",
                    list(RSVP_LABEL), format_func=RSVP_LABEL.get, default=m["rsvp"], key=f"rsvp_{mid}")
                reason = note = None
                if choice == "no":
                    reason = st.selectbox("סיבת ההיעדרות (חובה)", list(REASON_HE), format_func=REASON_HE.get,
                                          index=list(REASON_HE).index(m["absence_reason"]) if m["absence_reason"] else None,
                                          placeholder="בחירת סיבה", key=f"reason_{mid}")
                    note = st.text_input("פירוט" + (" (חובה)" if reason == "other" else " (רשות)"),
                                         value=m["absence_note"] or "", key=f"note_{mid}")
                    st.caption("היו\"ר יקבע אם ההיעדרות מוצדקת. אפשר לצרף אסמכתה (לא רפואית) גם בדיעבד.")
                if st.button("שמירת אישור ההגעה", key=f"save_rsvp_{mid}", icon=":material/save:",
                             disabled=choice is None):
                    if choice == "no" and not reason:
                        st.error("יש לבחור סיבת היעדרות.")
                    elif reason == "other" and not note.strip():
                        st.error("בסיבה \"אחר\" יש לפרט.")
                    else:
                        upsert_attendance(mid, rsvp=choice, rsvp_at=datetime.now(timezone.utc),
                                          absence_reason=reason if choice == "no" else None,
                                          absence_note=(note or "").strip() or None if choice == "no" else None)
                        db.audit(uid, "rsvp", "meeting", mid, RSVP_LABEL[choice] + (f": {REASON_HE[reason]}" if reason else ""))
                        st.toast("אישור ההגעה נשמר.", icon=":material/check_circle:")
                        st.rerun()
            with c2:
                start = m["meeting_at"].astimezone(timezone.utc)
                ics = "\r\n".join([
                    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//SOD Governance//HE", "METHOD:PUBLISH",
                    "BEGIN:VEVENT", f"UID:sod-meeting-{mid}@sod-governance",
                    # מספר גרסה עולה: אם המועד שונה, הורדה מחדש מעדכנת את אותה פגישה ביומן ולא יוצרת כפילות
                    f"SEQUENCE:{int(datetime.now(timezone.utc).timestamp() // 60)}",
                    f"DTSTAMP:{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
                    f"DTSTART:{start:%Y%m%dT%H%M%SZ}", f"DTEND:{start + timedelta(hours=2):%Y%m%dT%H%M%SZ}",
                    f"SUMMARY:{m['forum']}: {m['title']}", f"LOCATION:{m['location'] or ''}",
                    "DESCRIPTION:סדר היום וחומרי הישיבה נמצאים במערכת SOD Governance בלבד.",
                    "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY", "DESCRIPTION:תזכורת לישיבה", "END:VALARM",
                    "END:VEVENT", "END:VCALENDAR"])
                st.download_button("הוספה ליומן האישי (Outlook / Gmail)", ics.encode("utf-8"),
                                   file_name=f"meeting-{mid}.ics", mime="text/calendar",
                                   icon=":material/event_available:", key=f"ics_{mid}", width="stretch")
                st.caption("ביומן האישי נשמרים רק המועד והמקום. החומרים עצמם נשארים במערכת.")

                # ---- הצטרפות מרחוק, רק אחרי קוד אימות
                if m["mode"] in ("remote", "hybrid") and m["status"] == "scheduled":
                    opens = start - timedelta(minutes=30)
                    is_open = DEMO or datetime.now(timezone.utc) >= opens
                    if st.session_state.get(f"joined_{mid}"):
                        st.link_button("כניסה לחדר הישיבה", st.session_state[f"joined_{mid}"],
                                       icon=":material/videocam:", type="primary", width="stretch")
                    elif st.button("הצטרפות מרחוק", key=f"join_{mid}", icon=":material/videocam:",
                                   disabled=not is_open, width="stretch"):
                        st.session_state[f"join_code_{mid}"] = auth.send_otp(uid, "sms")
                    if not is_open:
                        st.caption(f"הכניסה תיפתח ב-{ui.fmt_date(opens)}, 30 דקות לפני הישיבה.")
                    if f"join_code_{mid}" in st.session_state and not st.session_state.get(f"joined_{mid}"):
                        st.info(f"הקוד שנשלח: **{st.session_state[f'join_code_{mid}']}**",
                                title="מצב הדגמה: אין חיבור לשירות SMS", icon=":material/sms:")
                        code = st.text_input("קוד אימות", max_chars=6, key=f"join_in_{mid}")
                        if st.button("אימות וכניסה", key=f"join_ok_{mid}"):
                            ok, err = auth.verify_otp(uid, code, purpose="remote_join_verified")
                            if ok:
                                key = (st.secrets.get("video", {}).get("secret")
                                       or st.secrets["postgres"]["url"]).encode()
                                room = hmac.new(key, f"meeting-{mid}".encode(), hashlib.sha256).hexdigest()[:20]
                                st.session_state[f"joined_{mid}"] = f"https://meet.jit.si/SOD-{room}"
                                del st.session_state[f"join_code_{mid}"]
                                db.audit(uid, "remote_join", "meeting", mid, "הצטרפות מרחוק אחרי קוד אימות")
                                st.rerun()
                            else:
                                st.error(err)

            # ---- טופס הצהרת ניגוד עניינים
            if m["status"] == "proposed":
                continue
            if m["declaration_signed_at"]:
                st.success(f"טופס הצהרת ניגוד העניינים נחתם ב-{ui.fmt_date(m['declaration_signed_at'])}.",
                           icon=":material/verified:")
                continue
            with st.expander("טופס הצהרת ניגוד עניינים: יש לחתום לפני הישיבה", icon=":material/draw:"):
                st.caption("לכל נושא בסדר היום יש לסמן במפורש אם יש לך עניין אישי. "
                           "מי שלא חתם לא יוכל להצביע, ומי שיש לו עניין אישי בנושא לא יצביע עליו.")
                answers, complete = {}, True
                for it in items:
                    ans = st.radio(f"{it['position']}. {it['title']}", ["אין לי עניין אישי", "יש לי עניין אישי"],
                                   index=None, horizontal=True, key=f"coi_{mid}_{it['id']}")
                    details = ""
                    if ans == "יש לי עניין אישי":
                        details = st.text_input("מהו העניין האישי? (חובה)", key=f"coi_d_{mid}_{it['id']}")
                    complete &= ans is not None and (ans == "אין לי עניין אישי" or bool(details.strip()))
                    answers[it["id"]] = {"has_conflict": ans == "יש לי עניין אישי", "details": details.strip() or None}
                read = st.checkbox("קראתי את חומרי הישיבה ואני מצהיר/ה שהפרטים נכונים", key=f"coi_read_{mid}")
                code_key = f"sign_code_{mid}"
                if st.button("שליחת קוד לחתימה", key=f"sign_send_{mid}", icon=":material/sms:",
                             disabled=not (complete and read and items)):
                    st.session_state[code_key] = auth.send_otp(uid, "sms")
                if not items:
                    st.caption("עדיין אין נושאים בסדר היום. הטופס ייפתח כשסדר היום יפורסם.")
                elif not (complete and read):
                    st.caption("יש לענות על כל הנושאים ולאשר את ההצהרה, ואז יישלח קוד לחתימה.")
                if code_key in st.session_state:
                    st.info(f"הקוד שנשלח: **{st.session_state[code_key]}**",
                            title="מצב הדגמה: אין חיבור לשירות SMS", icon=":material/sms:")
                    code = st.text_input("קוד החתימה", max_chars=6, key=f"sign_in_{mid}")
                    if st.button("חתימה על הטופס", key=f"sign_ok_{mid}", type="primary", icon=":material/draw:"):
                        ok, err = auth.verify_otp(uid, code, purpose="declaration_otp_verified")
                        if not ok:
                            st.error(err)
                        else:
                            now = datetime.now(timezone.utc)
                            content = json.dumps({"meeting_id": mid, "user_id": uid, "signed_at": now.isoformat(),
                                                  "materials_acknowledged": True, "items": answers},
                                                 ensure_ascii=False, sort_keys=True)
                            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                            doc = db.one(
                                "INSERT INTO documents (doc_type, meeting_id, filename, stored_path, classification, "
                                "content_sha256, uploaded_by) VALUES ('conflict_declaration', :m, :f, :p, 'confidential', "
                                ":h, :u) RETURNING id", m=mid, f=f"הצהרת ניגוד עניינים - {user['name']}.json",
                                p=f"declarations/m{mid}/user{uid}.json", h=sha, u=uid)
                            for item_id, a in answers.items():
                                db.execute(
                                    "INSERT INTO item_responses (agenda_item_id, user_id, has_conflict, conflict_details) "
                                    "VALUES (:i, :u, :c, :d) ON CONFLICT (agenda_item_id, user_id) DO UPDATE SET "
                                    "has_conflict = EXCLUDED.has_conflict, conflict_details = EXCLUDED.conflict_details, "
                                    "declared_at = now()", i=item_id, u=uid, c=a["has_conflict"], d=a["details"])
                            upsert_attendance(mid, materials_acknowledged=True,
                                              has_personal_interest=any(a["has_conflict"] for a in answers.values()),
                                              signature_otp_verified=True, declaration_document_id=doc["id"],
                                              declaration_signed_at=now)
                            db.audit(uid, "declaration_signed", "meeting", mid, f"SHA-256: {sha}")
                            del st.session_state[code_key]
                            st.toast("הטופס נחתם ונשמר עם חותמת שלמות.", icon=":material/verified:")
                            st.rerun()

# ================================================================ ישיבות שעברו
with tab_past:
    if not past:
        st.info("אין ישיבות קודמות.", icon=":material/history:")
    rows = []
    for m in reversed(past):
        icon, text = presence(m)
        ruling = ""
        if text == "נעדר/ה":
            ruling = ("חסרה סיבת היעדרות" if not m["absence_reason"] else
                      "ממתין להחלטת היו\"ר" if m["absence_justified"] is None else
                      "מוצדקת" if m["absence_justified"] else "לא מוצדקת")
        rows.append({"icon": icon, "when": ui.fmt_date(m["meeting_at"]), "meeting": f"{m['forum']}: {m['title']}",
                     "presence": text, "reason": REASON_HE.get(m["absence_reason"], ""), "ruling": ruling})
    with ui.card("past", "navy"):
        ui.table(rows, {"icon": "", "when": "מועד", "meeting": "ישיבה", "presence": "נוכחות",
                        "reason": "סיבה", "ruling": "החלטת היו\"ר"})
        st.caption("הנוכחות בפועל נקבעת לפי אישור היו\"ר או המזכירות אחרי הישיבה.")

    missing = [m for m in past if presence(m)[1] == "נעדר/ה" and not m["absence_reason"]]
    for m in missing:
        with ui.card(f"late-reason-{m['id']}", "red"):
            st.markdown(f"**חסרה סיבת היעדרות:** {ui.fmt_date(m['meeting_at'])} · {m['forum']}: {m['title']}")
            with st.form(f"late_{m['id']}", border=False):
                reason = st.selectbox("סיבת ההיעדרות", list(REASON_HE), format_func=REASON_HE.get, index=None,
                                      placeholder="בחירת סיבה")
                note = st.text_input("פירוט (חובה בסיבה \"אחר\")")
                if st.form_submit_button("שליחה ליו\"ר", icon=":material/send:"):
                    if not reason or (reason == "other" and not note.strip()):
                        st.error("יש לבחור סיבה, ובסיבה \"אחר\" גם לפרט.")
                    else:
                        upsert_attendance(m["id"], absence_reason=reason, absence_note=note.strip() or None)
                        db.audit(uid, "absence_reason", "meeting", m["id"], REASON_HE[reason])
                        st.rerun()
