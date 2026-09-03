"""「期間ストップ」モード（申請・承認・業務転記・チェック・印刷の5タブ）。
顧客検索は他モードと同じ。商品や契約内容の入力は無く、ストップ日（複数ある場合もあるため
記述式で自由入力）・次回訪問日・理由・連絡担当者様・特記事項をまとめて1件分入力する、
単発ルート変更に近いシンプルな構成。"""
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


# ==========================================
# 「期間ストップ」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
PS_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=377209026#gid=377209026"
PS_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=377209026"
# TAB3・TAB4用（転記〜チェック）
PS_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1919780984#gid=1919780984"
PS_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=1919780984"

# 期間ストップ：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G ストップ日, H 次回訪問日, I 理由, J 連絡担当者様, K 特記事項,
# L サイン(ステータス/承認者名), M 日時(承認日時), N コメント(承認コメント/差戻し理由),
# O 処理日, P 処理者, Q チェック日, R チェック者, S 印刷済
PS_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "stop_dates": 6, "next_visit_date": 7,
    "reason": 8, "contact_person": 9, "comment": 10,
    "status_sign": 11, "approval_time": 12, "approval_comment": 13,
    "process_time": 14, "process_user": 15,
    "check_time": 16, "check_user": 17,
    "print_time": 18,
}

# 「期間ストップ」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
PS_PRINT_SHEET_GID = "1073593000"
PS_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={PS_PRINT_SHEET_GID}#gid={PS_PRINT_SHEET_GID}"
# 1ページに4件まで配置。各件の起点行（A列、店名/顧客名/責任者/処理者の行）：1件目=4, 2件目=13, 3件目=22, 4件目=31
# （実テンプレートをクリックして確認：ブロックの高さは9行で均一）
PS_PRINT_BASE_ROWS = [4, 13, 22, 31]


