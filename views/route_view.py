"""「ルート変更」モード（申請・承認・業務転記・チェック・印刷の5タブ）。"""
import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

from views.maint_common import (
    JST, CUSTOMER_MASTER_CSV, PRINT_SHEET_ID,
    CONTRACT_COL_CUST_CODE, CONTRACT_WEEK_COLS,
    post_to_gas, build_print_pdf_url, _load_contract_df,
    tab_visible, RESTRICTED_TAB_MSG,

)


# ==========================================
# 「ルート変更」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
ROUTE_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=569308342#gid=569308342"
ROUTE_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=569308342"
# TAB3・TAB4用（転記〜チェック）
ROUTE_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1247639196#gid=1247639196"
ROUTE_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=1247639196"

# ルート変更：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G 変更前ルート, H 変更前担当者コード, I 変更前担当者, J 変更後ルート, K 変更後担当者コード, L 変更後担当者,
# M 次回訪問日, N コメント, O 理由, P 連絡担当者, Q サイン(ステータス/承認者名), R 日時(承認日時), S コメント(承認コメント/差戻し理由),
# T 処理日, U 処理者, V チェック日, W チェック者, X 印刷済
ROUTE_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "route_before": 6, "op_before_code": 7, "op_before_name": 8,
    "route_after": 9, "op_after_code": 10, "op_after_name": 11,
    "next_visit": 12, "comment": 13,
    "reason": 14, "contact_person": 15,
    "status_sign": 16, "approval_time": 17, "approval_comment": 18,
    "process_time": 19, "process_user": 20,
    "check_time": 21, "check_user": 22,
    "print_time": 23,
}
CONTRACT_COL_STAFF_CODE = 4
CONTRACT_COL_STAFF_NAME = 5
CONTRACT_COL_WEEKDAY = 6

# 「ルート変更」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
ROUTE_PRINT_SHEET_GID = "1261728197"
ROUTE_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={ROUTE_PRINT_SHEET_GID}#gid={ROUTE_PRINT_SHEET_GID}"
# 1ページに4件まで配置。各件の起点行（A列）：1件目=4, 2件目=15, 3件目=26, 4件目=38
ROUTE_PRINT_BASE_ROWS = [4, 15, 26, 38]


def get_route_lookup(cust_code):
    """ご契約データから、指定した顧客コードの「変更前ルート」「変更前担当者コード」「変更前担当者（氏名）」を算出する。
    M/N/O/P列（週1〜週4）のうち0以外が入っている週について、
    週番号＋G列(曜日種別・そのまま) + E列(担当者コード・3桁ゼロ埋め) でルートコードを作る。
    担当者名はE列(担当者コード)に対応するF列(担当者名)から取得する。
    ご契約データは商品ごとに複数行あるため、同じ顧客コードの行を全て見て、
    ルートコード・担当者コード・担当者名とも重複を除いて返す。"""
    if not cust_code or not str(cust_code).strip():
        return [], [], []
    df_contract = _load_contract_df()
    if df_contract is None:
        return [], [], []

    matched = df_contract[
        df_contract.iloc[:, CONTRACT_COL_CUST_CODE].astype(str).str.strip() == str(cust_code).strip()
    ]
    if matched.empty:
        return [], [], []

    route_codes = []
    staff_codes = []
    staff_names = []
    for _, c_row in matched.iterrows():
        weekday = str(c_row.iloc[CONTRACT_COL_WEEKDAY]).strip() if pd.notna(c_row.iloc[CONTRACT_COL_WEEKDAY]) else ""
        staff_code = str(c_row.iloc[CONTRACT_COL_STAFF_CODE]).strip() if pd.notna(c_row.iloc[CONTRACT_COL_STAFF_CODE]) else ""
        staff_name = str(c_row.iloc[CONTRACT_COL_STAFF_NAME]).strip() if len(c_row) > CONTRACT_COL_STAFF_NAME and pd.notna(c_row.iloc[CONTRACT_COL_STAFF_NAME]) else ""
        if staff_code and staff_code not in staff_codes:
            staff_codes.append(staff_code)
            staff_names.append(staff_name)
        for week_num, col_idx in enumerate(CONTRACT_WEEK_COLS, start=1):
            if col_idx >= len(c_row):
                continue
            week_val = c_row.iloc[col_idx]
            if pd.notna(week_val) and str(week_val).strip() not in ("", "0"):
                code = f"{week_num}{weekday}{staff_code.zfill(3)}"
                if code not in route_codes:
                    route_codes.append(code)
    return route_codes, staff_codes, staff_names


