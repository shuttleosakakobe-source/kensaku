import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timezone, timedelta
import time

GAS_URL = "https://script.google.com/macros/s/AKfycbxFMI1r4yx6Euh3afHspXpBLM72XttGuz1vrm6aEbTdsPAiVj7CMp8xD_qjyKGZBy47_A/exec"

TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0"
DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=0"
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"

# ==========================================
# 「ルート変更」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
ROUTE_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=569308342#gid=569308342"
ROUTE_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=569308342"
# TAB3・TAB4用（転記〜チェック）
ROUTE_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1247639196#gid=1247639196"
ROUTE_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=1247639196"

# ご契約データ（顧客コードごとの契約週・曜日・担当者コードからルートコードを計算するための参照シート）
CONTRACT_DATA_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=2011677989"

# ルート変更：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G 変更前ルート, H 変更前担当者, I 変更後ルート, J 変更後担当者, K 次回訪問日, L コメント,
# M 理由, N 連絡担当者, O サイン(ステータス/承認者名), P 日時(承認日時), Q コメント(承認コメント/差戻し理由),
# R 処理日, S 処理者, T チェック日, U チェック者, V 印刷済
ROUTE_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5, "route_before": 6, "op_before": 7,
    "route_after": 8, "op_after": 9, "next_visit": 10, "comment": 11,
    "reason": 12, "contact_person": 13,
    "status_sign": 14, "approval_time": 15, "approval_comment": 16,
    "process_time": 17, "process_user": 18,
    "check_time": 19, "check_user": 20,
    "print_time": 21,
}

# ご契約データシートの列（0始まり）：顧客コード(A)=0、担当者コード(E)=4、曜日(G)=6、契約週M/N/O/P=12/13/14/15
CONTRACT_COL_CUST_CODE = 0
CONTRACT_COL_STAFF_CODE = 4
CONTRACT_COL_WEEKDAY = 6
CONTRACT_WEEK_COLS = [12, 13, 14, 15]  # M, N, O, P → 週1, 週2, 週3, 週4

# TAB5用：加盟店別 印刷フォーマットのスプレッドシート（DEST_SHEET_URLとは別シート／gidが違う点に注意）
PRINT_SHEET_ID = "1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI"
PRINT_SHEET_GID = "457221393"
PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={PRINT_SHEET_GID}#gid={PRINT_SHEET_GID}"

# DEST_SHEET（実データ）側の管理列（0始まりのインデックス）
OP_USER_COL_IDX = 34      # AI列：処理者（TAB3で転記した担当者）
CHECK_TIME_COL_IDX = 35   # AJ列：チェック日時
CHECK_USER_COL_IDX = 36   # AK列：チェック者
PRINT_TIME_COL_IDX = 37   # AL列：印刷日時（TAB5で反映が完了したらここに日時が入る）


