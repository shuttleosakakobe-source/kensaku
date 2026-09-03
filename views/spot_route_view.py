"""「単発ルート変更」モード（申請・承認・業務転記・チェック・印刷の5タブ）。
基本構成は「ルート変更」モードと同じだが、変更前後の「担当者」の代わりに
変更前後の「日付」を扱う点が異なる（単発＝1回限りのルート変更のため、次回訪問日は不要）。
印刷フォーマットも「次回訪問日」欄が無く、「理由」欄1つに統合されている点がルート変更と異なる。"""
import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

from views.maint_common import (
    JST, CUSTOMER_MASTER_CSV, PRINT_SHEET_ID,
    post_to_gas, build_print_pdf_url,
    tab_visible, RESTRICTED_TAB_MSG,

)
from views.route_view import get_route_lookup


# ==========================================
# 「単発ルート変更」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
SR_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=1712868005#gid=1712868005"
SR_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=1712868005"
# TAB3・TAB4用（転記〜チェック）
SR_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=640102641#gid=640102641"
SR_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=640102641"

# 単発ルート変更：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G 変更前ルート, H 変更前日付, I 変更後ルート, J 変更後日付,
# K コメント, L 理由, M 連絡担当者, N サイン(ステータス/承認者名), O 日時(承認日時), P コメント(承認コメント/差戻し理由),
# Q 処理日, R 処理者, S チェック日, T チェック者, U 印刷済
SR_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "route_before": 6, "date_before": 7,
    "route_after": 8, "date_after": 9,
    "comment": 10,
    "reason": 11, "contact_person": 12,
    "status_sign": 13, "approval_time": 14, "approval_comment": 15,
    "process_time": 16, "process_user": 17,
    "check_time": 18, "check_user": 19,
    "print_time": 20,
}

# 「単発ルート変更」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
SR_PRINT_SHEET_GID = "1222824394"
SR_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={SR_PRINT_SHEET_GID}#gid={SR_PRINT_SHEET_GID}"
# 1ページに4件まで配置。各件の起点行（A列）：1件目=4, 2件目=15, 3件目=26, 4件目=38（ルート変更と同じテンプレート構成）
SR_PRINT_BASE_ROWS = [4, 15, 26, 38]


