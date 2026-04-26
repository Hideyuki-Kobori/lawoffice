"""
昼食ご飯予約システム
--------------------
依存ライブラリ: supabase, pytz
Streamlit Secrets に SUPABASE_URL と SUPABASE_KEY を設定してください。
"""

import streamlit as st
from supabase import create_client
import pandas as pd
from datetime import datetime, timedelta, date
import pytz

st.set_page_config(
    page_title="昼食ご飯予約",
    page_icon="🍚",
    layout="centered",
)

JST      = pytz.timezone("Asia/Tokyo")
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]

@st.cache_resource
def db():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )

@st.cache_data(ttl=20)
def load() -> pd.DataFrame:
    try:
        res = db().table("reservations") \
                  .select("date, user_name, wants_rice") \
                  .execute()
    except Exception as e:
        st.error(f"データの読み込みに失敗しました: {e}")
        return pd.DataFrame(columns=["date", "user_name", "wants_rice"])
    if not res.data:
        return pd.DataFrame(columns=["date", "user_name", "wants_rice"])
    df = pd.DataFrame(res.data)
    df["wants_rice"] = df["wants_rice"].astype(bool)
    return df

def save(date_str: str, user: str, wants: bool) -> None:
    try:
        db().table("reservations").upsert(
            {
                "date":       date_str,
                "user_name":  user,
                "wants_rice": wants,
                "updated_at": datetime.now(JST).isoformat(),
            },
            on_conflict="date,user_name",
        ).execute()
    except Exception as e:
        st.error(f"保存に失敗しました: {e}")
        return
    load.clear()

def rename_user(old_name: str, new_name: str) -> None:
    try:
        db().table("reservations") \
            .update({"user_name": new_name, "updated_at": datetime.now(JST).isoformat()}) \
            .eq("user_name", old_name) \
            .execute()
    except Exception as e:
        st.error(f"名前の変更に失敗しました: {e}")
        return
    load.clear()

def delete_user(user_name: str) -> None:
    try:
        db().table("reservations") \
            .delete() \
            .eq("user_name", user_name) \
            .execute()
    except Exception as e:
        st.error(f"削除に失敗しました: {e}")
        return
    load.clear()

def today() -> date:
    return datetime.now(JST).date()

def upcoming() -> list[date]:
    t = today()
    return [t + timedelta(days=i) for i in range(8)]

def date_label(d: date, is_today: bool) -> str:
    wd = WEEKDAYS[d.weekday()]
    label = f"{d.month}/{d.day}（{wd}）"
    if d.weekday() == 5:
        label = f":blue[{label}]"
    elif d.weekday() == 6:
        label = f":red[{label}]"
    if is_today:
        label += "　← 今日"
    return label

def get_date_data(df: pd.DataFrame, date_str: str) -> dict[str, bool]:
    if df.empty:
        return {}
    sub = df[df["date"] == date_str]
    return {row["user_name"]: bool(row["wants_rice"]) for _, row in sub.iterrows()}

def monthly_summary(df: pd.DataFrame, t: date) -> dict[str, pd.DataFrame]:
    """
    翌月1日以降に表示する月別集計を返す。
    今月分は含めない（月末まで待つ）。
    戻り値: {"2025年4月": DataFrame(user_name, count), ...}
    """
    if df.empty:
        return {}

    # 今月の初日
    this_month_start = t.replace(day=1)

    past = df[df["date"] < this_month_start.isoformat()].copy()
    if past.empty:
        return {}

    past["ym"] = past["date"].str[:7]  # "2025-04"
    result = {}

    for ym in sorted(past["ym"].unique(), reverse=True):
        sub = past[past["ym"] == ym]
        counts = (
            sub[sub["wants_rice"]]
            .groupby("user_name")
            .size()
            .reset_index(name="回数")
            .sort_values("回数", ascending=False)
            .reset_index(drop=True)
        )
        counts.index += 1  # 1始まり
        y, m = ym.split("-")
        label = f"{y}年{int(m)}月"
        result[label] = counts

    return result

# ─── セッション初期化 ────────────────────────────────────────────────────────

if "my_name" not in st.session_state:
    st.session_state.my_name = ""
if "confirm_delete" not in st.session_state:
    st.session_state.confirm_delete = False

