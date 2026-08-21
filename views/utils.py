import streamlit as st

def inject_pwa_blocker():
    """PWAブロック用のスクリプト注入（必要に応じて処理を記述）"""
    pass

def set_login_storage(user_info):
    """ログイン情報の保持用関数"""
    st.session_state["user_info"] = user_info

def check_session_storage():
    """セッションのチェック関数"""
    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "担当者"
