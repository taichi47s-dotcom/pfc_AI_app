import streamlit as st
import pandas as pd
from datetime import date, timedelta
from streamlit_gsheets import GSheetsConnection
from google import genai
import json
import time

# ==========================================
# 1. 接続・ページ設定・CSS
# ==========================================
try:
    client = genai.Client(api_key=st.secrets["gemini_api_key"])
    conn = st.connection("gsheets", type=GSheetsConnection)
except Exception as e:
    st.error("接続エラー: .streamlit/secrets.toml を確認してください。")
    st.stop()

st.set_page_config(page_title="PFC Tracker", layout="centered", initial_sidebar_state="expanded")

st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;700&family=Quicksand:wght@400;700&display=swap" rel="stylesheet">
<style>
    [data-testid="stStatusWidget"] { visibility: hidden; }
            
    /* 読み込み用スピナーのカスタマイズ */
    div[data-testid="stSpinner"] > div {
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background-color: rgba(0, 0, 0, 0.5); z-index: 9999;
        display: flex; align-items: center; justify-content: center; color: white;
    }
            
    /* 【新規】中央ポップアップ（褒め言葉用） */
    .praise-overlay {
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background-color: rgba(0, 0, 0, 0.7); z-index: 10000;
        display: flex; align-items: center; justify-content: center;
        flex-direction: column;
    }
    .praise-card {
        background: white; padding: 40px; border-radius: 25px;
        color: #5D4037; text-align: center; border: 4px solid #E6CFCF;
        max-width: 80%; box-shadow: 0 10px 25px rgba(0,0,0,0.2);
    }
            
    html, body, [data-testid="stAppViewContainer"] {
        font-family: 'Quicksand', 'Noto Sans JP', sans-serif;
        background-color: #FDFCF5; font-size: 0.9rem;
    }
    [data-testid="stHorizontalBlock"] { display: flex !important; flex-direction: row !important; flex-wrap: nowrap !important; gap: 8px !important; }
    [data-testid="column"] { flex: 1 1 0% !important; min-width: 0px !important; }
    div[data-testid="metric-container"] { background-color: #FFFFFF; border: 1px solid #F3E5DC; padding: 12px; border-radius: 15px; }
    div[data-testid="stMetricValue"] { font-size: 1.1rem !important; font-weight: 700 !important; }
    .stTextArea textarea { border: 2px solid #E6CFCF !important; background-color: #FFFFFF !important; border-radius: 15px !important; font-size: 1.0rem !important; }
    .stButton>button { border-radius: 12px !important; font-weight: 700; }
    form[data-testid="stForm"], div[data-testid="stVerticalBlockBorderWrapper"] { background-color: #FFFFFF; border: 1px solid #F3E5DC; border-radius: 15px; padding: 15px; }
    .dot-container { display: flex; flex-wrap: wrap; gap: 4px; padding: 10px; background: white; border-radius: 12px; border: 1px solid #F3E5DC; }
    .dot { width: 12px; height: 12px; border-radius: 2px; }
    .dot-none { background-color: #EBEDF0; }
    .dot-logged { background-color: #E6CFCF; }
    .dot-success { background-color: #A1887F; }
    .calc-text { font-size: 0.8rem; color: #8D6E63; margin-top: 5px; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. ユーザー管理とURL同期
# ==========================================
query_user = st.query_params.get("user", "default_user")
st.sidebar.title("👤 ユーザー管理")
user_id = st.sidebar.text_input("ユーザー名を入力", value=query_user)

if user_id != query_user:
    st.query_params["user"] = user_id
    st.rerun()

@st.cache_data(ttl="0s")
def load_full_data():
    # 記録データ (Sheet1)
    try:
        df = conn.read(worksheet="Sheet1")
        if df is None or df.empty or 'user' not in df.columns:
            df = pd.DataFrame(columns=['user', 'date', 'name', 'p', 'f', 'c', 'kcal'])
        else:
            df['date'] = pd.to_datetime(df['date']).dt.date
    except Exception:
        df = pd.DataFrame(columns=['user', 'date', 'name', 'p', 'f', 'c', 'kcal'])
    
    # ユーザー設定データ (settings)
    try:
        sdf = conn.read(worksheet="settings")
        # ★ここが重要：'user'列がない場合は強制的に列を持ったデータフレームを作る
        if sdf is None or sdf.empty or 'user' not in sdf.columns:
            sdf = pd.DataFrame(columns=['user', 'mode', 'p', 'f', 'c'])
    except Exception:
        sdf = pd.DataFrame(columns=['user', 'mode', 'p', 'f', 'c'])
    
    return df, sdf

all_df, settings_df = load_full_data()
user_meals = all_df[all_df['user'] == user_id]

# ==========================================
# 3. 【新機能】中央ポップアップ褒め言葉
# ==========================================
# ==========================================
# 3. 中央ポップアップ（ダイアログ）の設定
# ==========================================
# 1. まず「箱（関数）」を定義する
@st.dialog("✨ Great! ✨")
def show_praise_dialog(message):
    st.markdown(f"<p style='font-size:1.3rem; font-weight:bold; text-align:center;'>{message}</p>", unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    
    # このボタンがダイアログ内に表示されます
    if st.button("OK！記録を続ける", type="primary", use_container_width=True):
        st.session_state.diet_message = ""  # メッセージを消去
        st.rerun()  # 画面を更新してダイアログを閉じる

# 2. セッションステートにメッセージがある場合のみ、上の関数を呼び出す
if "diet_message" in st.session_state and st.session_state.diet_message:
    show_praise_dialog(st.session_state.diet_message)
# ==========================================
# 3. データ読み込み (記録用と設定用)
# ==========================================
@st.cache_data(ttl="0s")
def load_full_data():
    # 記録データ (Sheet1)
    df = conn.read(worksheet="Sheet1")
    if df is None or df.empty:
        df = pd.DataFrame(columns=['user', 'date', 'name', 'p', 'f', 'c', 'kcal'])
    else:
        df['date'] = pd.to_datetime(df['date']).dt.date
    
    # ユーザー設定データ (settings)
    try:
        sdf = conn.read(worksheet="settings")
    except Exception:
        sdf = pd.DataFrame(columns=['user', 'mode', 'p', 'f', 'c'])
    
    return df, sdf

all_df, settings_df = load_full_data()
user_meals = all_df[all_df['user'] == user_id]

# ==========================================
# 4. サイドバー：ユーザー設定（目標PFC）
# ==========================================
user_setting = settings_df[settings_df['user'] == user_id]
if not user_setting.empty:
    init_mode = user_setting.iloc[0]['mode']
    init_p = float(user_setting.iloc[0]['p'])
    init_f = float(user_setting.iloc[0]['f'])
    init_c = float(user_setting.iloc[0]['c'])
else:
    init_mode, init_p, init_f, init_c = "増量", 160.0, 90.0, 410.0

st.sidebar.markdown("---")
mode = st.sidebar.radio("モード選択", ["増量", "減量"], index=0 if init_mode=="増量" else 1)
gp = st.sidebar.number_input("目標 P", value=init_p)
gf = st.sidebar.number_input("目標 F", value=init_f)
gc = st.sidebar.number_input("目標 C", value=init_c)
gk = float(gp * 4 + gf * 9 + gc * 4)

if st.sidebar.button("この目標をユーザーに紐付けて保存"):
    new_s = pd.DataFrame([[user_id, mode, gp, gf, gc]], columns=['user', 'mode', 'p', 'f', 'c'])
    other_s = settings_df[settings_df['user'] != user_id]
    conn.update(worksheet="settings", data=pd.concat([other_s, new_s], ignore_index=True))
    st.sidebar.success("設定を保存しました")
    st.cache_data.clear()
    st.rerun()

if st.sidebar.button("全データをリセット", type="secondary"):
    conn.update(worksheet="Sheet1", data=pd.DataFrame(columns=['user', 'date', 'name', 'p', 'f', 'c', 'kcal']))
    st.cache_data.clear()
    st.rerun()

# ==========================================
# 5. メイン画面：継続状況
# ==========================================
daily = user_meals.groupby('date')['kcal'].sum()
streak, chk = 0, date.today()
while chk in daily.index:
    streak += 1
    chk -= timedelta(days=1)

st.title("PFC Tracker")
st.markdown(f"**🔥 {user_id} さん: {streak} 日間連続記録中**")

dot_html = '<div class="dot-container">'
for i in range(27, -1, -1):
    d = date.today() - timedelta(days=i)
    v = daily.get(d, 0)
    s = "none"
    if v >= 1300:
        s = "logged"
        if (mode == "増量" and v >= gk) or (mode == "減量" and v <= gk):
            s = "success"
    dot_html += f'<div class="dot dot-{s}" title="{d}"></div>'
dot_html += '</div>'
st.markdown(dot_html, unsafe_allow_html=True)

# ==========================================
# 6. AI自動入力（バックオフ＆クリア機能）
# ==========================================
st.markdown("<br>", unsafe_allow_html=True)
st.subheader("何を食べましたか？")

if "ai_input" not in st.session_state:
    st.session_state.ai_input = ""

ai_q = st.text_area(
    "内容", 
    value=st.session_state.ai_input,
    placeholder="例: ごはん100g, 鶏肉200g", 
    height=100,
    label_visibility="collapsed"
)

col_btn1, col_btn2 = st.columns([1, 1])

if col_btn1.button("AIで自動入力・保存", type="primary", use_container_width=True):
    if ai_q:
        max_retries = 3
        success = False
        for i in range(max_retries):
            try:
                with st.spinner(f"AI解析中... (試行 {i+1}/{max_retries})"):
                    prompt = f"""
                    「{ai_q}」のPFCバランス(g)を推測し、以下のJSON形式でのみ出力してください。
                    ダイエット向きの優れた内容（高タンパク・低脂質など）であれば「is_diet」をtrueにし、「message」に短い褒め言葉（20文字以内）を入れてください。
                    形式: {{"P": 0.0, "F": 0.0, "C": 0.0, "is_diet": true, "message": "ダイエットに適した食事です！"}}
                    """
                    res = client.models.generate_content(model='gemini-flash-latest', contents=prompt)
                    
                    json_str = res.text[res.text.find('{'):res.text.rfind('}')+1]
                    d = json.loads(json_str)
                    # AIの判定結果を受け取り、session_stateに保存する処理を追加
                    if d.get("is_diet") and d.get("message"):
                        st.session_state.diet_message = d.get("message")
                    
                    p, f, c = float(d.get("P", 0)), float(d.get("F", 0)), float(d.get("C", 0))
                    calc_k = (p * 4) + (f * 9) + (c * 4)
                    
                    new_row = pd.DataFrame([[user_id, date.today(), ai_q.replace('\n', ' '), p, f, c, calc_k]], columns=['user', 'date', 'name', 'p', 'f', 'c', 'kcal'])
                    conn.update(worksheet="Sheet1", data=pd.concat([all_df, new_row], ignore_index=True))
                    
                    st.session_state.ai_input = ""
                    success = True
                    break
            except Exception as e:
                if i < max_retries - 1:
                    time.sleep((2 ** i) + 1)
                else:
                    st.error(f"エラーが発生しました: {e}")
        
        if success:
            st.cache_data.clear()
            st.rerun()

if col_btn2.button("直近の記録を取り消す", type="secondary", use_container_width=True):
    if not user_meals.empty:
        last_idx = user_meals.index[-1]
        conn.update(worksheet="Sheet1", data=all_df.drop(last_idx))
        st.cache_data.clear()
        st.rerun()

# ==========================================
# 7. 運動の入力
# ==========================================
st.subheader("運動の入力")
with st.form("exercise_form"):
    ei1, ei2 = st.columns(2)
    w_min = ei1.number_input("筋トレ (分)", value=0.0, step=1.0)
    a_kcal = ei2.number_input("有酸素 (kcal)", value=0.0, step=1.0)
    burned = (1.05 * 3.5 * 70.0 * (w_min / 60.0)) + a_kcal
    st.markdown(f'<div class="calc-text">合計消費見込：<b>{burned:.1f} kcal</b></div>', unsafe_allow_html=True)
    
    if st.form_submit_button("運動を記録", use_container_width=True):
        if burned > 0:
            ex_n = [f"筋トレ:{int(w_min)}分" if w_min > 0 else "", f"有酸素:{int(a_kcal)}kcal" if a_kcal > 0 else ""]
            ex_row = pd.DataFrame([[user_id, date.today(), " + ".join([n for n in ex_n if n]), 0.0, 0.0, 0.0, -burned]], columns=['user', 'date', 'name', 'p', 'f', 'c', 'kcal'])
            conn.update(worksheet="Sheet1", data=pd.concat([all_df, ex_row], ignore_index=True))
            st.cache_data.clear()
            st.rerun()

# ==========================================
# 8. 今日の状況
# ==========================================
today = date.today()
td = user_meals[user_meals['date'] == today]
tp, tf, tc, tk = td['p'].sum(), td['f'].sum(), td['c'].sum(), td['kcal'].sum()

st.markdown("<br>", unsafe_allow_html=True)
st.subheader("今日の状況")
st.metric("残りカロリー", f"{int(gk - tk)} kcal", delta=f"目標 {int(gk)}", delta_color="off")
c1, c2, c3 = st.columns(3)
c1.metric("残り P", f"{gp - tp:.1f}g")
c2.metric("残り F", f"{gf - tf:.1f}g")
c3.metric("残り C", f"{gc - tc:.1f}g")

# ==========================================
# 9. 履歴と選択削除
# ==========================================
if not user_meals.empty:
    st.markdown("---")
    st.subheader("履歴と編集")
    display_df = user_meals.copy()
    display_df.insert(0, "選択", False)
    
    edited_df = st.data_editor(
        display_df.sort_values(['date', 'name'], ascending=[False, True]),
        column_config={"選択": st.column_config.CheckboxColumn(required=True)},
        disabled=[c for c in display_df.columns if c != "選択"],
        hide_index=True, use_container_width=True, key="history_editor"
    )

    selected_indices = edited_df[edited_df["選択"]].index.tolist()
    if selected_indices:
        if st.button(f"{len(selected_indices)} 件の記録を削除する", type="primary", use_container_width=True):
            conn.update(worksheet="Sheet1", data=all_df.drop(selected_indices))
            st.cache_data.clear()
            st.rerun()