def render_spot_route_change_tabs():
    # 💡 【CSS調整】disabled入力の文字が薄くて読みにくいのを解消
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

    st.header("🔄 単発ルート変更申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "spot_route_form_clear_key" not in st.session_state:
        st.session_state["spot_route_form_clear_key"] = 0

    rclear = f"_{st.session_state['spot_route_form_clear_key']}"

    for _key, _default in [
        (f"sr_ccode{rclear}", ""), (f"sr_cname{rclear}", ""),
        (f"sr_scode{rclear}", ""), (f"sr_sname{rclear}", ""),
        (f"sr_rbefore{rclear}", ""),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    if "spot_route_searched_ccode" not in st.session_state:
        st.session_state["spot_route_searched_ccode"] = ""

    _s_tab_all_labels = [
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
    ]
    _s_tab_visible_nums = [_n for _n in range(1, 6) if tab_visible(_n)]
    if not _s_tab_visible_nums:
        st.info(RESTRICTED_TAB_MSG)
        _tab_map = {}
    else:
        _s_tab_objs = st.tabs([_s_tab_all_labels[_n - 1] for _n in _s_tab_visible_nums])
        _tab_map = dict(zip(_s_tab_visible_nums, _s_tab_objs))

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    def _tab1_body():
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["spot_route_searched_ccode"],
                key=f"sr_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"sr_search_btn{rclear}")

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
                            route_codes, _staff_codes, _staff_names = get_route_lookup(cust_code_input)

                            st.session_state["spot_route_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"sr_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"sr_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"sr_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"sr_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            # 💡 変更前ルートが複数該当する場合はプルダウンで選ばせるため、
                            #    候補リストをまるごと保存しておく（1件だけの場合は従来通り自動入力）
                            st.session_state[f"sr_rbefore_opts{rclear}"] = route_codes
                            st.session_state[f"sr_rbefore{rclear}"] = route_codes[0] if len(route_codes) == 1 else ""

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
            customer_code = row1_col1.text_input("顧客コード", key=f"sr_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"sr_cname{rclear}")
            store_code = row1_col3.text_input("加盟店コード", key=f"sr_scode{rclear}")

            row2_col1, row2_col2 = st.columns(2)
            store_name = row2_col1.text_input("加盟店", key=f"sr_sname{rclear}")
            applicant = row2_col2.text_input("担当者", value=st.session_state["user_name"], key=f"sr_app{rclear}")

            st.write("---")
            st.write("**🗺️ ルート情報**")
            row3_col1, row3_col2 = st.columns(2)
            sr_rbefore_opts = st.session_state.get(f"sr_rbefore_opts{rclear}", [])
            if len(sr_rbefore_opts) > 1:
                # 💡 変更前ルートの候補が複数ある場合は自動選択せず、プルダウンで選ばせる
                route_before = row3_col1.selectbox(
                    "変更前ルート（複数該当・対象を選択）",
                    options=sr_rbefore_opts,
                    key=f"sr_rbefore_select{rclear}"
                )
            else:
                route_before = row3_col1.text_input("変更前ルート", key=f"sr_rbefore{rclear}", disabled=True)
            date_before_val = row3_col2.date_input("変更前日付", value=None, key=f"sr_dbefore{rclear}")
            date_before = date_before_val.strftime("%Y/%m/%d") if date_before_val else ""

            row4_col1, row4_col2 = st.columns(2)
            route_after = row4_col1.text_input("変更後ルート", key=f"sr_rafter{rclear}")
            date_after_val = row4_col2.date_input("変更後日付", value=None, key=f"sr_dafter{rclear}")
            date_after = date_after_val.strftime("%Y/%m/%d") if date_after_val else ""

            st.write("---")

            with st.form("sr_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                sr_comment = st.text_area("コメント", placeholder="連絡事項や補足説明があれば入力してください", key=f"sr_com{rclear}")
                sr_reason = st.text_input("理由", key=f"sr_reason{rclear}")
                sr_contact = st.text_input("連絡担当者", key=f"sr_contact{rclear}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip() or not route_after.strip():
                        st.error("⚠️ 「顧客コード」と「変更後ルート」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [
                            now_str, applicant, customer_code, customer_name, store_name, store_code,
                            route_before, date_before,
                            route_after, date_after,
                            sr_comment, sr_reason, sr_contact, "申請中", "", ""
                        ]

                        payload = {
                            "action": "SUBMIT_SPOT_ROUTE_CHANGE",
                            "target_sheet_url": SR_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["spot_route_searched_ccode"] = ""
                            st.session_state["spot_route_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(SR_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > SR_COL["status_sign"]:
                rejected_df = df[df.iloc[:, SR_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = SR_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            with st.form(key=f"sr_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"sr_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"sr_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"sr_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"sr_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"sr_re_app_{row_id}")

                                r3_1, r3_2 = st.columns(2)
                                edit_route_before = r3_1.text_input("変更前ルート", value=_v("route_before"), key=f"sr_re_rbefore_{row_id}")
                                edit_date_before = r3_2.text_input("変更前日付", value=_v("date_before"), key=f"sr_re_dbefore_{row_id}")

                                r4_1, r4_2 = st.columns(2)
                                edit_route_after = r4_1.text_input("変更後ルート", value=_v("route_after"), key=f"sr_re_rafter_{row_id}")
                                edit_date_after = r4_2.text_input("変更後日付", value=_v("date_after"), key=f"sr_re_dafter_{row_id}")

                                st.write("---")
                                edit_comment = st.text_area("コメント", value=_v("comment"), key=f"sr_re_com_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"sr_re_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者", value=_v("contact_person"), key=f"sr_re_contact_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip() or not edit_route_after.strip():
                                        st.error("⚠️ 「顧客コード」と「変更後ルート」は必須項目です。")
                                    else:
                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code,
                                            edit_route_before, edit_date_before,
                                            edit_route_after, edit_date_after,
                                            edit_comment, edit_reason, edit_contact, "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_SPOT_ROUTE_CHANGE",
                                            "target_sheet_url": SR_TARGET_SHEET_URL,
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
    if 1 in _tab_map:
        with _tab_map[1]:
            _tab1_body()
    def _tab2_body():
        st.subheader("🔍 管理職チェック")
        try:
            st.cache_data.clear()
            df = pd.read_csv(SR_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > SR_COL["status_sign"]:
                pending_df = df[df.iloc[:, SR_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = SR_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            with st.form(key=f"sr_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"sr_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"sr_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"sr_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"sr_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"sr_m_app_{row_id}")

                                m3_1, m3_2 = st.columns(2)
                                edit_rbefore = m3_1.text_input("変更前ルート", value=_v("route_before"), key=f"sr_m_rbefore_{row_id}")
                                edit_dbefore = m3_2.text_input("変更前日付", value=_v("date_before"), key=f"sr_m_dbefore_{row_id}")

                                m4_1, m4_2 = st.columns(2)
                                edit_rafter = m4_1.text_input("変更後ルート", value=_v("route_after"), key=f"sr_m_rafter_{row_id}")
                                edit_dafter = m4_2.text_input("変更後日付", value=_v("date_after"), key=f"sr_m_dafter_{row_id}")

                                st.write("---")
                                edit_comment = st.text_area("申請者コメント", value=_v("comment"), key=f"sr_m_com_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"sr_m_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者", value=_v("contact_person"), key=f"sr_m_contact_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"sr_mgr_com_{row_id}")

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
                                        edit_rbefore, edit_dbefore,
                                        edit_rafter, edit_dafter,
                                        edit_comment, edit_reason, edit_contact
                                    ]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_SPOT_ROUTE_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_SPOT_ROUTE_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_SPOT_ROUTE_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": SR_TARGET_SHEET_URL,
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
    if 2 in _tab_map:
        with _tab_map[2]:
            _tab2_body()
    def _tab3_body():
        st.subheader("🚚 業務担当メンテナンス処理")
        try:
            st.cache_data.clear()
            df = pd.read_csv(SR_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= SR_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, SR_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, SR_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = SR_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"sr_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"sr_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"sr_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"sr_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"sr_v_app_{row_id}")

                            o3_c1, o3_c2 = st.columns(2)
                            o3_c1.text_input("変更前ルート", value=_v("route_before"), disabled=True, key=f"sr_v_rbefore_{row_id}")
                            o3_c2.text_input("変更前日付", value=_v("date_before"), disabled=True, key=f"sr_v_dbefore_{row_id}")

                            o4_c1, o4_c2 = st.columns(2)
                            o4_c1.text_input("変更後ルート", value=_v("route_after"), disabled=True, key=f"sr_v_rafter_{row_id}")
                            o4_c2.text_input("変更後日付", value=_v("date_after"), disabled=True, key=f"sr_v_dafter_{row_id}")

                            o5_c1, o5_c2 = st.columns(2)
                            o5_c1.text_input("承認者", value=mgr_name, disabled=True, key=f"sr_v_mgr_{row_id}")

                            comment_val = _v("comment")
                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            if comment_val.strip() or reason_val.strip() or contact_val.strip():
                                st.write("---")
                                if comment_val.strip():
                                    st.text_area("申請者コメント", value=comment_val, disabled=True, key=f"sr_v_com_{row_id}")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"sr_v_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者", value=contact_val, disabled=True, key=f"sr_v_contact_{row_id}")

                            st.write("---")
                            with st.form(key=f"sr_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"sr_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(SR_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_SPOT_ROUTE_TO_OPERATOR",
                                        "target_sheet_url": SR_TARGET_SHEET_URL,
                                        "dest_sheet_url": SR_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": SR_COL["status_sign"] + 1,
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
                                            for i in range(SR_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_SPOT_ROUTE_CHANGE",
                                            "target_sheet_url": SR_TARGET_SHEET_URL,
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
    if 3 in _tab_map:
        with _tab_map[3]:
            _tab3_body()
    def _tab4_body():
        st.subheader("✅ メンテナンスチェック画面")

        try:
            st.cache_data.clear()
            df_dest = pd.read_csv(SR_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="sr_chk_show_checked")

                if not show_checked and len(df_dest.columns) > SR_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, SR_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = SR_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"sr_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"sr_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"sr_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"sr_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"sr_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"sr_chk_app_{row_id}")

                            c6, c7 = st.columns(2)
                            c6.text_input("変更前ルート", value=_v("route_before"), disabled=True, key=f"sr_chk_rbefore_{row_id}")
                            c7.text_input("変更前日付", value=_v("date_before"), disabled=True, key=f"sr_chk_dbefore_{row_id}")

                            c8, c9 = st.columns(2)
                            c8.text_input("変更後ルート", value=_v("route_after"), disabled=True, key=f"sr_chk_rafter_{row_id}")
                            c9.text_input("変更後日付", value=_v("date_after"), disabled=True, key=f"sr_chk_dafter_{row_id}")

                            c10, c11 = st.columns(2)
                            c10.text_input("処理者", value=op_user_val, disabled=True, key=f"sr_chk_op_{row_id}")
                            c11.text_input("承認者", value=mgr_name_val, disabled=True, key=f"sr_chk_mgr_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            comment_val = _v("comment")
                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            if comment_val.strip() or reason_val.strip() or contact_val.strip():
                                st.write("---")
                                if comment_val.strip():
                                    st.text_area("申請者コメント", value=comment_val, disabled=True, key=f"sr_chk_com_{row_id}")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"sr_chk_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者", value=contact_val, disabled=True, key=f"sr_chk_contact_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"sr_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"sr_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < SR_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[SR_COL["check_time"]] = check_time
                                clean_base_row[SR_COL["check_user"]] = checker_name

                                payload = {
                                    "action": "UPDATE_SPOT_ROUTE_CHECK",
                                    "target_sheet_url": SR_DEST_SHEET_URL,
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
    # TAB 5: 加盟店別 印刷プレビュー
    # ==========================================
    if 4 in _tab_map:
        with _tab_map[4]:
            _tab4_body()
    def _tab5_body():
        st.subheader("🖨️ 加盟店別 印刷")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(SR_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > SR_COL["check_time"]:
                    checked_mask = df_print.iloc[:, SR_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > SR_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, SR_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = SR_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="sr_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(SR_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_spot_route_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = SR_COL[col_key]
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
                                "date_before": _f("date_before"), "date_after": _f("date_after"),
                                "applicant": _f("applicant"),
                                "reason": _f("reason"),
                                "comment": _f("comment") or "特記事項なし",
                                "contact_disp": contact_disp,
                            }

                        def spot_route_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            C1=加盟店名, A/B/D/E(+0)=加盟店コード/顧客名/責任者/処理者,
                            A/C/E(+2)=変更前ルート/変更後ルート/シャトルコード(顧客コード),
                            A/C/E(+4)=変更前日付/変更後日付/提出者,
                            A(+6)=理由（次回訪問日欄と統合され、A〜E結合の1セルのみ）,
                            A/E(+8)=特記事項/連絡担当者
                            ※ルート変更のテンプレートと違い、(+6)は「変更前担当者/変更後担当者」に
                            相当する欄自体が無く、「次回訪問日」と「理由」を統合した1セルだけになっている"""
                            if not rec:
                                rec = {k: "" for k in [
                                    "store_code", "cust_name", "manager", "operator",
                                    "route_before", "route_after", "cust_code",
                                    "date_before", "date_after", "applicant",
                                    "reason", "comment", "contact_disp",
                                ]}
                            return [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 2, "value": rec["cust_name"]},
                                {"offset": 0, "col": 4, "value": rec["manager"]},
                                {"offset": 0, "col": 5, "value": rec["operator"]},
                                {"offset": 2, "col": 1, "value": rec["route_before"]},
                                {"offset": 2, "col": 3, "value": rec["route_after"]},
                                {"offset": 2, "col": 5, "value": rec["cust_code"]},
                                {"offset": 4, "col": 1, "value": rec["date_before"]},
                                {"offset": 4, "col": 3, "value": rec["date_after"]},
                                {"offset": 4, "col": 5, "value": rec["applicant"]},
                                {"offset": 6, "col": 1, "value": rec["reason"]},
                                {"offset": 8, "col": 1, "value": rec["comment"]},
                                {"offset": 8, "col": 5, "value": rec["contact_disp"]},
                            ]

                        chunk_size = len(SR_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(SR_PRINT_BASE_ROWS):
                                rec = build_spot_route_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": spot_route_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    st.caption(f"変更前ルート: {rec['route_before']} → 変更後ルート: {rec['route_after']} ｜ シャトルコード（顧客コード）: {rec['cust_code']}")
                                    st.caption(f"変更前日付: {rec['date_before']} → 変更後日付: {rec['date_after']} ｜ 提出者: {rec['applicant']}")
                                    st.caption(f"理由: {rec['reason']} ｜ 連絡担当者: {rec['contact_disp']}")
                                    st.caption(f"特記事項: {rec['comment']}")

                            if st.button("📥 反映してPDFを作成する", key=f"sr_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": SR_PRINT_SHEET_URL,
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
                                        "target_sheet_url": SR_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": SR_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = SR_PRINT_BASE_ROWS[len(chunk) - 1] + 8 if len(chunk) > 0 else 12
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, gid=SR_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_spot_route_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"sr_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({SR_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                            )
                                    except Exception as pdf_e:
                                        st.warning(f"PDF作成中にエラーが発生しました: {pdf_e}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"反映に失敗しました: {res.get('message')}")

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
    if 5 in _tab_map:
        with _tab_map[5]:
            _tab5_body()
