import streamlit as st

# 1. スクリプトの最先頭でページ設定（Streamlitの必須ルール）
st.set_page_config(
    page_title="社内業務システム",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. セッション状態（全ページ共通の変数）の初期化
if "is_logged_in" not in st.session_state:
    st.session_state["is_logged_in"] = False
if "username" not in st.session_state:
    st.session_state["username"] = ""
if "user_role" not in st.session_state:
    st.session_state["user_role"] = ""

st.title("🏢 社内業務アプリ ポータル")

# 3. ログインチェックとフォームの表示
if not st.session_state["is_logged_in"]:
    st.subheader("ログイン")
    st.info("テスト用：任意のID・パスワードと対象のロール（権限）を選択してログインしてください。")
    
    with st.form("login_form"):
        username = st.text_input("ユーザーID / 氏名")
        password = st.text_input("パスワード", type="password")
        role = st.selectbox("ログイン権限（テスト切り替え用）", ["staff", "manager", "admin"])
        submit_button = st.form_submit_button("ログイン")
        
        if submit_button:
            if username and password:
                # ログイン情報をセッションに記録
                st.session_state["is_logged_in"] = True
                st.session_state["username"] = username
                st.session_state["user_role"] = role
                st.success(f"ログインしました: {username} 様（権限: {role}）")
                st.rerun()
            else:
                st.error("ユーザーIDとパスワードを入力してください。")

else:
    # ログイン済みの画面
    st.success(f"現在 **{st.session_state['username']}** 様としてログイン中（権限: {st.session_state['user_role']}）")
    st.markdown("""
    ---
    ### 👈 左側のサイドバーから利用する機能を選択してください
    - **一般業務**: 全ユーザー利用可能
    - **マネージャーダッシュボード**: マネージャー・管理者のみ
    - **管理者ダッシュボード**: 管理者のみ
    - **システムメンテナンス**: 管理者のみ
    """)
    
    st.markdown("---")
    if st.button("ログアウト", type="primary"):
        st.session_state["is_logged_in"] = False
        st.session_state["username"] = ""
        st.session_state["user_role"] = ""
        st.rerun()