# ─── サイドバー ────────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("👤 名前の登録・変更")

    name_input = st.text_input(
        "お名前（20文字以内）",
        value=st.session_state.my_name,
        placeholder="例：山田 太郎",
        max_chars=20,
    )

    if st.button("登録 / 変更", type="primary", use_container_width=True):
        stripped = name_input.strip()
        if not stripped:
            st.error("名前を入力してください")
        elif stripped == st.session_state.my_name:
            st.info("名前は変わっていません")
        elif st.session_state.my_name:
            old = st.session_state.my_name
            rename_user(old, stripped)
            st.session_state.my_name = stripped
            st.success(f"「{old}」→「{stripped}」に変更しました。予約データも引き継がれました")
            st.rerun()
        else:
            st.session_state.my_name = stripped
            st.success(f"「{stripped}」で登録しました ✓")

    st.divider()

    if st.session_state.my_name:
        st.subheader("⚠️ 登録の削除")
        st.caption("自分の名前と予約データをすべて削除します")

        if not st.session_state.confirm_delete:
            if st.button("削除する", use_container_width=True):
                st.session_state.confirm_delete = True
                st.rerun()
        else:
            st.warning(f"「{st.session_state.my_name}」の全データを削除します。よろしいですか？")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("はい、削除", type="primary", use_container_width=True):
                    delete_user(st.session_state.my_name)
                    st.session_state.my_name = ""
                    st.session_state.confirm_delete = False
                    st.success("削除しました")
                    st.rerun()
            with col2:
                if st.button("キャンセル", use_container_width=True):
                    st.session_state.confirm_delete = False
                    st.rerun()

    st.divider()

    if st.button("🔄 データを最新に更新", use_container_width=True):
        load.clear()
        st.rerun()

    st.divider()
    st.caption("名前はこのブラウザ・端末ごとに保存されます。\nスマホからアクセスする場合は再度登録してください。")

# ─── メイン ────────────────────────────────────────────────────────────────────

st.title("🍚 昼食ご飯予約")

my_name: str = st.session_state.my_name

if not my_name:
    st.warning("👈 左のサイドバーからお名前を登録してください")
    st.stop()

st.caption(f"登録名：**{my_name}**　／　自分の行のチェックボックスで登録・変更できます")

df   = load()
t    = today()
all_users: list[str] = sorted(
    set((df["user_name"].tolist() if not df.empty else []) + [my_name])
)

tab_upcoming, tab_past, tab_monthly = st.tabs(
    ["📅 今後の予約（今日 ＋ 7日）", "📂 過去の記録", "📊 月別集計"]
)

# ── 今後の予約 ─────────────────────────────────────────────────────────────────

with tab_upcoming:
    for d in upcoming():
        date_str = d.isoformat()
        is_today = d == t
        dd       = get_date_data(df, date_str)
        count    = sum(1 for v in dd.values() if v)
        header   = f"{'🔵 ' if is_today else ''}{date_label(d, is_today)}　　　🍚 **{count}人**"

        with st.expander(header, expanded=True):
            for user in all_users:
                checked = dd.get(user, False)
                is_me   = user == my_name
                col_cb, col_status = st.columns([5, 2])

                with col_cb:
                    disp = f"**{user}** （あなた）" if is_me else user
                    if is_me:
                        new_val = st.checkbox(
                            disp, value=checked, key=f"cb_{date_str}_{user}"
                        )
                        if new_val != checked:
                            with st.spinner("保存中…"):
                                save(date_str, user, new_val)
                            st.rerun()
                    else:
                        st.checkbox(
                            disp, value=checked, disabled=True,
                            key=f"cb_{date_str}_{user}"
                        )

                with col_status:
                    if checked:
                        st.markdown(
                            '<p style="color:#2D8A4E;font-size:13px;padding-top:6px;margin:0">✅ あり</p>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            '<p style="color:#aaa;font-size:13px;padding-top:6px;margin:0">― なし</p>',
                            unsafe_allow_html=True,
                        )
        st.write("")

# ── 過去の記録 ─────────────────────────────────────────────────────────────────

with tab_past:
    if df.empty:
        st.info("過去のデータはまだありません")
    else:
        past_dates: list[date] = sorted(
            [
                date.fromisoformat(s)
                for s in df["date"].unique()
                if date.fromisoformat(s) < t
            ],
            reverse=True,
        )
        if not past_dates:
            st.info("過去のデータはまだありません")
        else:
            current_ym = ""
            for d in past_dates:
                ym = f"{d.year}年{d.month}月"
                if ym != current_ym:
                    st.subheader(ym)
                    current_ym = ym
                date_str = d.isoformat()
                dd       = get_date_data(df, date_str)
                count    = sum(1 for v in dd.values() if v)
                with st.expander(f"{date_label(d, False)}　　🍚 {count}人"):
                    for user in sorted(dd.keys()):
                        wants = dd[user]
                        color = "#2D8A4E" if wants else "#aaa"
                        icon  = "✅" if wants else "☐"
                        st.markdown(
                            f'<span style="color:{color}">{icon}</span>&nbsp;&nbsp;{user}',
                            unsafe_allow_html=True,
                        )

# ── 月別集計 ──────────────────────────────────────────────────────────────────

with tab_monthly:
    summary = monthly_summary(df, t)

    if not summary:
        st.info(
            f"月別集計は翌月1日以降に表示されます。\n\n"
            f"（現在 {t.year}年{t.month}月 ／ "
            f"{t.year}年{t.month}月分は {t.year if t.month < 12 else t.year+1}年"
            f"{t.month+1 if t.month < 12 else 1}月1日以降に集計されます）"
        )
    else:
        st.caption("先月以前のご飯あり回数の集計です")
        for label, counts in summary.items():
            st.subheader(f"📅 {label}")
            if counts.empty:
                st.write("ご飯ありの記録がありません")
            else:
                counts.columns = ["名前", "ご飯あり（回）"]
                st.dataframe(
                    counts,
                    use_container_width=True,
                    hide_index=False,
                )
            st.divider()
