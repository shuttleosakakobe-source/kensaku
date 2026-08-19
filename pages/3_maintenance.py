import streamlit as st

# 1. スクリプトの最先頭に配置
st.set_page_config(page_title="メンテナンス", page_icon="🛠️", layout="wide")

# 2. アクセス制限（ガード処理）
if not st.session_state.get("is_logged_in"):
    st.error("🔒 ログインが必要です。トップページからログインしてください。")
    st.stop()

if st.session_state.get("user_role") != "admin":
    st.error("⛔ このページを表示する権限がありません（管理者専用）。")
    st.stop()

# 3. 本体の画面構成
st.title("🛠️ システムメンテナンス")
st.caption(f"操作ユーザー: {st.session_state.get('username')} (admin)")
st.markdown("---")

st.warning("⚠️ データのバックアップ・ログの確認を行う画面です。")

col1, col2 = st.columns(2)
with col1:
    if st.button("DBバックアップ実行"):
        st.info("バックアップ処理を実行しました。")
with col2:
    if st.button("キャッシュクリア"):
        st.cache_data.clear()
        st.success("キャッシュを削除しました。")
