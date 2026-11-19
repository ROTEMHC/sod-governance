# מסך: היועץ של סוד, סוכן AI לכל דיון (UC-19).
# הסוכן מציג את עצמו, שואל על איזה דיון מדובר, ומחזיר: פערים מהותיים בדוחות, שאלות להנהלה
# ודוחות נוספים ששווה לבקש. כל שאלה ותשובה נשמרות ביומן הפעולות כראיה שהדירקטור בדק ושאל.
import json
from datetime import date, timedelta

import streamlit as st

from board import agent, auth, db, ui

user = st.session_state.user
uid, role = user["id"], user["role"]
sees_all = role in ("admin", "secretary", "chair")

# ---------------------------------------------------------------- הסוכן מציג את עצמו
with st.chat_message("assistant", avatar=":material/psychology:"):
    st.markdown(f"שלום {user['name'].split()[0]}, אני **היועץ של סוד**. "
                "למדתי את הדוחות הכספיים של החברה, כולל הביאורים ודוח הדירקטוריון. "
                "**על איזה דיון מדובר?** אכין לך סקירה: מה הפערים המהותיים שאני רואה בדוחות, "
                "אילו שאלות כדאי לשאול את ההנהלה, ואילו דוחות נוספים כדאי לבקש.")
    st.caption("אני ממליץ בלבד. ההחלטה והאחריות נשארות אצל הדירקטוריון. כל שאלה נשמרת ביומן הפעולות.")

# ---------------------------------------------------------------- בחירת הדיון
access = "" if sees_all else "AND m.id IN (SELECT meeting_id FROM v_meeting_participants WHERE user_id = :u)"
items = db.query(
    "SELECT ai.id, ai.meeting_id, ai.position, ai.title, ai.item_type, ai.summary, ai.decision_required, "
    "ai.alternatives, ai.no_go_option, ai.risks, ai.negative_scenario, m.title AS meeting, m.meeting_at, "
    "f.name AS forum FROM agenda_items ai JOIN meetings m ON m.id = ai.meeting_id "
    "JOIN forums f ON f.id = m.forum_id WHERE m.status <> 'cancelled' " + access +
    " ORDER BY (m.meeting_at < now()), abs(extract(epoch FROM (m.meeting_at - now()))), ai.position", u=uid)
GENERAL = 0
item_id = st.selectbox(
    "על איזה דיון מדובר?", [GENERAL] + [i["id"] for i in items],
    format_func=lambda i: "שאלה כללית על הדוחות הכספיים" if i == GENERAL else next(
        f"{x['forum']}, {ui.fmt_date(x['meeting_at'].date())}: {x['position']}. {x['title']}" for x in items if x["id"] == i))
item = next((x for x in items if x["id"] == item_id), None)

if item:
    with ui.card("agent-item", "navy"):
        st.markdown(f"**{item['title']}** · {item['forum']}: {item['meeting']}")
        if item["decision_required"]:
            st.caption(f"ההחלטה הנדרשת: {item['decision_required']}")

state_key = f"agent_{item_id}"
state = st.session_state.setdefault(state_key, {"brief": None, "pages": [], "chat": []})


def log(question: str, answer: str):
    db.audit(uid, "ai_question", "agenda_item" if item else None, item["id"] if item else None,
             f"שאלה: {question[:400]} | תשובה: {answer[:1200]}")


def request_report(r: dict) -> str:
    """בקשת דוח שהסוכן המליץ עליו: נפתחת בקשה רגילה לסמנכ"ל הכספים, עם הנימוק של הסוכן."""
    cfo = db.one("SELECT id, name FROM users WHERE role = 'cfo' AND active ORDER BY id LIMIT 1")
    due, days = date.today(), db.setting_int("request_due_default_days", 5)
    while days:
        due += timedelta(days=1)
        days -= due.weekday() not in (4, 5)
    row = db.one("INSERT INTO document_requests (requested_by, assigned_to, title, period, reason, due_date, meeting_id) "
                 "VALUES (:by, :to, :t, :p, :r, :d, :m) RETURNING id",
                 by=uid, to=cfo["id"], t=r["title"], p=r["period"] or None,
                 r=f"בהמלצת היועץ של סוד: {r['why']}", d=due, m=item["meeting_id"] if item else None)
    db.audit(uid, "request_submitted", "document_request", row["id"], f"{r['title']} (בהמלצת הסוכן)")
    return f"הבקשה \"{r['title']}\" נשלחה ל{cfo['name']}, עם מועד מענה {ui.fmt_date(due)}."