def get_staff_name_by_code(staff_code):
    """ご契約データ全体（顧客コードを問わず）からE列=担当者コードで検索し、
    最初に見つかったF列=担当者名を返す（見つからなければ空文字）"""
    if not staff_code or not str(staff_code).strip():
        return ""
    df_contract = _load_contract_df()
    if df_contract is None:
        return ""
    if len(df_contract.columns) <= CONTRACT_COL_STAFF_NAME:
        return ""

    matched = df_contract[
        df_contract.iloc[:, CONTRACT_COL_STAFF_CODE].astype(str).str.strip() == str(staff_code).strip()
    ]
    if matched.empty:
        return ""
    first_row = matched.iloc[0]
    return str(first_row.iloc[CONTRACT_COL_STAFF_NAME]).strip() if pd.notna(first_row.iloc[CONTRACT_COL_STAFF_NAME]) else ""


def render_route_change_tabs():
    # 💡 【CSS調整】disabled入力の文字が薄くて読みにくいのを解消（商品発注タブと同じ調整）
    st.markdown("""
        <style>
        /* 🔧 disabled/readonly文字が薄い問題の対策
           Streamlitのバージョンによって disabled 属性ではなく readonly や aria-disabled で
           表現される場合があり、:disabled だけでは効かないことがあるため、
           入力欄そのものに常に濃い文字色を強制する（状態を問わず適用） */
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stNumberInput"] input {
            -webkit-text-fill-color: #31333F !important;
            color: #31333F !important;
            opacity: 1 !important;
        }
        input:disabled, input:read-only, input[aria-disabled="true"],
        textarea:disabled, textarea:read-only, textarea[aria-disabled="true"] {
            -webkit-text-fill-color: #31333F !important;
            color: #31333F !important;
            opacity: 1 !important;
        }
        div[data-testid="stTextInput"], div[data-testid="stTextArea"], div[data-testid="stSelectbox"],
        div[data-testid="stTextInput"] label, div[data-testid="stTextArea"] label, div[data-testid="stSelectbox"] label,
        div[data-testid="stWidgetLabel"], div[data-testid="stWidgetLabel"] p, div[data-testid="stWidgetLabel"] label {
            opacity: 1 !important;
            color: #31333F !important;
            -webkit-text-fill-color: #31333F !important;
        }
        div[data-testid="stSelectbox"] div[aria-disabled="true"],
        div[data-testid="stSelectbox"] div[aria-disabled="true"] * {
            opacity: 1 !important;
            color: #31333F !important;
        }
        div[data-testid="stForm"] button[disabled] {
            display: none !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("🗺️ ルート変更申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "route_form_clear_key" not in st.session_state:
        st.session_state["route_form_clear_key"] = 0

    rclear = f"_{st.session_state['route_form_clear_key']}"

    for _key, _default in [
        (f"rt_ccode{rclear}", ""), (f"rt_cname{rclear}", ""),
        (f"rt_scode{rclear}", ""), (f"rt_sname{rclear}", ""),
        (f"rt_rbefore{rclear}", ""), (f"rt_obefore_code{rclear}", ""), (f"rt_obefore_name{rclear}", ""),
        (f"rt_oafter_code{rclear}", ""), (f"rt_oafter_name{rclear}", ""),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    if "route_searched_ccode" not in st.session_state:
        st.session_state["route_searched_ccode"] = ""

    r_tab1, r_tab2, r_tab3, r_tab4, r_tab5 = st.tabs([
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    def _tab1_body():
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["route_searched_ccode"],
                key=f"rt_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"rt_search_btn{rclear}")

            if btn_search:
                if cust_code_input:
                    try:
                        df_master = pd.read_csv(
                            CUSTOMER_MASTER_CSV,
                            dtype=str,
                            storage_options={"User-Agent": "Mozilla/5.0"}
                        )
                        matched = df_master[df_master.iloc[:, 1].astype(str).str.strip() == str(cust_code_input).strip()]

                        if not matched.empty:
                            last_row = matched.iloc[-1]
                            route_codes, staff_codes, staff_names = get_route_lookup(cust_code_input)

                            st.session_state["route_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"rt_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"rt_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"rt_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"rt_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            st.session_state[f"rt_rbefore{rclear}"] = "、".join(route_codes)
                            st.session_state[f"rt_obefore_code{rclear}"] = "、".join(staff_codes)
                            st.session_state[f"rt_obefore_name{rclear}"] = "、".join([n for n in staff_names if n])

                            st.toast("顧客情報を取得しました！", icon="✅")
                            time.sleep(0.3)
                            st.rerun()
                        else:
                            st.warning("該当する顧客データが見つかりませんでした。")
                    except Exception as e:
                        st.error(f"マスタ参照エラー: {e}")
                else:
                    st.warning("顧客コードを入力してください。")

            st.write("---")
            st.write("**📋 入力情報**")

            row1_col1, row1_col2, row1_col3 = st.columns(3)
            customer_code = row1_col1.text_input("顧客コード", key=f"rt_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"rt_cname{rclear}")
            store_code = row1_col3.text_input("加盟店コード", key=f"rt_scode{rclear}")

            row2_col1, row2_col2 = st.columns(2)
            store_name = row2_col1.text_input("加盟店", key=f"rt_sname{rclear}")
            applicant = row2_col2.text_input("担当者", value=st.session_state["user_name"], key=f"rt_app{rclear}")

            st.write("---")
            st.write("**🗺️ ルート情報**")
            row3_col1, row3_col2, row3_col3 = st.columns(3)
            route_before = row3_col1.text_input("変更前ルート", key=f"rt_rbefore{rclear}", disabled=True)
            op_before_code = row3_col2.text_input("変更前担当者コード", key=f"rt_obefore_code{rclear}", disabled=True)
            op_before_name = row3_col3.text_input("変更前担当者", key=f"rt_obefore_name{rclear}", disabled=True)

            def _on_rt_oafter_code_change(_rclear=rclear):
                code_val = st.session_state.get(f"rt_oafter_code{_rclear}", "").strip()
                st.session_state[f"rt_oafter_name{_rclear}"] = get_staff_name_by_code(code_val) if code_val else ""

            row4_col1, row4_col2, row4_col3 = st.columns(3)
            route_after = row4_col1.text_input("変更後ルート", key=f"rt_rafter{rclear}")
            op_after_code = row4_col2.text_input(
                "変更後担当者コード（入力すると担当者名を自動表示）",
                key=f"rt_oafter_code{rclear}",
                on_change=_on_rt_oafter_code_change,
            )
            op_after_name = row4_col3.text_input("変更後担当者（コードから自動表示・手入力も可）", key=f"rt_oafter_name{rclear}")

            st.write("---")

            with st.form("rt_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                next_visit_val = st.date_input("次回訪問日", value=None, key=f"rt_nvisit{rclear}")
                next_visit = next_visit_val.strftime("%Y/%m/%d") if next_visit_val else ""

                st.write("---")
                rt_comment = st.text_area("コメント", placeholder="連絡事項や補足説明があれば入力してください", key=f"rt_com{rclear}")
                rt_reason = st.text_input("理由", key=f"rt_reason{rclear}")
                rt_contact = st.text_input("連絡担当者", key=f"rt_contact{rclear}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip() or not route_after.strip():
                        st.error("⚠️ 「顧客コード」と「変更後ルート」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [
                            now_str, applicant, customer_code, customer_name, store_name, store_code,
                            route_before, op_before_code, op_before_name,
                            route_after, op_after_code, op_after_name, next_visit,
                            rt_comment, rt_reason, rt_contact, "申請中", "", ""
                        ]

                        payload = {
                            "action": "SUBMIT_ROUTE_CHANGE",
                            "target_sheet_url": ROUTE_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["route_searched_ccode"] = ""
                            st.session_state["route_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(ROUTE_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > ROUTE_COL["status_sign"]:
                rejected_df = df[df.iloc[:, ROUTE_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = ROUTE_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            with st.form(key=f"rt_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"rt_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"rt_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"rt_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"rt_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"rt_re_app_{row_id}")

                                r3_1, r3_2, r3_3 = st.columns(3)
                                edit_route_before = r3_1.text_input("変更前ルート", value=_v("route_before"), key=f"rt_re_rbefore_{row_id}")
                                edit_op_before_code = r3_2.text_input("変更前担当者コード", value=_v("op_before_code"), key=f"rt_re_obefore_code_{row_id}")
                                edit_op_before_name = r3_3.text_input("変更前担当者", value=_v("op_before_name"), key=f"rt_re_obefore_name_{row_id}")

                                r4_1, r4_2, r4_3 = st.columns(3)
                                edit_route_after = r4_1.text_input("変更後ルート", value=_v("route_after"), key=f"rt_re_rafter_{row_id}")
                                edit_op_after_code = r4_2.text_input("変更後担当者コード", value=_v("op_after_code"), key=f"rt_re_oafter_code_{row_id}")
                                edit_op_after_name = r4_3.text_input("変更後担当者", value=_v("op_after_name"), key=f"rt_re_oafter_name_{row_id}")

                                edit_next_visit = st.text_input("次回訪問日", value=_v("next_visit"), key=f"rt_re_nvisit_{row_id}")

                                st.write("---")
                                edit_comment = st.text_area("コメント", value=_v("comment"), key=f"rt_re_com_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"rt_re_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者", value=_v("contact_person"), key=f"rt_re_contact_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip() or not edit_route_after.strip():
                                        st.error("⚠️ 「顧客コード」と「変更後ルート」は必須項目です。")
                                    else:
                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code,
                                            edit_route_before, edit_op_before_code, edit_op_before_name,
                                            edit_route_after, edit_op_after_code, edit_op_after_name, edit_next_visit,
                                            edit_comment, edit_reason, edit_contact, "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_ROUTE_CHANGE",
                                            "target_sheet_url": ROUTE_TARGET_SHEET_URL,
                                            "row_index": row_id,
                                            "updated_row": updated_row
                                        }
                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            st.toast("再申請が完了しました！")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(f"処理に失敗しました: {res.get('message')}")
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 2: 管理職チェック
    # ==========================================
    with r_tab1:
        if tab_visible(1):
            _tab1_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab2_body():
        st.subheader("🔍 管理職チェック")
        try:
            st.cache_data.clear()
            df = pd.read_csv(ROUTE_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > ROUTE_COL["status_sign"]:
                pending_df = df[df.iloc[:, ROUTE_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = ROUTE_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            with st.form(key=f"rt_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"rt_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"rt_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"rt_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"rt_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"rt_m_app_{row_id}")

                                m3_1, m3_2, m3_3 = st.columns(3)
                                edit_rbefore = m3_1.text_input("変更前ルート", value=_v("route_before"), key=f"rt_m_rbefore_{row_id}")
                                edit_obefore_code = m3_2.text_input("変更前担当者コード", value=_v("op_before_code"), key=f"rt_m_obefore_code_{row_id}")
                                edit_obefore_name = m3_3.text_input("変更前担当者", value=_v("op_before_name"), key=f"rt_m_obefore_name_{row_id}")

                                m4_1, m4_2, m4_3 = st.columns(3)
                                edit_rafter = m4_1.text_input("変更後ルート", value=_v("route_after"), key=f"rt_m_rafter_{row_id}")
                                edit_oafter_code = m4_2.text_input("変更後担当者コード", value=_v("op_after_code"), key=f"rt_m_oafter_code_{row_id}")
                                edit_oafter_name = m4_3.text_input("変更後担当者", value=_v("op_after_name"), key=f"rt_m_oafter_name_{row_id}")

                                edit_nvisit = st.text_input("次回訪問日", value=_v("next_visit"), key=f"rt_m_nvisit_{row_id}")

                                st.write("---")
                                edit_comment = st.text_area("申請者コメント", value=_v("comment"), key=f"rt_m_com_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"rt_m_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者", value=_v("contact_person"), key=f"rt_m_contact_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"rt_mgr_com_{row_id}")

                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認（変更内容を反映）", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    updated_row = [
                                        _v("timestamp"), edit_app, edit_ccode, edit_cname,
                                        edit_sname, edit_scode,
                                        edit_rbefore, edit_obefore_code, edit_obefore_name,
                                        edit_rafter, edit_oafter_code, edit_oafter_name, edit_nvisit,
                                        edit_comment, edit_reason, edit_contact
                                    ]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_ROUTE_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_ROUTE_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_ROUTE_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": ROUTE_TARGET_SHEET_URL,
                                        "row_index": row_id,
                                        "updated_row": updated_row
                                    }
                                    res = post_to_gas(payload)
                                    if res.get("status") == "success":
                                        st.toast("処理が完了しました！")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error(f"処理に失敗しました: {res.get('message')}")
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 3: 業務担当メンテナンス処理
    # ==========================================
    with r_tab2:
        if tab_visible(2):
            _tab2_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab3_body():
        st.subheader("🚚 業務担当メンテナンス処理")
        try:
            st.cache_data.clear()
            df = pd.read_csv(ROUTE_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= ROUTE_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, ROUTE_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, ROUTE_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = ROUTE_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"rt_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"rt_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"rt_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"rt_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"rt_v_app_{row_id}")

                            o3_c1, o3_c2, o3_c3 = st.columns(3)
                            o3_c1.text_input("変更前ルート", value=_v("route_before"), disabled=True, key=f"rt_v_rbefore_{row_id}")
                            o3_c2.text_input("変更前担当者コード", value=_v("op_before_code"), disabled=True, key=f"rt_v_obefore_code_{row_id}")
                            o3_c3.text_input("変更前担当者", value=_v("op_before_name"), disabled=True, key=f"rt_v_obefore_name_{row_id}")

                            o4_c1, o4_c2, o4_c3 = st.columns(3)
                            o4_c1.text_input("変更後ルート", value=_v("route_after"), disabled=True, key=f"rt_v_rafter_{row_id}")
                            o4_c2.text_input("変更後担当者コード", value=_v("op_after_code"), disabled=True, key=f"rt_v_oafter_code_{row_id}")
                            o4_c3.text_input("変更後担当者", value=_v("op_after_name"), disabled=True, key=f"rt_v_oafter_name_{row_id}")

                            o5_c1, o5_c2 = st.columns(2)
                            o5_c1.text_input("次回訪問日", value=_v("next_visit"), disabled=True, key=f"rt_v_nvisit_{row_id}")
                            o5_c2.text_input("承認者", value=mgr_name, disabled=True, key=f"rt_v_mgr_{row_id}")

                            comment_val = _v("comment")
                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            if comment_val.strip() or reason_val.strip() or contact_val.strip():
                                st.write("---")
                                if comment_val.strip():
                                    st.text_area("申請者コメント", value=comment_val, disabled=True, key=f"rt_v_com_{row_id}")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"rt_v_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者", value=contact_val, disabled=True, key=f"rt_v_contact_{row_id}")

                            st.write("---")
                            with st.form(key=f"rt_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"rt_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(ROUTE_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_ROUTE_TO_OPERATOR",
                                        "target_sheet_url": ROUTE_TARGET_SHEET_URL,
                                        "dest_sheet_url": ROUTE_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": ROUTE_COL["status_sign"] + 1,
                                    }

                                    with st.spinner("業務シートへ転記中..."):
                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            st.cache_data.clear()
                                            st.toast("🎉 業務用スプレッドシートへの転記が完了しました！", icon="🎉")
                                            time.sleep(1.5)
                                            st.rerun()
                                        else:
                                            st.error(f"転記失敗: {res.get('message')}")

                                elif btn_op_reject:
                                    if not op_reject_reason.strip():
                                        st.error("⚠️ 差戻しを行う場合は「差戻し理由」を入力してください。")
                                    else:
                                        base_data = [
                                            "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                            for i in range(ROUTE_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_ROUTE_CHANGE",
                                            "target_sheet_url": ROUTE_TARGET_SHEET_URL,
                                            "row_index": row_id,
                                            "updated_row": final_reject_row
                                        }

                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            st.cache_data.clear()
                                            st.toast("申請を差し戻しました。", icon="↩️")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(f"差戻し失敗: {res.get('message')}")

        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 4: メンテナンスチェック画面
    # ==========================================
    with r_tab3:
        if tab_visible(3):
            _tab3_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab4_body():
        st.subheader("✅ メンテナンスチェック画面")

        try:
            st.cache_data.clear()
            df_dest = pd.read_csv(ROUTE_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="rt_chk_show_checked")

                if not show_checked and len(df_dest.columns) > ROUTE_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, ROUTE_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = ROUTE_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"rt_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"rt_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"rt_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"rt_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"rt_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"rt_chk_app_{row_id}")

                            c6, c7, c8 = st.columns(3)
                            c6.text_input("変更前ルート", value=_v("route_before"), disabled=True, key=f"rt_chk_rbefore_{row_id}")
                            c7.text_input("変更前担当者コード", value=_v("op_before_code"), disabled=True, key=f"rt_chk_obefore_code_{row_id}")
                            c8.text_input("変更前担当者", value=_v("op_before_name"), disabled=True, key=f"rt_chk_obefore_name_{row_id}")

                            c9, c10, c11 = st.columns(3)
                            c9.text_input("変更後ルート", value=_v("route_after"), disabled=True, key=f"rt_chk_rafter_{row_id}")
                            c10.text_input("変更後担当者コード", value=_v("op_after_code"), disabled=True, key=f"rt_chk_oafter_code_{row_id}")
                            c11.text_input("変更後担当者", value=_v("op_after_name"), disabled=True, key=f"rt_chk_oafter_name_{row_id}")

                            c12, c13 = st.columns(2)
                            c12.text_input("次回訪問日", value=_v("next_visit"), disabled=True, key=f"rt_chk_nvisit_{row_id}")
                            c13.text_input("処理者", value=op_user_val, disabled=True, key=f"rt_chk_op_{row_id}")

                            st.text_input("承認者", value=mgr_name_val, disabled=True, key=f"rt_chk_mgr_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            comment_val = _v("comment")
                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            if comment_val.strip() or reason_val.strip() or contact_val.strip():
                                st.write("---")
                                if comment_val.strip():
                                    st.text_area("申請者コメント", value=comment_val, disabled=True, key=f"rt_chk_com_{row_id}")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"rt_chk_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者", value=contact_val, disabled=True, key=f"rt_chk_contact_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"rt_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"rt_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < ROUTE_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[ROUTE_COL["check_time"]] = check_time
                                clean_base_row[ROUTE_COL["check_user"]] = checker_name
                                # ※ print_time列（印刷済）はここでは触らない。既存の値を保持する。

                                payload = {
                                    "action": "UPDATE_ROUTE_CHECK",
                                    "target_sheet_url": ROUTE_DEST_SHEET_URL,
                                    "row_index": row_id,
                                    "updated_row": clean_base_row
                                }

                                res = post_to_gas(payload)
                                if res.get("status") == "success":
                                    st.cache_data.clear()
                                    st.toast(f"行 {row_id} のメンテナンスチェックを完了しました！", icon="✅")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"更新失敗: {res.get('message')}")

                            elif btn_checked_reject:
                                if not reject_reason.strip():
                                    st.error("⚠️ 差戻しを行う場合は「差戻し理由」を入力してください。")
                                else:
                                    st.toast(f"【{reject_target}】へ差戻しを行いました（理由: {reject_reason}）", icon="↩️")
                                    time.sleep(1.5)
                                    st.rerun()

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")

    # ==========================================
    # TAB 5: 加盟店別 印刷プレビュー画面
    # ==========================================
    with r_tab4:
        if tab_visible(4):
            _tab4_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab5_body():
        st.subheader("🖨️ 加盟店別 印刷")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(ROUTE_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > ROUTE_COL["check_time"]:
                    checked_mask = df_print.iloc[:, ROUTE_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > ROUTE_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, ROUTE_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = ROUTE_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="rt_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(ROUTE_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_route_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = ROUTE_COL[col_key]
                                return str(r_row.iloc[i]) if len(r_row) > i and pd.notna(r_row.iloc[i]) else ""

                            manager = _f("status_sign") or "未確認"
                            operator = _f("process_user") or st.session_state["user_name"]
                            contact = _f("contact_person")
                            contact_disp = f"{contact} 様" if contact.strip() else ""
                            raw_cname = _f("cust_name")
                            cust_name_disp = f"{raw_cname} 様" if raw_cname.strip() else ""

                            return {
                                "store_code": _f("store_code"), "cust_name": cust_name_disp,
                                "manager": manager, "operator": operator,
                                "route_before": _f("route_before"), "route_after": _f("route_after"),
                                "cust_code": _f("cust_code"),
                                "op_before_name": _f("op_before_name"), "op_after_name": _f("op_after_name"),
                                "applicant": _f("applicant"),
                                "next_visit": _f("next_visit"), "reason": _f("reason"),
                                "comment": _f("comment") or "特記事項なし",
                                "contact_disp": contact_disp,
                            }

                        def route_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            C1=加盟店名, A/B/D/E(+0)=加盟店コード/顧客名/責任者/処理者,
                            A/C/E(+2)=変更前ルート/変更後ルート/シャトルコード(顧客コード),
                            A/C/E(+4)=変更前担当者/変更後担当者/提出者,
                            A/C(+6)=次回訪問日/変更理由, A/E(+8)=特記事項/連絡担当者"""
                            if not rec:
                                rec = {k: "" for k in [
                                    "store_code", "cust_name", "manager", "operator",
                                    "route_before", "route_after", "cust_code",
                                    "op_before_name", "op_after_name", "applicant",
                                    "next_visit", "reason", "comment", "contact_disp",
                                ]}
                            return [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 2, "value": rec["cust_name"]},
                                {"offset": 0, "col": 4, "value": rec["manager"]},
                                {"offset": 0, "col": 5, "value": rec["operator"]},
                                {"offset": 2, "col": 1, "value": rec["route_before"]},
                                {"offset": 2, "col": 3, "value": rec["route_after"]},
                                {"offset": 2, "col": 5, "value": rec["cust_code"]},
                                {"offset": 4, "col": 1, "value": rec["op_before_name"]},
                                {"offset": 4, "col": 3, "value": rec["op_after_name"]},
                                {"offset": 4, "col": 5, "value": rec["applicant"]},
                                {"offset": 6, "col": 1, "value": rec["next_visit"]},
                                {"offset": 6, "col": 3, "value": rec["reason"]},
                                {"offset": 8, "col": 1, "value": rec["comment"]},
                                {"offset": 8, "col": 5, "value": rec["contact_disp"]},
                            ]

                        chunk_size = len(ROUTE_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(ROUTE_PRINT_BASE_ROWS):
                                rec = build_route_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": route_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    st.caption(f"変更前ルート: {rec['route_before']} → 変更後ルート: {rec['route_after']} ｜ シャトルコード（顧客コード）: {rec['cust_code']}")
                                    st.caption(f"変更前担当者: {rec['op_before_name']} → 変更後担当者: {rec['op_after_name']} ｜ 提出者: {rec['applicant']}")
                                    st.caption(f"次回訪問日: {rec['next_visit']} ｜ 変更理由: {rec['reason']} ｜ 連絡担当者: {rec['contact_disp']}")
                                    st.caption(f"特記事項: {rec['comment']}")

                            if st.button("📥 反映してPDFを作成する", key=f"rt_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": ROUTE_PRINT_SHEET_URL,
                                    "store_name": selected_store,
                                    "c1_value": c1_value,
                                    "blocks": blocks,
                                }
                                with st.spinner("印刷用スプレッドシートへ反映しています..."):
                                    res = post_to_gas(payload)

                                if res.get("status") == "success":
                                    print_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                    mark_payload = {
                                        "action": "MARK_PRINTED",
                                        "target_sheet_url": ROUTE_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": ROUTE_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = ROUTE_PRINT_BASE_ROWS[len(chunk) - 1] + 8 if len(chunk) > 0 else 12
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, gid=ROUTE_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_route_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"rt_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({ROUTE_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                            )
                                    except Exception as pdf_e:
                                        st.warning(f"PDF作成中にエラーが発生しました: {pdf_e}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"反映に失敗しました: {res.get('message')}")

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
    with r_tab5:
        if tab_visible(5):
            _tab5_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