def render_period_stop_tabs():
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

    st.header("🛑 期間ストップ申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "ps_form_clear_key" not in st.session_state:
        st.session_state["ps_form_clear_key"] = 0

    rclear = f"_{st.session_state['ps_form_clear_key']}"

    for _key, _default in [
        (f"ps_ccode{rclear}", ""), (f"ps_cname{rclear}", ""),
        (f"ps_scode{rclear}", ""), (f"ps_sname{rclear}", ""),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    if "ps_searched_ccode" not in st.session_state:
        st.session_state["ps_searched_ccode"] = ""

    def _tab6_body():
        st.subheader("🔍 過去の申請検索")
        st.caption("承認・処理が完了した過去の申請データを検索できます。")

        _col6 = PS_COL

        col_f1, col_f2, col_f3 = st.columns(3)
        f_cust_code = col_f1.text_input("顧客コード", key="p_tab_search_cust_code")
        f_applicant = col_f2.text_input("担当者名", key="p_tab_search_applicant")
        f_date_type = col_f3.selectbox("期間の基準日", ["申請日", "処理日"], key="p_tab_search_date_type")

        col_d1, col_d2 = st.columns(2)
        f_date_from = col_d1.date_input("開始日", value=None, key="p_tab_search_date_from")
        f_date_to = col_d2.date_input("終了日", value=None, key="p_tab_search_date_to")

        if st.button("🔍 検索する", key="p_tab_search_btn"):
            try:
                st.cache_data.clear()
                df_search = pd.read_csv(PS_DEST_SHEET_CSV, dtype=str)
            except Exception as e:
                st.error(f"データ取得エラー: {e}")
                df_search = pd.DataFrame()

            if df_search.empty:
                st.info("対象データがありません。")
            else:
                mask = pd.Series(True, index=df_search.index)
                idx_cust_code = _col6.get("cust_code")
                idx_applicant = _col6.get("applicant")
                idx_timestamp = _col6.get("timestamp")
                idx_process_time = _col6.get("process_time")
                idx_cust_name = _col6.get("cust_name")
                idx_store_name = _col6.get("store_name")

                if f_cust_code and idx_cust_code is not None and len(df_search.columns) > idx_cust_code:
                    mask &= df_search.iloc[:, idx_cust_code].fillna("").astype(str).str.strip() == str(f_cust_code).strip()

                if f_applicant and idx_applicant is not None and len(df_search.columns) > idx_applicant:
                    mask &= df_search.iloc[:, idx_applicant].fillna("").astype(str).str.contains(str(f_applicant).strip(), na=False)

                date_col_idx = idx_timestamp if f_date_type == "申請日" else idx_process_time
                if (f_date_from or f_date_to) and date_col_idx is not None and len(df_search.columns) > date_col_idx:
                    parsed_dates = pd.to_datetime(df_search.iloc[:, date_col_idx], errors="coerce")
                    if f_date_from:
                        mask &= parsed_dates >= pd.Timestamp(f_date_from)
                    if f_date_to:
                        mask &= parsed_dates <= (pd.Timestamp(f_date_to) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))

                result_df = df_search[mask]

                if result_df.empty:
                    st.info("条件に一致するデータは見つかりませんでした。")
                else:
                    st.success(f"📋 検索結果: **{len(result_df)} 件**")
                    for idx, row in result_df.iterrows():
                        def _val(col_idx):
                            if col_idx is None or len(row) <= col_idx or pd.isna(row.iloc[col_idx]):
                                return ""
                            return str(row.iloc[col_idx])

                        cust_code_v = _val(idx_cust_code)
                        cust_name_v = _val(idx_cust_name)
                        store_name_v = _val(idx_store_name)
                        applicant_v = _val(idx_applicant)
                        timestamp_v = _val(idx_timestamp)
                        process_time_v = _val(idx_process_time)

                        expander_label = f"📌 【{store_name_v or '未設定'}】 {cust_name_v}（{cust_code_v}） | 申請日: {timestamp_v}"
                        with st.expander(expander_label):
                            st.write(f"**担当者名：** {applicant_v}")
                            st.write(f"**処理日時：** {process_time_v}")
                            st.dataframe(row.to_frame().T, use_container_width=True, hide_index=True)

    _p_tab_all_labels = [
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
        "🔍 過去の申請検索",
    ]
    _p_tab_visible_nums = [_n for _n in range(1, 7) if tab_visible(_n)]
    if not _p_tab_visible_nums:
        st.info(RESTRICTED_TAB_MSG)
        _tab_map = {}
    else:
        _p_tab_objs = st.tabs([_p_tab_all_labels[_n - 1] for _n in _p_tab_visible_nums])
        _tab_map = dict(zip(_p_tab_visible_nums, _p_tab_objs))

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    def _tab1_body():
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["ps_searched_ccode"],
                key=f"ps_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"ps_search_btn{rclear}")

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
                            st.session_state["ps_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"ps_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"ps_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"ps_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"ps_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""

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
            customer_code = row1_col1.text_input("顧客コード", key=f"ps_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"ps_cname{rclear}")
            store_name = row1_col3.text_input("加盟店名", key=f"ps_sname{rclear}")

            row1b_col1, row1b_col2 = st.columns(2)
            store_code = row1b_col1.text_input("加盟店コード", key=f"ps_scode{rclear}")
            applicant = row1b_col2.text_input("担当者", value=st.session_state["user_name"], key=f"ps_app{rclear}")

            st.write("---")

            with st.form("ps_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                ps_stop_dates = st.text_area("ストップ日（複数ある場合はまとめて入力してください）", key=f"ps_stop_dates{rclear}")
                ps_next_visit_val = st.date_input("次回訪問日", value=None, key=f"ps_next_visit{rclear}")
                ps_next_visit = ps_next_visit_val.strftime("%Y/%m/%d") if ps_next_visit_val else ""
                ps_reason = st.text_input("理由", key=f"ps_reason{rclear}")
                ps_contact = st.text_input("連絡担当者様", key=f"ps_contact{rclear}")
                ps_comment = st.text_area("特記事項", key=f"ps_comment{rclear}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip():
                        st.error("⚠️ 「顧客コード」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [
                            now_str, applicant, customer_code, customer_name, store_name, store_code,
                            ps_stop_dates, ps_next_visit, ps_reason, ps_contact, ps_comment,
                            "申請中", "", ""
                        ]

                        payload = {
                            "action": "SUBMIT_PERIOD_STOP_CHANGE",
                            "target_sheet_url": PS_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["ps_searched_ccode"] = ""
                            st.session_state["ps_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(PS_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > PS_COL["status_sign"]:
                rejected_df = df[df.iloc[:, PS_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = PS_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            with st.form(key=f"ps_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"ps_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"ps_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"ps_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"ps_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"ps_re_app_{row_id}")

                                edit_stop_dates = st.text_area("ストップ日", value=_v("stop_dates"), key=f"ps_re_stop_dates_{row_id}")
                                edit_next_visit = st.text_input("次回訪問日", value=_v("next_visit_date"), key=f"ps_re_next_visit_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"ps_re_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"ps_re_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"ps_re_comment_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip():
                                        st.error("⚠️ 「顧客コード」は必須項目です。")
                                    else:
                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code,
                                            edit_stop_dates, edit_next_visit, edit_reason, edit_contact, edit_comment,
                                            "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_PERIOD_STOP_CHANGE",
                                            "target_sheet_url": PS_TARGET_SHEET_URL,
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
            df = pd.read_csv(PS_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > PS_COL["status_sign"]:
                pending_df = df[df.iloc[:, PS_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = PS_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            with st.form(key=f"ps_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"ps_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"ps_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"ps_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"ps_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"ps_m_app_{row_id}")

                                edit_stop_dates = st.text_area("ストップ日", value=_v("stop_dates"), key=f"ps_m_stop_dates_{row_id}")
                                edit_next_visit = st.text_input("次回訪問日", value=_v("next_visit_date"), key=f"ps_m_next_visit_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"ps_m_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"ps_m_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"ps_m_comment_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"ps_mgr_com_{row_id}")

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
                                        edit_stop_dates, edit_next_visit, edit_reason, edit_contact, edit_comment
                                    ]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_PERIOD_STOP_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_PERIOD_STOP_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_PERIOD_STOP_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": PS_TARGET_SHEET_URL,
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
            df = pd.read_csv(PS_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= PS_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, PS_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, PS_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = PS_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"ps_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"ps_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"ps_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"ps_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"ps_v_app_{row_id}")

                            o3_c1, o3_c2 = st.columns(2)
                            o3_c1.text_area("ストップ日", value=_v("stop_dates"), disabled=True, key=f"ps_v_stop_dates_{row_id}")
                            o3_c2.text_input("次回訪問日", value=_v("next_visit_date"), disabled=True, key=f"ps_v_next_visit_{row_id}")

                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            if reason_val.strip() or contact_val.strip() or comment_val.strip():
                                st.write("---")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"ps_v_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"ps_v_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"ps_v_comment_{row_id}")

                            st.write("---")
                            with st.form(key=f"ps_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"ps_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(PS_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_PERIOD_STOP_TO_OPERATOR",
                                        "target_sheet_url": PS_TARGET_SHEET_URL,
                                        "dest_sheet_url": PS_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": PS_COL["status_sign"] + 1,
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
                                            for i in range(PS_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_PERIOD_STOP_CHANGE",
                                            "target_sheet_url": PS_TARGET_SHEET_URL,
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
            df_dest = pd.read_csv(PS_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="ps_chk_show_checked")

                if not show_checked and len(df_dest.columns) > PS_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, PS_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = PS_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"ps_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"ps_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"ps_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"ps_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"ps_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"ps_chk_app_{row_id}")

                            c6, c7 = st.columns(2)
                            c6.text_area("ストップ日", value=_v("stop_dates"), disabled=True, key=f"ps_chk_stop_dates_{row_id}")
                            c7.text_input("次回訪問日", value=_v("next_visit_date"), disabled=True, key=f"ps_chk_next_visit_{row_id}")

                            c8, c9 = st.columns(2)
                            c8.text_input("処理者", value=op_user_val, disabled=True, key=f"ps_chk_op_{row_id}")
                            c9.text_input("承認者", value=mgr_name_val, disabled=True, key=f"ps_chk_mgr_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            if reason_val.strip() or contact_val.strip() or comment_val.strip():
                                st.write("---")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"ps_chk_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"ps_chk_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"ps_chk_comment_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"ps_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"ps_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < PS_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[PS_COL["check_time"]] = check_time
                                clean_base_row[PS_COL["check_user"]] = checker_name
                                # ※ print_time列（印刷済）はここでは触らない。既存の値を保持する。

                                payload = {
                                    "action": "UPDATE_PERIOD_STOP_CHECK",
                                    "target_sheet_url": PS_DEST_SHEET_URL,
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
    # TAB 5: 加盟店別 印刷
    # ==========================================
    if 4 in _tab_map:
        with _tab_map[4]:
            _tab4_body()
    def _tab5_body():
        st.subheader("🖨️ 加盟店別 印刷")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(PS_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > PS_COL["check_time"]:
                    checked_mask = df_print.iloc[:, PS_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > PS_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, PS_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = PS_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="ps_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(PS_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_ps_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = PS_COL[col_key]
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
                                "cust_code": _f("cust_code"), "applicant": _f("applicant"),
                                "stop_dates": _f("stop_dates"), "next_visit_date": _f("next_visit_date"),
                                "reason": _f("reason") or "特になし",
                                "comment": _f("comment") or "特記事項なし",
                                "contact_disp": contact_disp,
                            }

                        def ps_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            A/B/D/E(+0)=加盟店コード/顧客名(結合B:C)/責任者確認/処理者,
                            A(+2、A:B結合)=ストップ日, C(+2、C:D結合)=次回訪問日, E(+2)=シャトルコード,
                            A(+4、A:D結合)=理由, E(+4)=提出者,
                            A(+6、A:D結合)=特記事項, E(+6)=連絡担当者様"""
                            if not rec:
                                rec = {k: "" for k in [
                                    "store_code", "cust_name", "manager", "operator",
                                    "cust_code", "applicant", "stop_dates", "next_visit_date",
                                    "reason", "comment", "contact_disp",
                                ]}
                            return [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 2, "value": rec["cust_name"]},
                                {"offset": 0, "col": 4, "value": rec["manager"]},
                                {"offset": 0, "col": 5, "value": rec["operator"]},
                                {"offset": 2, "col": 1, "value": rec["stop_dates"]},
                                {"offset": 2, "col": 3, "value": rec["next_visit_date"]},
                                {"offset": 2, "col": 5, "value": rec["cust_code"]},
                                {"offset": 4, "col": 1, "value": rec["reason"]},
                                {"offset": 4, "col": 5, "value": rec["applicant"]},
                                {"offset": 6, "col": 1, "value": rec["comment"]},
                                {"offset": 6, "col": 5, "value": rec["contact_disp"]},
                            ]

                        chunk_size = len(PS_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(PS_PRINT_BASE_ROWS):
                                rec = build_ps_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": ps_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    st.caption(f"ストップ日: {rec['stop_dates']} ｜ 次回訪問日: {rec['next_visit_date']} ｜ シャトルコード: {rec['cust_code']}")
                                    st.caption(f"理由: {rec['reason']} ｜ 提出者: {rec['applicant']}")
                                    st.caption(f"特記事項: {rec['comment']} ｜ 連絡担当者様: {rec['contact_disp']}")

                            if st.button("📥 反映してPDFを作成する", key=f"ps_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": PS_PRINT_SHEET_URL,
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
                                        "target_sheet_url": PS_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": PS_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = PS_PRINT_BASE_ROWS[len(chunk) - 1] + 6 if len(chunk) > 0 else 10
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, gid=PS_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_period_stop_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"ps_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({PS_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
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
    if 6 in _tab_map:
        with _tab_map[6]:
            _tab6_body()