# ---------------------------------------------------------------- מצב בלי מפתח API: ניתוח לפי כללים, לכל דיון בנפרד
online = agent.available()
if not online:
    st.caption(":material/key: הסוכן פועל במצב מצומצם, בלי מודל שפה: הסקירה נבנית לפי נושא הדיון, תבנית החובה "
               "והקטעים הרלוונטיים בדוחות. שיחה חופשית זמינה אחרי הגדרת מפתח API.")
    conflicts = db.one("SELECT count(*) AS n FROM item_responses WHERE agenda_item_id = :i AND has_conflict",
                       i=item["id"])["n"] if item else 0
    state["brief"], state["pages"] = agent.offline_brief(item, conflicts)

# ---------------------------------------------------------------- סקירה לדיון
if online and st.button("הכנת סקירה לדיון", type="primary", icon=":material/auto_awesome:"):
    with st.spinner("קורא את הדוחות והביאורים הרלוונטיים..."):
        try:
            state["brief"], state["pages"] = agent.brief(item)
            log("סקירה לדיון", json.dumps(state["brief"], ensure_ascii=False))
        except Exception as e:   # שירות ה-AI אינו זמין: שאר המערכת ממשיכה לפעול
            st.error(f"הסוכן אינו זמין כרגע ({type(e).__name__}). אפשר לנסות שוב בעוד כמה דקות.")

b = state["brief"]
if b:
    with st.chat_message("assistant", avatar=":material/psychology:"):
        st.markdown(b["summary"])
    if b["gaps"]:
        st.markdown("#### :material/search_insights: פערים מהותיים שאני רואה בדוחות")
        cols = st.columns(min(len(b["gaps"]), 3))
        for i, g in enumerate(b["gaps"]):
            with cols[i % len(cols)], ui.card(f"gap-{i}", "red"):
                st.markdown(f"**{g['title']}**")
                st.write(g["detail"])
                st.caption(f"מקור: {g['source']}")
    st.markdown("#### :material/quiz: שאלות מומלצות להנהלה")
    with ui.card("ai-questions", "gold"):
        for q in b["questions"]:
            st.markdown(f"- {q}")
    if b["reports"]:
        st.markdown("#### :material/request_quote: דוחות נוספים ששווה לבקש")
        for i, r in enumerate(b["reports"]):
            with ui.card(f"ai-report-{i}"):
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown(f"**{r['title']}** ({r['period']})  \n{r['why']}")
                    if auth.can(user, "submit_request"):
                        if st.button("לבקש את הדוח", key=f"req_{item_id}_{i}", icon=":material/send:"):
                            st.success(request_report(r), icon=":material/check_circle:")
    with st.expander(f"קטעים רלוונטיים מהדוחות ({len(state['pages'])} עמודים)", icon=":material/menu_book:"):
        for p in state["pages"]:
            st.markdown(f"**{p['source']}, עמוד {p['page']}**")
            if p.get("snippet"):
                st.caption(p["snippet"])

if not online:
    st.stop()

# ---------------------------------------------------------------- שיחה חופשית
st.markdown("#### :material/forum: שאלות נוספות")
for msg in state["chat"]:
    with st.chat_message(msg["role"], avatar=":material/psychology:" if msg["role"] == "assistant" else None):
        st.markdown(msg["content"])
question = st.chat_input("למשל: למה הוצאות המימון עלו? האם המלאי מוערך נכון?")
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant", avatar=":material/psychology:"):
        try:
            answer = st.write_stream(agent.chat_stream(item, state["chat"], question))
        except Exception as e:
            answer = f"הסוכן אינו זמין כרגע ({type(e).__name__})."
            st.error(answer)
    state["chat"] += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    log(question, answer)
