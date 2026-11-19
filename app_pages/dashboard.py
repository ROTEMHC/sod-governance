# מסך 8: דשבורד כספי (UC-18). מדדים מסכמים, השוואה לשנה הקודמת ורמזור דגלים אדומים.
# הדשבורד מציג מדדים מסכמים בלבד. לדוח מפורט הדירקטור מגיש בקשה (UC-23).
import altair as alt
import pandas as pd
import streamlit as st

from board import financials as fin
from board import ui

st.caption(f"לקוח הפיילוט: סל הארץ קמעונאות בע\"מ · שנת 2025 מול 2024 · במיליוני ש\"ח  \n"
           f"מקור הנתונים: {fin.SOURCE}")

# ---------------------------------------------------------------- מדדים עיקריים
with st.container(horizontal=True):
    for key, icon in (("sales", ":material/payments:"), ("gross_profit", ":material/trending_up:"),
                      ("operating_profit", ":material/factory:"), ("net_profit", ":material/savings:"),
                      ("cfo", ":material/account_balance_wallet:")):
        with st.container(key=f"kpi-fin-{key}"):
            note = fin.NOTES.get(key)
            st.metric(fin.LABELS[key], f"{fin.v(key):,.0f}", f"{fin.growth(key):+.1%}", icon=icon,
                      help=f"**{note[0]}:** {note[1]}" if note else None)

