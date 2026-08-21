import streamlit as st

def main_screen():
    st.title("🏠 メイン画面")
    st.write(f"ようこそ、**{st.session_state.get('user_name', 'ユーザー')}** 様")
    st.info("左側のサイドバーから「📦 メンテナンス申請・承認」を選択してください。")
