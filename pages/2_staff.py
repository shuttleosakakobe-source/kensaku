import streamlit as st

# 1. スクリプトの最先頭に配置
st.set_page_config(page_title="一般業務メニュー", page_icon="📝", layout="wide")

# 2. アクセス制限（ガード処理）
if not st.session_state.get("is_logged_in"):
    st.error("🔒 ログインが必要です。トップページからログインしてください。")
    st.stop()

# 3. 本体の画面構成
st.title("📝 一般業務ポータル")
st.caption(f"担当者: {st.session_state.get('username')}")
st.markdown("---")

st.subheader("日報・業務データ入力")
with st.form("daily_report_form"):
    report_date = st.date_input("日付")
    task_detail = st.text_area("業務内容")
    status = st.selectbox("進捗ステータス", ["完了", "進行中", "保留"])
    submitted = st.form_submit_button("登録する")
    
    if submitted:
        st.success(f"{report_date} の日報を送信しました。")
