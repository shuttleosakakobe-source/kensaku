import streamlit as st
import pandas as pd
from data_loader import load_navi_data_from_url

def route_navigation_screen():
    st.markdown("### 🗺️ ルートナビゲーション")
    
    if st.button("⬅️ メイン画面に戻る"):
        st.session_state.current_page = "main"
        st.rerun()

    u_url = st.session_state.get('user_url', '')
    if not u_url:
        st.warning("担当者個別のルートスプレッドシートURLが設定されていません。")
        return

    # CSVエクスポートURLへ変換
    csv_url = u_url.replace('/edit', '/export?format=csv') if '/edit' in u_url else u_url

    navi_data = load_navi_data_from_url(csv_url)
    if not navi_data:
        st.error("ナビゲーションデータの読み込みに失敗しました。")
        return

    df = pd.DataFrame(navi_data)
    st.dataframe(df, use_container_width=True)
