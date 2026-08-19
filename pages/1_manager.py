import streamlit as st

# 1. スクリプトの最先頭に配置
st.set_page_config(page_title="マネージャーメニュー", page_icon="📊", layout="wide")

# 2. アクセス制限（ガード処理）
if not st.session_state.get("is_logged_in"):
    st.error("🔒 ログインが必要です。トップページからログインしてください。")
    st.stop()

allowed_roles = ["manager", "admin"]
if st.session_state.get("user_role") not in allowed_roles:
    st.error("⛔ このページを表示する権限がありません（マネージャー・管理者用）。")
    st.stop()

# 3. 本体の画面構成
st.title("📊 マネージャーダッシュボード")
st.caption(f"操作ユーザー: {st.session_state.get('username')} ({st.session_state.get('user_role')})")
st.markdown("---")

st.subheader("チーム実績・業務進捗")
st.write("配下スタッフの日報集計や業務ステータスの承認を行います。")

# ここに必要な業務データ集計（Pandas等）を記述していきます
