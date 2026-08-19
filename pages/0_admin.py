import streamlit as st

# 1. スクリプトの最先頭に配置
st.set_page_config(page_title="管理者メニュー", page_icon="⚙️", layout="wide")

# 2. アクセス制限（ガード処理）
if not st.session_state.get("is_logged_in"):
    st.error("🔒 ログインが必要です。トップページからログインしてください。")
    st.stop()

if st.session_state.get("user_role") != "admin":
    st.error("⛔ このページを表示する権限がありません（管理者専用）。")
    st.stop()

# 3. 本体の画面構成
st.title("⚙️ 管理者専用ダッシュボード")
st.caption(f"操作ユーザー: {st.session_state.get('username')} (admin)")
st.markdown("---")

st.subheader("1. ユーザーアカウント管理")
st.write("社内ユーザーの追加・削除・権限変更を行います。")

st.subheader("2. システム全体設定")
st.write("アプリケーションの各種パラメータ設定を変更できます。")

# ここに必要なビジネスロジックを追加していきます