def build_print_pdf_url(row_end=46, col_end=5):
    """印刷フォーマットシートのA1〜(row_end, col_end)の範囲をPDFとして書き出すURLを作る
    （row_end/col_endは0始まりの終端。col_end=5はA〜E列を含む）"""
    params = {
        "format": "pdf",
        "gid": PRINT_SHEET_GID,
        "size": "A4",
        "portrait": "true",
        "fitw": "true",
        "top_margin": "0.4",
        "bottom_margin": "0.4",
        "left_margin": "0.4",
        "right_margin": "0.4",
        "sheetnames": "false",
        "printtitle": "false",
        "pagenumbers": "false",
        "gridlines": "false",
        "fzr": "false",
        "horizontal_alignment": "CENTER",
        "vertical_alignment": "TOP",
        "r1": "0",
        "c1": "0",
        "r2": str(row_end),
        "c2": str(col_end),
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/export?{query}"

# 日本時間（JST = UTC+9）のタイムゾーン定義
JST = timezone(timedelta(hours=+9), 'JST')


def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_route_lookup(cust_code):
    """ご契約データから、指定した顧客コードの「変更前ルート」「変更前担当者」を算出する。
    M/N/O/P列（週1〜週4）のうち0以外が入っている週について、
    週番号＋G列(曜日種別・そのまま) + E列(担当者コード・3桁ゼロ埋め) でルートコードを作る。
    ご契約データは商品ごとに複数行あるため、同じ顧客コードの行を全て見て、
    ルートコード・担当者コードとも重複を除いて返す。"""
    if not cust_code or not str(cust_code).strip():
        return [], []
    try:
        df_contract = pd.read_csv(CONTRACT_DATA_CSV, dtype=str, storage_options={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return [], []
    if df_contract.empty:
        return [], []

    matched = df_contract[
        df_contract.iloc[:, CONTRACT_COL_CUST_CODE].astype(str).str.strip() == str(cust_code).strip()
    ]
    if matched.empty:
        return [], []

    route_codes = []
    staff_codes = []
    for _, c_row in matched.iterrows():
        weekday = str(c_row.iloc[CONTRACT_COL_WEEKDAY]).strip() if pd.notna(c_row.iloc[CONTRACT_COL_WEEKDAY]) else ""
        staff_code = str(c_row.iloc[CONTRACT_COL_STAFF_CODE]).strip() if pd.notna(c_row.iloc[CONTRACT_COL_STAFF_CODE]) else ""
        if staff_code and staff_code not in staff_codes:
            staff_codes.append(staff_code)
        for week_num, col_idx in enumerate(CONTRACT_WEEK_COLS, start=1):
            if col_idx >= len(c_row):
                continue
            week_val = c_row.iloc[col_idx]
            if pd.notna(week_val) and str(week_val).strip() not in ("", "0"):
                code = f"{week_num}{weekday}{staff_code.zfill(3)}"
                if code not in route_codes:
                    route_codes.append(code)
    return route_codes, staff_codes


def maintenance_admin_screen():
    """メンテナンス画面の入口。商品発注／ルート変更を切り替えて、それぞれのタブ一式を表示する"""
    st.markdown("#### 📦🗺️ メンテナンス業務")
    mode = st.radio(
        "モード切り替え",
        ["📦 商品発注", "🗺️ ルート変更"],
        index=0,
        horizontal=True,
        key="maint_mode_select",
        label_visibility="collapsed",
    )
    st.write("---")

    if mode == "📦 商品発注":
        render_product_order_tabs()
    else:
        render_route_change_tabs()


def render_route_change_tabs():
    st.header("🗺️ ルート変更申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "route_form_clear_key" not in st.session_state:
        st.session_state["route_form_clear_key"] = 0

    rclear = f"_{st.session_state['route_form_clear_key']}"

    if f"rt_ccode{rclear}" not in st.session_state:
        st.session_state[f"rt_ccode{rclear}"] = ""
    if f"rt_cname{rclear}" not in st.session_state:
        st.session_state[f"rt_cname{rclear}"] = ""
    if f"rt_scode{rclear}" not in st.session_state:
        st.session_state[f"rt_scode{rclear}"] = ""
    if f"rt_sname{rclear}" not in st.session_state:
        st.session_state[f"rt_sname{rclear}"] = ""
    if f"rt_rbefore{rclear}" not in st.session_state:
        st.session_state[f"rt_rbefore{rclear}"] = ""
    if f"rt_obefore{rclear}" not in st.session_state:
        st.session_state[f"rt_obefore{rclear}"] = ""

    if "route_searched_ccode" not in st.session_state:
        st.session_state["route_searched_ccode"] = ""

    r_tab1, r_tab2, r_tab3, r_tab4 = st.tabs([
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with r_tab1:
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
                            route_codes, staff_codes = get_route_lookup(cust_code_input)

                            st.session_state["route_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"rt_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"rt_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"rt_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"rt_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            st.session_state[f"rt_rbefore{rclear}"] = "、".join(route_codes)
                            st.session_state[f"rt_obefore{rclear}"] = "、".join(staff_codes)

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

            with st.form("rt_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

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
                row3_col1, row3_col2 = st.columns(2)
                route_before = row3_col1.text_input("変更前ルート（顧客コード検索で自動表示）", key=f"rt_rbefore{rclear}", disabled=True)
                op_before = row3_col2.text_input("変更前担当者（顧客コード検索で自動表示）", key=f"rt_obefore{rclear}", disabled=True)

                row4_col1, row4_col2 = st.columns(2)
                route_after = row4_col1.text_input("変更後ルート", key=f"rt_rafter{rclear}")
                op_after = row4_col2.text_input("変更後担当者", key=f"rt_oafter{rclear}")

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
                            route_before, op_before, route_after, op_after, next_visit,
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

                                r3_1, r3_2 = st.columns(2)
                                edit_route_before = r3_1.text_input("変更前ルート", value=_v("route_before"), key=f"rt_re_rbefore_{row_id}")
                                edit_op_before = r3_2.text_input("変更前担当者", value=_v("op_before"), key=f"rt_re_obefore_{row_id}")

                                r4_1, r4_2 = st.columns(2)
                                edit_route_after = r4_1.text_input("変更後ルート", value=_v("route_after"), key=f"rt_re_rafter_{row_id}")
                                edit_op_after = r4_2.text_input("変更後担当者", value=_v("op_after"), key=f"rt_re_oafter_{row_id}")

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
                                            edit_store_name, edit_store_code, edit_route_before, edit_op_before,
                                            edit_route_after, edit_op_after, edit_next_visit,
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
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 2: 管理職チェック
    # ==========================================
    with r_tab2:
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

                                m3_1, m3_2 = st.columns(2)
                                edit_rbefore = m3_1.text_input("変更前ルート", value=_v("route_before"), key=f"rt_m_rbefore_{row_id}")
                                edit_obefore = m3_2.text_input("変更前担当者", value=_v("op_before"), key=f"rt_m_obefore_{row_id}")

                                m4_1, m4_2 = st.columns(2)
                                edit_rafter = m4_1.text_input("変更後ルート", value=_v("route_after"), key=f"rt_m_rafter_{row_id}")
                                edit_oafter = m4_2.text_input("変更後担当者", value=_v("op_after"), key=f"rt_m_oafter_{row_id}")

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
                                        edit_sname, edit_scode, edit_rbefore, edit_obefore,
                                        edit_rafter, edit_oafter, edit_nvisit, edit_comment, edit_reason, edit_contact
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
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 3: 業務担当メンテナンス処理
    # ==========================================
    with r_tab3:
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

                            o3_c1, o3_c2 = st.columns(2)
                            o3_c1.text_input("変更前ルート", value=_v("route_before"), disabled=True, key=f"rt_v_rbefore_{row_id}")
                            o3_c2.text_input("変更前担当者", value=_v("op_before"), disabled=True, key=f"rt_v_obefore_{row_id}")

                            o4_c1, o4_c2 = st.columns(2)
                            o4_c1.text_input("変更後ルート", value=_v("route_after"), disabled=True, key=f"rt_v_rafter_{row_id}")
                            o4_c2.text_input("変更後担当者", value=_v("op_after"), disabled=True, key=f"rt_v_oafter_{row_id}")

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
    with r_tab4:
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

                            c6, c7 = st.columns(2)
                            c6.text_input("変更前ルート", value=_v("route_before"), disabled=True, key=f"rt_chk_rbefore_{row_id}")
                            c7.text_input("変更前担当者", value=_v("op_before"), disabled=True, key=f"rt_chk_obefore_{row_id}")

                            c8, c9 = st.columns(2)
                            c8.text_input("変更後ルート", value=_v("route_after"), disabled=True, key=f"rt_chk_rafter_{row_id}")
                            c9.text_input("変更後担当者", value=_v("op_after"), disabled=True, key=f"rt_chk_oafter_{row_id}")

                            c10, c11 = st.columns(2)
                            c10.text_input("次回訪問日", value=_v("next_visit"), disabled=True, key=f"rt_chk_nvisit_{row_id}")
                            c11.text_input("処理者", value=op_user_val, disabled=True, key=f"rt_chk_op_{row_id}")

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


def render_product_order_tabs():
    # 💡 【CSS調整】指定レイアウトに合わせた帳票・印刷用スタイル定義
    st.markdown("""
        <style>
        input:disabled, textarea:disabled {
            -webkit-text-fill-color: #31333F !important;
            color: #31333F !important;
            opacity: 1 !important;
        }
        div[data-testid="stForm"] button[disabled] {
            display: none !important;
        }
        
        /* 🖨️ 印刷/PDF出力時のレイアウト最適化（A4サイズ・3件1ページ） */
        @media print {
            body {
                background: white !important;
                color: black !important;
            }
            header, footer, [data-testid="stSidebar"], .stButton, button, .no-print {
                display: none !important;
            }
            .print-sheet {
                page-break-after: always;
                border: none !important;
                padding: 0px !important;
                margin: 0px !important;
                background: white !important;
                box-shadow: none !important;
            }
        }
        
        /* 画面上での帳票プレビュー枠 */
        .print-sheet {
            border: 1px solid #d6d6d6;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 25px;
            background: #ffffff;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            font-family: monospace, sans-serif;
        }
        .sheet-block {
            border: 1px solid #aaa;
            padding: 10px;
            margin-bottom: 15px;
            background: #fafafa;
            border-radius: 4px;
        }
        .block-title {
            font-size: 13px;
            font-weight: bold;
            color: #333;
            margin-bottom: 6px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 3px;
        }
        .grid-row {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 5px;
            font-size: 11px;
            margin-bottom: 4px;
        }
        .grid-cell {
            background: #fff;
            border: 1px solid #ccc;
            padding: 4px 6px;
            border-radius: 3px;
        }
        .grid-cell span.lbl {
            font-size: 9px;
            color: #666;
            display: block;
        }
        .grid-cell span.val {
            font-weight: bold;
            color: #111;
        }
        .memo-cell {
            background: #fff;
            border: 1px solid #ccc;
            padding: 6px;
            font-size: 11px;
            margin-top: 4px;
            border-radius: 3px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("📦 メンテナンス申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "form_clear_key" not in st.session_state:
        st.session_state["form_clear_key"] = 0

    clear_suffix = f"_{st.session_state['form_clear_key']}"

    if f"ccode{clear_suffix}" not in st.session_state:
        st.session_state[f"ccode{clear_suffix}"] = ""
    if f"cname{clear_suffix}" not in st.session_state:
        st.session_state[f"cname{clear_suffix}"] = ""
    if f"scode{clear_suffix}" not in st.session_state:
        st.session_state[f"scode{clear_suffix}"] = ""
    if f"sname{clear_suffix}" not in st.session_state:
        st.session_state[f"sname{clear_suffix}"] = ""

    if "searched_ccode" not in st.session_state:
        st.session_state["searched_ccode"] = ""

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷プレビュー（スプレッドシート貼り付け・PDF印刷用）"
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with tab1:
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力", 
                value=st.session_state["searched_ccode"], 
                key=f"cust_code_search{clear_suffix}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary")

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
                            st.session_state["searched_ccode"] = str(cust_code_input)
                            st.session_state[f"ccode{clear_suffix}"] = str(cust_code_input)
                            st.session_state[f"sname{clear_suffix}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"cname{clear_suffix}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"scode{clear_suffix}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            
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

            with st.form("submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                st.write("**📋 入力情報**")
                
                row1_col1, row1_col2, row1_col3 = st.columns(3)
                customer_code = row1_col1.text_input("顧客コード", key=f"ccode{clear_suffix}")
                customer_name = row1_col2.text_input("顧客名", key=f"cname{clear_suffix}")
                store_code = row1_col3.text_input("加盟店コード", key=f"scode{clear_suffix}")

                row2_col1, row2_col2, row2_col3 = st.columns(3)
                store_name = row2_col1.text_input("加盟店名", key=f"sname{clear_suffix}")
                route_code = row2_col2.text_input("ルートコード", value="", key=f"rcode{clear_suffix}")
                delivery_date_val = row2_col3.date_input("納品日", value=None, key=f"ddate{clear_suffix}")
                delivery_date = delivery_date_val.strftime("%Y/%m/%d") if delivery_date_val else ""

                row3_col1, row3_col2, row3_col3 = st.columns(3)
                delivery_person = row3_col1.text_input("納品者", value=st.session_state["user_name"], key=f"dperson{clear_suffix}")
                applicant = row3_col2.text_input("申請者名", value=st.session_state["user_name"], key=f"app{clear_suffix}")

                st.write("---")
                st.write("**📦 発注商品（最大5件）**")
                items_flat = []
                for i in range(5):
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                    p_code = c1.text_input(f"商品コード {i+1}", key=f"p_{i}{clear_suffix}")
                    qty = c2.text_input(f"数量 {i+1}", value="", key=f"q_{i}{clear_suffix}")
                    price = c3.text_input(f"単価 {i+1}", value="", key=f"pr_{i}{clear_suffix}")
                    print_flg = c4.selectbox(f"伝票出力 {i+1}", ["", "有", "無"], index=0, key=f"flg_{i}{clear_suffix}")
                    
                    if p_code.strip():
                        items_flat.extend([p_code, qty, price, print_flg])
                    else:
                        items_flat.extend(["", "", "", ""])

                st.write("---")
                app_comment = st.text_area("申請コメント", placeholder="連絡事項や補足説明があれば入力してください", key=f"app_com{clear_suffix}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not route_code.strip() or not delivery_date:
                        st.error("⚠️ 「ルートコード」と「納品日」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                        
                        full_row = [
                            now_str, applicant, customer_code, customer_name,
                            store_name, store_code, delivery_date, route_code, delivery_person
                        ] + items_flat + [app_comment, "申請中", "", ""]

                        payload = {
                            "action": "SUBMIT_MAINTENANCE",
                            "target_sheet_url": TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["searched_ccode"] = ""
                            st.session_state["form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) >= 30:
                rejected_df = df[df.iloc[:, 30].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2
                        cust_name = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ""
                        rej_comment = str(row.iloc[32]) if len(row) > 32 and pd.notna(row.iloc[32]) else ""
                        
                        with st.expander(f"🔴 【差戻し】{cust_name} (行: {row_id}) | 理由: {rej_comment}"):
                            with st.form(key=f"resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")
                                
                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", key=f"re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", key=f"re_scode_{row_id}")

                                r2_1, r2_2, r2_3 = st.columns(3)
                                edit_store_name = r2_1.text_input("加盟店名", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", key=f"re_sname_{row_id}")
                                edit_route_code = r2_2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", key=f"re_rcode_{row_id}")
                                edit_deliv_date = r2_3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", key=f"re_ddate_{row_id}")

                                r3_1, r3_2, r3_3 = st.columns(3)
                                edit_deliv_person = r3_1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", key=f"re_dperson_{row_id}")
                                edit_applicant = r3_2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", key=f"re_app_{row_id}")

                                st.write("---")
                                st.write("**📦 発注商品修正**")
                                edit_items = []
                                for i in range(5):
                                    base_idx = 9 + (i * 4)
                                    p_val = str(row.iloc[base_idx]) if base_idx < len(row) and pd.notna(row.iloc[base_idx]) else ""
                                    q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else ""
                                    pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else ""
                                    flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else ""

                                    r1, r2, r3, r4 = st.columns([3, 2, 2, 2])
                                    p_in = r1.text_input(f"商品コード {i+1}", value=p_val, key=f"re_p_{row_id}_{i}")
                                    q_in = r2.text_input(f"数量 {i+1}", value=q_val, key=f"re_q_{row_id}_{i}")
                                    pr_in = r3.text_input(f"単価 {i+1}", value=pr_val, key=f"re_pr_{row_id}_{i}")
                                    
                                    opts = ["", "有", "無"]
                                    flg_idx = opts.index(flg_val) if flg_val in opts else 0
                                    flg_in = r4.selectbox(f"伝票出力 {i+1}", opts, index=flg_idx, key=f"re_flg_{row_id}_{i}")

                                    if p_in.strip():
                                        edit_items.extend([p_in, q_in, pr_in, flg_in])
                                    else:
                                        edit_items.extend(["", "", "", ""])

                                st.write("---")
                                edit_app_comment = st.text_area("申請コメント", value=str(row.iloc[29]) if len(row) > 29 and pd.notna(row.iloc[29]) else "", key=f"re_com_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_route_code.strip() or not edit_deliv_date.strip():
                                        st.error("⚠️ 「ルートコード」と「納品日」は必須項目です。")
                                    else:
                                        updated_row = [
                                            str(row.iloc[0]), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code, edit_deliv_date, edit_route_code, edit_deliv_person
                                        ] + edit_items + [edit_app_comment, "申請中", "", ""]

                                        payload = {
                                            "action": "RESUBMIT_MAINTENANCE",
                                            "target_sheet_url": TARGET_SHEET_URL,
                                            "row_index": row_id,
                                            "updated_row": updated_row
                                        }
                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            st.toast("再申請が完了しました！")
                                            time.sleep(1)
                                            st.rerun()
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 2: 管理職承認
    # ==========================================
    with tab2:
        st.subheader("🔍 管理職チェック")
        try:
            st.cache_data.clear()
            df = pd.read_csv(TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) >= 30:
                pending_df = df[df.iloc[:, 30].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2
                        cust_name = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ""
                        cust_code = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ""

                        with st.expander(f"⏳ 【承認待ち】{cust_name}（{cust_code}） | 行: {row_id}"):
                            with st.form(key=f"mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")
                                
                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", key=f"m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", key=f"m_scode_{row_id}")

                                m2_1, m2_2, m2_3 = st.columns(3)
                                edit_sname = m2_1.text_input("加盟店名", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", key=f"m_sname_{row_id}")
                                edit_rcode = m2_2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", key=f"m_rcode_{row_id}")
                                edit_ddate = m2_3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", key=f"m_ddate_{row_id}")

                                m3_1, m3_2, m3_3 = st.columns(3)
                                edit_dperson = m3_1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", key=f"m_dperson_{row_id}")
                                edit_app = m3_2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", key=f"m_app_{row_id}")

                                st.write("---")
                                st.write("**📦 発注商品（修正可能）**")
                                edit_items = []
                                for i in range(5):
                                    base_idx = 9 + (i * 4)
                                    p_val = str(row.iloc[base_idx]) if base_idx < len(row) and pd.notna(row.iloc[base_idx]) else ""
                                    q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else ""
                                    pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else ""
                                    flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else ""

                                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                                    p_in = c1.text_input(f"商品コード {i+1}", value=p_val, key=f"m_p_{row_id}_{i}")
                                    q_in = c2.text_input(f"数量 {i+1}", value=q_val, key=f"m_q_{row_id}_{i}")
                                    pr_in = c3.text_input(f"単価 {i+1}", value=pr_val, key=f"m_pr_{row_id}_{i}")
                                    
                                    opts = ["", "有", "無"]
                                    flg_idx = opts.index(flg_val) if flg_val in opts else 0
                                    flg_in = c4.selectbox(f"伝票出力 {i+1}", opts, index=flg_idx, key=f"m_flg_{row_id}_{i}")

                                    if p_in.strip():
                                        edit_items.extend([p_in, q_in, pr_in, flg_in])
                                    else:
                                        edit_items.extend(["", "", "", ""])

                                st.write("---")
                                edit_app_comment = st.text_area("申請者コメント", value=str(row.iloc[29]) if len(row) > 29 and pd.notna(row.iloc[29]) else "", key=f"m_app_com_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"mgr_com_{row_id}")
                                
                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認（変更内容を反映）", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    updated_row = [
                                        str(row.iloc[0]), edit_app, edit_ccode, edit_cname,
                                        edit_sname, edit_scode, edit_ddate, edit_rcode, edit_dperson
                                    ] + edit_items + [edit_app_comment]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_MAINTENANCE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_MAINTENANCE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_MAINTENANCE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": TARGET_SHEET_URL,
                                        "row_index": row_id,
                                        "updated_row": updated_row
                                    }
                                    res = post_to_gas(payload)
                                    if res.get("status") == "success":
                                        st.toast("処理が完了しました！")
                                        time.sleep(1)
                                        st.rerun()
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 3: 業務担当
    # ==========================================
    with tab3:
        st.subheader("🚚 業務担当メンテナンス処理")
        try:
            st.cache_data.clear()
            df = pd.read_csv(TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) < 31:
                st.info("現在、処理可能なデータはありません。")
            else:
                ac_series = df.iloc[:, 30].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, 30].isna()) & 
                    (~ac_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")
                    
                    sort_by_date = st.checkbox("📅 納品日の早い順（昇順）で並び替える", value=False, key="t3_sort_date")

                    if sort_by_date:
                        approved_df = approved_df.copy()
                        approved_df["_sort_date"] = pd.to_datetime(approved_df.iloc[:, 6], errors="coerce")
                        approved_df = approved_df.sort_values(by="_sort_date", ascending=True, na_position="last")

                    iterator = approved_df.iterrows() if sort_by_date else approved_df.iloc[::-1].iterrows()

                    for idx, row in iterator:
                        row_id = idx + 2
                        timestamp = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
                        cust_code = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ""
                        cust_name = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ""
                        mgr_name = str(row.iloc[30]) if pd.notna(row.iloc[30]) else ""
                        deliv_date_str = str(row.iloc[6]) if pd.notna(row.iloc[6]) else "未設定"

                        expander_label = f"🟢【納品日: {deliv_date_str}】{cust_name}（{cust_code}） | 承認者: {mgr_name}"

                        with st.expander(expander_label):
                            st.write("**📋 申請内容**")
                            
                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", disabled=True, key=f"v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", disabled=True, key=f"v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", disabled=True, key=f"v_scode_{row_id}")

                            o2_c1, o2_c2, o2_c3 = st.columns(3)
                            o2_c1.text_input("加盟店名", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", disabled=True, key=f"v_sname_{row_id}")
                            o2_c2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", disabled=True, key=f"v_rcode_{row_id}")
                            o2_c3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", disabled=True, key=f"v_ddate_{row_id}")

                            o3_c1, o3_c2, o3_c3 = st.columns(3)
                            o3_c1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", disabled=True, key=f"v_dperson_{row_id}")
                            o3_c2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", disabled=True, key=f"v_app_{row_id}")
                            o3_c3.text_input("承認者", value=mgr_name, disabled=True, key=f"v_mgr_{row_id}")

                            st.write("---")
                            st.write("**📦 発注商品**")
                            for i in range(5):
                                base_idx = 9 + (i * 4)
                                p_val = str(row.iloc[base_idx]) if base_idx < len(row) and pd.notna(row.iloc[base_idx]) else ""
                                if p_val.strip():
                                    q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else ""
                                    pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else ""
                                    flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else ""
                                    
                                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                                    c1.text_input(f"商品コード {i+1}", value=p_val, disabled=True, key=f"v_p_{row_id}_{i}")
                                    c2.text_input(f"数量 {i+1}", value=q_val, disabled=True, key=f"v_q_{row_id}_{i}")
                                    c3.text_input(f"単価 {i+1}", value=pr_val, disabled=True, key=f"v_pr_{row_id}_{i}")
                                    c4.text_input(f"伝票出力 {i+1}", value=flg_val, disabled=True, key=f"v_flg_{row_id}_{i}")

                            app_com_val = str(row.iloc[29]) if len(row) > 29 and pd.notna(row.iloc[29]) else ""
                            if app_com_val.strip():
                                st.text_area("申請者コメント", value=app_com_val, disabled=True, key=f"v_com_{row_id}")

                            st.write("---")
                            with st.form(key=f"transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_memo = st.text_input("業務メモ / 伝票番号など（任意）", key=f"op_memo_{row_id}")
                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"op_rej_reason_{row_id}")
                                
                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(df.columns))]
                                    transfer_row = clean_base_row + [action_time, op_user, op_memo]

                                    payload = {
                                        "action": "TRANSFER_TO_OPERATOR",
                                        "target_sheet_url": TARGET_SHEET_URL,
                                        "dest_sheet_url": DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "op_user": op_user,
                                        "action_time": action_time
                                    }

                                    with st.spinner("業務シートへ転記中..."):
                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            st.cache_data.clear()
                                            st.toast("🎉 業務用スプレッドシートへの転記が完了しました！", icon="🎉")
                                            time.sleep(1.5)
                                            st.rerun()

                                elif btn_op_reject:
                                    if not op_reject_reason.strip():
                                        st.error("⚠️ 差戻しを行う場合は「差戻し理由」を入力してください。")
                                    else:
                                        clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(df.columns))]
                                        base_data = clean_base_row[:29]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_MAINTENANCE",
                                            "target_sheet_url": TARGET_SHEET_URL,
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
    # TAB 4: メンテナンスチェック画面（書き換え・修正済み部分）
    # ==========================================
    with tab4:
        st.subheader("✅ メンテナンスチェック画面")

        try:
            st.cache_data.clear()
            df_dest = pd.read_csv(DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="chk_show_checked")

                if not show_checked and len(df_dest.columns) > CHECK_TIME_COL_IDX:
                    unchecked_mask = df_dest.iloc[:, CHECK_TIME_COL_IDX].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                col_sort1, col_sort2 = st.columns([3, 1])
                sort_store = col_sort1.checkbox("🏪 加盟店別（店舗名）で並び替える", value=False, key="chk_sort_store")
                sort_order = col_sort2.selectbox("並び順", ["昇順 (あ〜わ)", "降順 (わ〜あ)"], index=0, key="chk_sort_order", label_visibility="collapsed")

                df_display = df_dest.copy()
                if sort_store:
                    store_col_idx = 4
                    if len(df_display.columns) > store_col_idx:
                        is_ascending = (sort_order == "昇順 (あ〜わ)")
                        df_display["_sort_store"] = df_display.iloc[:, store_col_idx].fillna("")
                        df_display = df_display.sort_values(by="_sort_store", ascending=is_ascending)

                iterator_chk = df_display.iterrows()

                for idx, row in iterator_chk:
                    row_id = idx + 2
                    cust_name = str(row.iloc[3]) if len(row) > 3 and pd.notna(row.iloc[3]) else ""
                    store_name = str(row.iloc[4]) if len(row) > 4 and pd.notna(row.iloc[4]) else ""
                    cust_code = str(row.iloc[2]) if len(row) > 2 and pd.notna(row.iloc[2]) else ""
                    deliv_date = str(row.iloc[6]) if len(row) > 6 and pd.notna(row.iloc[6]) else ""
                    
                    delivery_person_val = str(row.iloc[8]) if len(row) > 8 and pd.notna(row.iloc[8]) else ""
                    mgr_name_val = str(row.iloc[30]) if len(row) > 30 and pd.notna(row.iloc[30]) else "不明"
                    op_user_val = str(row.iloc[OP_USER_COL_IDX]) if len(row) > OP_USER_COL_IDX and pd.notna(row.iloc[OP_USER_COL_IDX]) else "不明"

                    checked_time_val = str(row.iloc[CHECK_TIME_COL_IDX]) if len(row) > CHECK_TIME_COL_IDX and pd.notna(row.iloc[CHECK_TIME_COL_IDX]) else ""
                    checked_user_val = str(row.iloc[CHECK_USER_COL_IDX]) if len(row) > CHECK_USER_COL_IDX and pd.notna(row.iloc[CHECK_USER_COL_IDX]) else ""

                    expander_label = f"📌 【加盟店: {store_name or '未設定'}】 顧客名: {cust_name}（{cust_code}） | 納品日: {deliv_date}"
                    if checked_time_val:
                        expander_label += f" ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=cust_code, disabled=True, key=f"chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=cust_name, disabled=True, key=f"chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=str(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) else "", disabled=True, key=f"chk_scode_{row_id}")

                            c4, c5, c6 = st.columns(3)
                            c4.text_input("加盟店名", value=store_name, disabled=True, key=f"chk_sname_{row_id}")
                            c5.text_input("ルートコード", value=str(row.iloc[7]) if len(row) > 7 and pd.notna(row.iloc[7]) else "", disabled=True, key=f"chk_rcode_{row_id}")
                            c6.text_input("納品日", value=deliv_date, disabled=True, key=f"chk_ddate_{row_id}")

                            c7, c8, c9 = st.columns(3)
                            c7.text_input("納品者", value=delivery_person_val, disabled=True, key=f"chk_dperson_{row_id}")
                            c8.text_input("承認者", value=mgr_name_val, disabled=True, key=f"chk_mgr_{row_id}")
                            c9.text_input("処理者", value=op_user_val, disabled=True, key=f"chk_op_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            st.write("---")
                            st.write("**📦 登録商品明細**")
                            has_item = False
                            for i in range(5):
                                base_idx = 9 + (i * 4)
                                p_val = str(row.iloc[base_idx]) if base_idx < len(row) and pd.notna(row.iloc[base_idx]) else ""
                                if p_val.strip():
                                    has_item = True
                                    q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else ""
                                    pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else ""
                                    flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else ""
                                    
                                    ic1, ic2, ic3, ic4 = st.columns([3, 2, 2, 2])
                                    ic1.text_input(f"商品コード {i+1}", value=p_val, disabled=True, key=f"chk_p_{row_id}_{i}")
                                    ic2.text_input(f"数量 {i+1}", value=q_val, disabled=True, key=f"chk_q_{row_id}_{i}")
                                    ic3.text_input(f"単価 {i+1}", value=pr_val, disabled=True, key=f"chk_pr_{row_id}_{i}")
                                    ic4.text_input(f"伝票出力 {i+1}", value=flg_val, disabled=True, key=f"chk_flg_{row_id}_{i}")
                            
                            if not has_item:
                                st.info("登録されている商品明細はありません。")

                            st.write("---")
                            chk_memo = st.text_input("チェック用メモ / 特記事項", key=f"chk_memo_{row_id}")
                            
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < CHECK_USER_COL_IDX + 1:
                                    clean_base_row.append("")

                                clean_base_row[CHECK_TIME_COL_IDX] = check_time
                                clean_base_row[CHECK_USER_COL_IDX] = checker_name
                                # ※ PRINT_TIME_COL_IDX（AL列）はここでは触らない。
                                #   clean_base_row はAK列までしか埋めていないため、GASへのupdated_rowも
                                #   AK列までしか含まれず、既存のAL列（印刷日時）は上書きされず保持される。

                                payload = {
                                    "action": "UPDATE_MAINTENANCE_CHECK",
                                    "target_sheet_url": DEST_SHEET_URL,
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
    with tab5:
        st.subheader("🖨️ 加盟店別 印刷プレビュー（スプレッドシート貼り付け・PDF印刷用）")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータ（AJ列にチェック日時が入っている行）だけを対象にする
                if len(df_print.columns) > CHECK_TIME_COL_IDX:
                    checked_mask = df_print.iloc[:, CHECK_TIME_COL_IDX].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（AL列に印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > PRINT_TIME_COL_IDX:
                    not_printed_mask = df_print.iloc[:, PRINT_TIME_COL_IDX].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = 4
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="print_store_select_v2")

                    if selected_store:
                        # ※ 行番号（row_id = 元のインデックス + 2）をMARK_PRINTEDで使うため、
                        #   ここでは reset_index しない（他のTABと同じ row_id の考え方）
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大3件まで配置されます。")

                        def build_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            store_code = str(r_row.iloc[5]) if len(r_row) > 5 and pd.notna(r_row.iloc[5]) else ""
                            raw_cname = str(r_row.iloc[3]) if len(r_row) > 3 and pd.notna(r_row.iloc[3]) else ""
                            cust_name = f"{raw_cname} 様" if raw_cname.strip() else ""

                            manager = str(r_row.iloc[30]) if len(r_row) > 30 and pd.notna(r_row.iloc[30]) else "未確認"
                            operator = str(r_row.iloc[OP_USER_COL_IDX]) if len(r_row) > OP_USER_COL_IDX and pd.notna(r_row.iloc[OP_USER_COL_IDX]) else st.session_state["user_name"]

                            cust_code = str(r_row.iloc[2]) if len(r_row) > 2 and pd.notna(r_row.iloc[2]) else ""
                            applicant = str(r_row.iloc[1]) if len(r_row) > 1 and pd.notna(r_row.iloc[1]) else ""
                            delivery_person = str(r_row.iloc[8]) if len(r_row) > 8 and pd.notna(r_row.iloc[8]) else ""
                            delivery_date = str(r_row.iloc[6]) if len(r_row) > 6 and pd.notna(r_row.iloc[6]) else ""
                            route_code = str(r_row.iloc[7]) if len(r_row) > 7 and pd.notna(r_row.iloc[7]) else ""

                            special_note = str(r_row.iloc[29]) if len(r_row) > 29 and pd.notna(r_row.iloc[29]) else "特記事項なし"

                            items = []
                            for pi in range(5):
                                b_idx = 9 + (pi * 4)
                                p_code = str(r_row.iloc[b_idx]) if b_idx < len(r_row) and pd.notna(r_row.iloc[b_idx]) else ""
                                p_qty = str(r_row.iloc[b_idx + 1]) if b_idx + 1 < len(r_row) and pd.notna(r_row.iloc[b_idx + 1]) else ""
                                p_price = str(r_row.iloc[b_idx + 2]) if b_idx + 2 < len(r_row) and pd.notna(r_row.iloc[b_idx + 2]) else ""
                                p_flg = str(r_row.iloc[b_idx + 3]) if b_idx + 3 < len(r_row) and pd.notna(r_row.iloc[b_idx + 3]) else ""
                                items.append((p_code, p_qty, p_price, p_flg))

                            return {
                                "store_code": store_code, "cust_name": cust_name,
                                "manager": manager, "operator": operator,
                                "cust_code": cust_code, "applicant": applicant,
                                "delivery_person": delivery_person, "delivery_date": delivery_date,
                                "route_code": route_code, "special_note": special_note,
                                "items": items,
                            }

                        def matrix_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした13行×5列（A〜E）の行列に変換する。
                            1行目=A/B/D/E(加盟店コード/顧客名/責任者/処理者)、2行おきに商品明細5件、
                            最終行=特記事項。空欄になる行（間の行）は全て空文字にする。
                            ※GASへは1件あたり1回のsetValuesでまとめて送るための行列（cell単位で送ると
                            リクエスト回数が増えてタイムアウトするため）"""
                            blank = ["", "", "", "", ""]
                            if not rec:
                                return [blank[:] for _ in range(13)]

                            extra_e = [rec["cust_code"], rec["applicant"], rec["delivery_person"], rec["delivery_date"], rec["route_code"]]
                            matrix = [blank[:] for _ in range(13)]
                            matrix[0] = [rec["store_code"], rec["cust_name"], "", rec["manager"], rec["operator"]]
                            for i_item, item_row in enumerate([2, 4, 6, 8, 10]):
                                p_code, p_qty, p_price, p_flg = rec["items"][i_item]
                                matrix[item_row] = [p_code, p_qty, p_price, p_flg, extra_e[i_item]]
                            matrix[12] = [rec["special_note"], "", "", "", ""]
                            return matrix

                        chunk_size = 3
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            # C1＝加盟店名＋「 様」、A4〜A16／A19〜A31／A34〜A46＝1〜3件目（base_row = 4, 19, 34）
                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]  # 印刷済みマーク用の実際の行番号

                            for slot in range(3):
                                base_row = 4 + slot * 15
                                rec = build_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "matrix": matrix_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    items_df = pd.DataFrame(rec["items"], columns=["商品記号", "発注数", "単価", "伝票出力"])
                                    st.dataframe(items_df, use_container_width=True, hide_index=True)
                                    st.caption(f"顧客コード: {rec['cust_code']} ｜ 申請者: {rec['applicant']} ｜ 納品者: {rec['delivery_person']} ｜ 納品日: {rec['delivery_date']} ｜ ルートコード: {rec['route_code']}")
                                    st.caption(f"特記事項: {rec['special_note']}")

                            if st.button("📥 反映してPDFを作成する", key=f"print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": PRINT_SHEET_URL,
                                    "store_name": selected_store,
                                    "c1_value": c1_value,
                                    "blocks": blocks,
                                }
                                with st.spinner("印刷用スプレッドシートへ反映しています..."):
                                    res = post_to_gas(payload)

                                if res.get("status") == "success":
                                    # 印刷済みマーク（AL列＝印刷日時）を付けて、以後この印刷画面に出てこないようにする
                                    print_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                    mark_payload = {
                                        "action": "MARK_PRINTED",
                                        "target_sheet_url": DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        # このページの実件数分（1件なら1〜16行目、2件なら1〜31行目…）だけをPDF化する。
                                        # 空のブロックまで印刷されないよう、件数に応じて末尾行を切り詰める。
                                        pdf_row_end = 1 + len(chunk) * 15
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(build_print_pdf_url(row_end=pdf_row_end), timeout=30)
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                            )
                                    except Exception as pdf_err:
                                        st.warning(
                                            f"スプレッドシートへの反映は完了しましたが、PDF取得中にエラーが発生しました: {pdf_err}　"
                                            f"[印刷用スプレッドシートを開く]({PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                        )
                                else:
                                    st.error(f"反映に失敗しました: {res.get('message')}")

                            st.write("---")

        except Exception as e:
            st.error(f"印刷データの読み込みエラー: {e}")

# アプリ実行
if __name__ == "__main__":
    st.set_page_config(page_title="メンテナンス申請管理システム", layout="wide")
    maintenance_admin_screen()
