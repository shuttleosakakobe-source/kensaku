import sys
from pathlib import Path

# ルートディレクトリを検索パスに追加（ImportError防止）
sys.path.append(str(Path(__file__).parent))

import streamlit as st
import os
from utils import inject_pwa_blocker, set_login_storage, check_session_storage, clear_login_storage, remember_email, get_remembered_email
from data_loader import load_sheet_data
from views.maint_view import maintenance_admin_screen

# --- 1. ページ基本設定 ---
st.set_page_config(
    page_title="ダスキンシャトル メンテナンス依頼アプリ",
    page_icon="icon.png", 
    layout="wide"
)

# --- 2. セッション状態の初期化 ---
if 'login_status' not in st.session_state: st.session_state.login_status = False
if 'logout_requested' not in st.session_state: st.session_state.logout_requested = False
if 'selected_route_nodes' not in st.session_state: st.session_state.selected_route_nodes = [{"名前": "📌 現在地", "住所": "現在地"}]
if 'moved_to_bottom_names' not in st.session_state: st.session_state.moved_to_bottom_names = []
if 'needs_alert' not in st.session_state: st.session_state.needs_alert = False

# --- 3. セッションストレージによる自動ログイン確認 ---
if not st.session_state.login_status and not st.session_state.logout_requested:
    check_session_storage()

# --- 4. 画面表示 ---
# 💡 サイドバーのメニュー切り替えは廃止。ログイン後はメンテナンス業務画面（メインの
#    ボタン行から、商品発注／ルート変更などの各モードに加えてナビ画面・顧客契約データ
#    管理にも入れる）を直接表示する。サイドバーはログイン情報とログアウトのみに使う。
if st.session_state.login_status:
    with st.sidebar:
        st.write(f"👤 ログイン中: **{st.session_state.get('user_name', '担当者')}**")
        st.caption(f"権限: {st.session_state.get('user_role', 'なし')}")
        if st.button("🚪 ログアウト", use_container_width=True):
            st.session_state.login_status = False
            st.session_state.logout_requested = True
            clear_login_storage()
            st.rerun()

    maintenance_admin_screen()
else:
    # --- 🔑 ログイン画面 ---
    inject_pwa_blocker() 
    
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        if os.path.exists("1.png"):
            st.image("1.png", use_container_width=True)

        u_email = st.text_input("メールアドレス", value=get_remembered_email()).strip()
        u_pass = st.text_input("パスワード", type="password").strip()
        
        if st.button("ログイン", type="primary", use_container_width=True):
            raw = load_sheet_data(gid="0")
            if raw and len(raw) > 1:
                # 行ごとに判定 (A列: 0[メール], B列: 1[拠点], C列: 2[名前], D列: 3[パスワード],
                # F列: 5[権限], G列: 6[エリア])
                # 💡 拠点・エリアはこのアプリでは今のところ使っていないが、将来1つの業務アプリに
                #    統合する際にそのまま使えるよう、campaign-tallyと同じ列の読み方・
                #    session_stateキー名（user_branch, user_area）で取得しておく。
                #    同じメール・パスワードで複数行（拠点違い）がある場合も、このアプリでは
                #    拠点を使わないため選択させず、従来通り最初に見つかった行を使う。
                user_found = None
                for row in raw[1:]:
                    if len(row) >= 6:
                        email_val = str(row[0]).strip() # A列
                        pass_val = str(row[3]).strip()  # D列

                        if email_val.lower() == u_email.lower() and pass_val == u_pass:
                            user_found = {
                                "email": email_val,
                                "branch": str(row[1]).strip(),  # B列
                                "name": str(row[2]).strip(), # C列
                                "role": str(row[5]).strip(),  # F列
                                "area": str(row[6]).strip() if len(row) >= 7 else "",  # G列
                            }
                            break

                if user_found:
                    st.session_state.user_name = user_found["name"]
                    st.session_state.user_role = user_found["role"]
                    st.session_state.user_code = user_found["email"]
                    st.session_state.user_branch = user_found["branch"]
                    st.session_state.user_area = user_found["area"]
                    st.session_state.login_status = True
                    st.session_state.logout_requested = False

                    set_login_storage(
                        st.session_state.user_name,
                        "",
                        False,
                        st.session_state.user_role,
                        st.session_state.user_code,
                        st.session_state.user_branch,
                        st.session_state.user_area,
                    )
                    remember_email(u_email)
                    st.rerun()
                else:
                    st.error("認証失敗: メールアドレスまたはパスワードが正しくありません")
            else:
                # テスト用フォールバック
                if u_email == "admin@example.com" and u_pass == "admin":
                    st.session_state.user_name = "管理者"
                    st.session_state.user_role = "管理者"
                    st.session_state.user_code = u_email
                    st.session_state.login_status = True
                    st.session_state.logout_requested = False
                    st.rerun()
                else:
                    st.error("マスターデータの読み込みに失敗しました。シートの共有設定（アクセス権限）を確認してください。")
