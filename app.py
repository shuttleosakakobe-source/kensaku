import sys
from pathlib import Path

# ルートディレクトリを検索パスに追加（Streamlit Cloud等でのImportErrorを絶対防止）
sys.path.append(str(Path(__file__).parent))

import streamlit as st
import os
from utils import inject_pwa_blocker, set_login_storage, check_session_storage
from data_loader import load_sheet_data
from views.main_view import main_screen
from views.navi_view import route_navigation_screen
from views.maint_view import maintenance_admin_screen

# --- 1. ページ基本設定 ---
st.set_page_config(
    page_title="ダスキンシャトル 業務アプリ",
    page_icon="icon.png", 
    layout="wide"
)

# --- 2. セッション状態の初期化 ---
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'logout_requested' not in st.session_state: st.session_state.logout_requested = False
if 'current_page' not in st.session_state: st.session_state.current_page = "maint_admin" # 初期画面設定
if 'selected_route_nodes' not in st.session_state: st.session_state.selected_route_nodes = [{"名前": "📌 現在地", "住所": "現在地"}]
if 'moved_to_bottom_names' not in st.session_state: st.session_state.moved_to_bottom_names = []
if 'needs_alert' not in st.session_state: st.session_state.needs_alert = False

# --- 3. セッションストレージによる自動ログイン確認 ---
if not st.session_state.login_status and not st.session_state.logout_requested:
    check_session_storage()

# --- 4. 画面ルーティング制御 ---
if st.session_state.login_status:
    # サイドバーに画面切り替えメニューを表示
    with st.sidebar:
        st.write(f"👤 ログイン中: **{st.session_state.get('user_name', '担当者')}**")
        if st.button("🚪 ログアウト", use_container_width=True):
            st.session_state.login_status = False
            st.session_state.logout_requested = True
            st.rerun()
        st.write("---")
        page = st.radio(
            "メニュー切り替え",
            ["📦 メンテナンス申請・承認", "🏠 メイン画面", "🗺️ ナビ画面"],
            index=0
        )
        if page == "📦 メンテナンス申請・承認":
            st.session_state.current_page = "maint_admin"
        elif page == "🏠 メイン画面":
            st.session_state.current_page = "main"
        elif page == "🗺️ ナビ画面":
            st.session_state.current_page = "navi"

    # 指定ページの表示
    if st.session_state.current_page in ["navi", "nav"]:
        route_navigation_screen()
    elif st.session_state.current_page == "maint_admin":
        maintenance_admin_screen()
    else:
        main_screen()
else:
    # --- 🔑 ログイン画面 ---
    inject_pwa_blocker() 
    
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        if os.path.exists("1.png"):
            st.image("1.png", use_container_width=True)
        st.title("🔑 業務システム ログイン")
            
        u_code = st.text_input("担当者コード").strip()
        u_pass = st.text_input("パスワード", type="password").strip()
        
        if st.button("ログイン", type="primary", use_container_width=True):
            raw = load_sheet_data(gid="0")
            if raw:
                h = raw[0]
                rows = [dict(zip(h, r)) for r in raw[1:]]
                user = next((r for r in rows if str(r.get('担当者コード')).strip() == u_code and str(r.get('パスワード')).strip() == u_pass), None)
                
                if user:
                    vals = list(user.values())
                    st.session_state.user_name = user.get('担当者名')
                    st.session_state.user_url = user.get('URL')
                    st.session_state.needs_alert = (str(vals[5]).strip() not in ["0", ""]) if len(vals) > 5 else False
                    st.session_state.user_role = str(vals[6]).strip() if len(vals) >= 7 else "2"
                    st.session_state.user_code = u_code
                    st.session_state.login_status = True
                    st.session_state.logout_requested = False
                    st.session_state.current_page = "maint_admin"
                    
                    set_login_storage(
                        st.session_state.user_name,
                        st.session_state.user_url,
                        st.session_state.needs_alert,
                        st.session_state.user_role,
                        st.session_state.user_code
                    )
                    st.rerun()
                else:
                    st.error("認証失敗: 担当者コードまたはパスワードが正しくありません")
            else:
                # デモ用フォールバック（マスター接続不可時のテスト用）
                if u_code == "admin" and u_pass == "admin":
                    st.session_state.user_name = "管理者"
                    st.session_state.user_code = u_code
                    st.session_state.login_status = True
                    st.session_state.logout_requested = False
                    st.session_state.current_page = "maint_admin"
                    st.rerun()
                else:
                    st.error("マスターデータの読み込みに失敗しました")