# ---------------------------------------------------------------- מגמה רבעונית: עונתיות או מגמה מתמשכת?
st.subheader(":material/show_chart: מגמה לפי רבעונים: עלייה עונתית או מגמה מתמשכת?")
with ui.card("quarters", "navy"):
    Q = fin.QUARTERS
    names = list(Q)
    q_sel = st.segmented_control("רבעון לניתוח", names, default=names[-1], required=True, key="q_sel")
    k_sel = names.index(q_sel)
    METRICS = {"sales": "מכירות", "gross_profit": "רווח גולמי", "opex": "הוצאות מכירה והנהלה",
               "operating_profit": "רווח תפעולי", "finance_net": "הוצאות מימון", "net_profit": "רווח נקי"}

    def val(d, k):
        return d["selling"] + d["admin"] if k == "opex" else d[k]

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**מכירות ורווח גולמי לפי רבעון**")
        rows = [{"רבעון": q, "מדד": METRICS[k], "סכום": val(Q[q], k)} for q in names for k in ("sales", "gross_profit")]
        rows += [{"רבעון": "Q4 2024", "מדד": METRICS[k], "סכום": val(fin.Q4_2024, k)} for k in ("sales", "gross_profit")]
        order = ["Q4 2024"] + names
        line = (alt.Chart(pd.DataFrame(rows)).mark_line(point=alt.OverlayMarkDef(size=70), strokeWidth=3)
                .encode(x=alt.X("רבעון:N", sort=order, title=None, axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("סכום:Q", title="מיליוני ש\"ח"),
                        color=alt.Color("מדד:N", scale=alt.Scale(range=[ui.NAVY, ui.TEAL]),
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=["רבעון", "מדד", alt.Tooltip("סכום:Q", format=",.1f")])
                .properties(height=280))
        st.altair_chart(line, alt="מכירות ורווח גולמי לפי רבעון")
    with c2:
        st.markdown(f"**עלה או ירד: {q_sel} מול " + (f"{names[k_sel - 1]}**" if k_sel else "Q4 2024**"))
        prev = Q[names[k_sel - 1]] if k_sel else fin.Q4_2024
        cur = Q[q_sel]
        rows = []
        for k, label in METRICS.items():
            ch = val(cur, k) - val(prev, k)
            good = ch < 0 if k in ("opex", "finance_net") else ch > 0     # עלייה בהוצאה = רע
            rows.append({"מדד": label, "שינוי": ch, "כיוון": "לטובה" if good else "לרעה"})
        bars = (alt.Chart(pd.DataFrame(rows)).mark_bar(cornerRadiusEnd=4)
                .encode(y=alt.Y("מדד:N", sort=None, title=None),
                        x=alt.X("שינוי:Q", title="שינוי במיליוני ש\"ח"),
                        color=alt.Color("כיוון:N", scale=alt.Scale(domain=["לטובה", "לרעה"], range=[ui.TEAL, "#C0392B"]),
                                        legend=alt.Legend(orient="top", title=None)),
                        tooltip=["מדד", alt.Tooltip("שינוי:Q", format="+,.1f")])
                .properties(height=280))
        st.altair_chart(bars, alt="שינוי בכל מדד מול הרבעון הקודם")

    # השוואה לרבעון הקודם מול השוואה לרבעון המקביל אשתקד: זה מה שמפריד בין עונתיות למגמה
    same_q = fin.Q4_2024 if q_sel == "Q4 2025" else None
    table_rows = []
    for k, label in METRICS.items():
        c, p = val(cur, k), val(prev, k)
        row = {"m": label, "cur": f"{c:,.1f}", "pct": f"{c / cur['sales']:.2%}",
               "qoq": f"{c / p - 1:+.1%}" if p else ""}
        if same_q:
            row["yoy"] = f"{c / val(same_q, k) - 1:+.1%}"
        table_rows.append(row)
    ui.table(table_rows, {"m": "מדד", "cur": q_sel, "pct": "% מהמכירות", "qoq": "מול הרבעון הקודם",
                          "yoy": "מול הרבעון המקביל אשתקד"})
    st.caption("**איך מזהים עונתיות:** שינוי מול הרבעון הקודם מושפע מהעונה (למשל חגים, או סופגניות בחנוכה). "
               "שינוי מול **אותו רבעון בשנה הקודמת** מנטרל את העונה: אם גם שם יש עלייה, זו מגמה מתמשכת. "
               + ("" if same_q else "להשוואה לרבעון המקביל ב-2024 יש להוסיף את הדוח התקופתי לשנת 2024."))
    if q_sel in fin.Q_EXPLAIN:
        st.markdown("**:material/psychology: מה גרם לשינוי (לפי הסברי הדירקטוריון)**")
        for line in fin.Q_EXPLAIN[q_sel]:
            st.markdown(f"- {line}")
    else:
        st.caption("הסברי ההנהלה לרבעון זה מופיעים בדוח הרבעוני. אפשר לשאול עליהם את היועץ של סוד.")
    st.caption(":material/info: תזרים מזומנים רבעוני ונתונים חודשיים או לפי קטגוריה (למשל מאפים) אינם מפורסמים "
               "בדוחות הציבוריים. במערכת אצל הלקוח הם נמשכים ממערכת ה-ERP (פריוריטי), לפי הרשאה.")

# ---------------------------------------------------------------- רמזור
LEVEL = {"red": ("card-red", ":material/error:", "אדום"), "yellow": ("card-gold", ":material/warning:", "צהוב"),
         "green": ("card", ":material/check_circle:", "ירוק")}
st.subheader("רמזור: דגלים לדיון בדירקטוריון")
cols = st.columns(len(fin.red_flags()))
for i, (col, f) in enumerate(zip(cols, fin.red_flags())):
    color = {"red": "red", "yellow": "gold", "green": "teal"}[f["level"]]
    with col, ui.card(f"flag-{i}", color):
        st.markdown(f"{LEVEL[f['level']][1]} **{f['title']}**")
        st.caption(f["detail"])
        st.markdown(f"**שאלה להנהלה:** {f['question']}")

# ---------------------------------------------------------------- ניתוח הסוכן: למה הרווח ירד?
st.subheader(":material/psychology: ניתוח הסוכן: המכירות עלו, למה הרווח ירד?")
with ui.card("agent", "gold"):
    chart_col, text_col = st.columns([3, 2])
    with chart_col:
        bridge = pd.DataFrame(fin.profit_bridge())
        waterfall = (alt.Chart(bridge)
                     .mark_bar(size=34, cornerRadius=3)
                     .encode(x=alt.X("שלב:N", sort=None, title=None,
                                     axis=alt.Axis(labelAngle=-30, labelLimit=140)),
                             y=alt.Y("מ:Q", title="מיליוני ש\"ח"),
                             y2="עד:Q",
                             color=alt.Color("סוג:N", legend=alt.Legend(orient="top", title=None),
                                             scale=alt.Scale(domain=["סה\"כ", "תוספת", "גריעה"],
                                                             range=[ui.NAVY, ui.TEAL, "#C0392B"])),
                             tooltip=["שלב", alt.Tooltip("סכום:Q", format="+,.1f")])
                     .properties(height=340))
        labels = waterfall.mark_text(dy=-8, fontWeight="bold").encode(
            y="עד:Q", text=alt.Text("סכום:Q", format=",.0f"), color=alt.value("#1F2A44"))
        st.altair_chart(waterfall + labels,
                        alt="גשר רווח נקי מ-2024 ל-2025: מה הוסיף ומה גרע מהרווח")
        st.caption("גשר רווח: מתחילים ברווח הנקי של 2024, מוסיפים ומחסרים כל שינוי, ומגיעים לרווח של 2025.")
    with text_col:
        for line in fin.agent_explanation():
            st.markdown(f"- {line}")
    st.markdown("**:material/quiz: שאלות שהסוכן ממליץ לשאול את ההנהלה**")
    for q in fin.agent_questions():
        st.markdown(f"- {q}")
    st.caption("הסוכן ממליץ בלבד: ההחלטה והאחריות נשארות אצל הדירקטוריון. כל ממצא מבוסס על הדוחות הכספיים "
               "ומפנה לביאור. לדוח מפורט, למשל קניות לפי ספק, מגישים בקשה במסך \"בקשות לדוחות\".")

# ---------------------------------------------------------------- גרפים
left, right = st.columns(2)
with left, ui.card("chart-pl", "navy"):
    st.markdown("**רווחיות: 2025 מול 2024**")
    rows = [{"מדד": fin.LABELS[k], "שנה": str(y), "סכום": fin.DATA[k][y]}
            for k in ("gross_profit", "operating_profit", "net_profit", "cfo") for y in fin.YEARS]
    chart = (alt.Chart(pd.DataFrame(rows))
             .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
             .encode(x=alt.X("מדד:N", sort=None, title=None, axis=alt.Axis(labelAngle=0)),
                     xOffset="שנה:N",
                     y=alt.Y("סכום:Q", title="מיליוני ש\"ח"),
                     color=alt.Color("שנה:N", scale=alt.Scale(range=["#9DB4D6", ui.NAVY]),
                                     legend=alt.Legend(orient="top", title=None)),
                     tooltip=["מדד", "שנה", alt.Tooltip("סכום:Q", format=",.1f")])
             .properties(height=300))
    st.altair_chart(chart, alt="השוואת רווח גולמי, תפעולי, נקי ותזרים בין 2024 ל-2025")

with right, ui.card("chart-growth", "gold"):
    st.markdown("**שיעור השינוי: הון חוזר מול מכירות**")
    rows = [{"רכיב": fin.LABELS[k], "שינוי": fin.growth(k)}
            for k in ("sales", "receivables", "inventory", "payables", "net_profit", "cash")]
    df = pd.DataFrame(rows)
    sales_growth = fin.growth("sales")
    df["מצב"] = ["חריג" if g > sales_growth * 2 else "ירידה" if g < 0 else "תקין" for g in df["שינוי"]]
    chart = (alt.Chart(df)
             .mark_bar(cornerRadiusEnd=4)
             .encode(y=alt.Y("רכיב:N", sort=None, title=None),
                     x=alt.X("שינוי:Q", axis=alt.Axis(format="%"), title="שינוי 2025 מול 2024"),
                     color=alt.Color("מצב:N", legend=alt.Legend(orient="top", title=None),
                                     scale=alt.Scale(domain=["תקין", "ירידה", "חריג"],
                                                     range=[ui.TEAL, ui.GOLD, "#C0392B"])),
                     tooltip=["רכיב", alt.Tooltip("שינוי:Q", format="+.1%")])
             .properties(height=300))
    st.altair_chart(chart, alt="שיעור השינוי במכירות, לקוחות, מלאי, ספקים, רווח נקי ומזומנים")
    st.caption("באדום: רכיב שגדל יותר מפי 2 מקצב המכירות.")

# ---------------------------------------------------------------- דוחות מתומצתים עם ביאורים
STATEMENT_COLS = {"item": "סעיף", "y25": "2025", "p25": "% 2025", "y24": "2024", "p24": "% 2024",
                  "chg": "שינוי", "note": "ביאור"}
with ui.card("pl-statement", "navy"):
    st.markdown("**רווח והפסד מתומצת** · אחוז מהמכירות")
    ui.table(fin.statement_rows(["sales", "cogs", "gross_profit", "operating_profit", "net_profit", "cfo"], "sales"),
             STATEMENT_COLS)
with ui.card("bs-statement", "navy"):
    st.markdown("**מאזן מתומצת** · אחוז מסך הנכסים")
    ui.table(fin.statement_rows(["cash", "receivables", "inventory", "current_assets", "payables",
                                 "current_liabilities", "equity", "total_assets"], "total_assets"),
             STATEMENT_COLS)
st.caption("במיליוני ש\"ח. מעבר עם העכבר על ⓘ בעמודת \"ביאור\" מציג את תמצית הביאור בדוחות הכספיים.")

# ---------------------------------------------------------------- יחסים פיננסיים
r24, r25 = fin.ratios(2024), fin.ratios(2025)
with ui.card("ratios"):
    st.markdown("**יחסים פיננסיים**")
    pct = lambda x: f"{x:.2%}"
    num = lambda x: f"{x:.2f}"
    ui.table([
        {"name": "שולי רווח גולמי", "y25": pct(r25["gross_margin"]), "y24": pct(r24["gross_margin"]),
         "how": "רווח גולמי חלקי מכירות"},
        {"name": "שולי רווח תפעולי", "y25": pct(r25["operating_margin"]), "y24": pct(r24["operating_margin"]),
         "how": "רווח תפעולי חלקי מכירות"},
        {"name": "שולי רווח נקי", "y25": pct(r25["net_margin"]), "y24": pct(r24["net_margin"]),
         "how": "רווח נקי חלקי מכירות"},
        {"name": "יחס שוטף", "y25": num(r25["current_ratio"]), "y24": num(r24["current_ratio"]),
         "how": "נכסים שוטפים חלקי התחייבויות שוטפות"},
        {"name": "יחס מהיר", "y25": num(r25["quick_ratio"]), "y24": num(r24["quick_ratio"]),
         "how": "נכסים שוטפים בניכוי מלאי, חלקי התחייבויות שוטפות"},
        {"name": "הון למאזן", "y25": pct(r25["equity_ratio"]), "y24": pct(r24["equity_ratio"]),
         "how": "הון חלקי סך הנכסים"},
        {"name": "ימי מלאי", "y25": f"{fin.inventory_days():.1f}", "y24": "",
         "how": "ממוצע המלאי חלקי עלות המכר, כפול 365"},
        {"name": "ימי לקוחות", "y25": f"{fin.customer_days():.1f}", "y24": "",
         "how": "ממוצע הלקוחות חלקי המכירות, כפול 365"},
    ], {"name": "יחס", "y25": "2025", "y24": "2024", "how": "איך מחשבים"})

st.info("הדשבורד מציג מדדים מסכמים בלבד. לדוח מפורט, למשל גיול לקוחות או הרכב המלאי, "
        "מגישים בקשה במסך \"בקשות לדוחות\", והדוח יוצג לכל חברי הפורום.",
        icon=":material/request_quote:")
