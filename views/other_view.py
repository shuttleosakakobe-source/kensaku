"""「その他のメンテナンス」モード（申請・承認・業務転記・チェック・印刷の5タブ）。
顧客検索は他モードと同じ。商品や契約内容の入力は無く、種別（住所・電話番号変更／コメント／
未収金・過入金変更／その他〈記述式〉のプルダウン）・内容・連絡担当者様・特記事項をまとめて
1件分入力する、期間ストップに近いシンプルな構成。"""
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
# 「その他のメンテナンス」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
OT_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=1623118092#gid=1623118092"
OT_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=1623118092"
# TAB3・TAB4用（転記〜チェック）
OT_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1292519782#gid=1292519782"
OT_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=1292519782"

# その他のメンテナンス：プルダウンの選択肢（最後の「その他」を選んだ場合のみ記述式で内容を入力）
OT_CATEGORY_OPTIONS = ["住所・電話番号変更", "コメント", "未収金・過入金変更", "その他"]

# その他のメンテナンス：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G 種別, H その他の内容(種別が「その他」の場合のみ), I 内容, J 連絡担当者様, K 特記事項,
# L サイン(ステータス/承認者名), M 日時(承認日時), N コメント(承認コメント/差戻し理由),
# O 処理日, P 処理者, Q チェック日, R チェック者, S 印刷済
OT_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "category": 6, "category_detail": 7, "content": 8,
    "contact_person": 9, "comment": 10,
    "status_sign": 11, "approval_time": 12, "approval_comment": 13,
    "process_time": 14, "process_user": 15,
    "check_time": 16, "check_user": 17,
    "print_time": 18,
}

# 「その他のメンテナンス」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
OT_PRINT_SHEET_GID = "1519347246"
OT_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={OT_PRINT_SHEET_GID}#gid={OT_PRINT_SHEET_GID}"
# 1ページに5件まで配置。各件の起点行（A列、店名/顧客名/責任者/処理者の行）：
# 1件目=4, 2件目=13, 3件目=22, 4件目=31, 5件目=40（実テンプレートをクリックして確認：ブロックの高さは9行で均一）
OT_PRINT_BASE_ROWS = [4, 13, 22, 31, 40]


def render_other_maintenance_tabs():
    # 💡 【CSS調整】disabled入力の文字が薄くて読みにくいのを解消
    st.markdown("""
        <style>
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

    st.header("📮 その他のメンテナンス申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "ot_form_clear_key" not in st.session_state:
        st.session_state["ot_form_clear_key"] = 0

    rclear = f"_{st.session_state['ot_form_clear_key']}"

    for _key, _default in [
        (f"ot_ccode{rclear}", ""), (f"ot_cname{rclear}", ""),
        (f"ot_scode{rclear}", ""), (f"ot_sname{rclear}", ""),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    if "ot_searched_ccode" not in st.session_state:
        st.session_state["ot_searched_ccode"] = ""

    _o_tab_all_labels = [
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
    ]
    _o_tab_visible_nums = [_n for _n in range(1, 6) if tab_visible(_n)]
    if not _o_tab_visible_nums:
        st.info(RESTRICTED_TAB_MSG)
        _tab_map = {}
    else:
        _o_tab_objs = st.tabs([_o_tab_all_labels[_n - 1] for _n in _o_tab_visible_nums])
        _tab_map = dict(zip(_o_tab_visible_nums, _o_tab_objs))

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    def _tab1_body():
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["ot_searched_ccode"],
                key=f"ot_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"ot_search_btn{rclear}")

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
                            st.session_state["ot_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"ot_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"ot_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"ot_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"ot_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""

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
            customer_code = row1_col1.text_input("顧客コード", key=f"ot_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"ot_cname{rclear}")
            store_name = row1_col3.text_input("加盟店名", key=f"ot_sname{rclear}")

            row1b_col1, row1b_col2 = st.columns(2)
            store_code = row1b_col1.text_input("加盟店コード", key=f"ot_scode{rclear}")
            applicant = row1b_col2.text_input("担当者", value=st.session_state["user_name"], key=f"ot_app{rclear}")

            row2_col1, row2_col2 = st.columns(2)
            ot_category = row2_col1.selectbox("種別", OT_CATEGORY_OPTIONS, key=f"ot_category{rclear}")
            if ot_category == "その他":
                ot_category_detail = row2_col2.text_input("その他の内容（種別が「その他」の場合に入力）", key=f"ot_category_detail{rclear}")
            else:
                ot_category_detail = ""

            st.write("---")

            with st.form("ot_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                ot_content = st.text_area("内容", key=f"ot_content{rclear}")
                ot_contact = st.text_input("連絡担当者様", key=f"ot_contact{rclear}")
                ot_comment = st.text_area("特記事項", key=f"ot_comment{rclear}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip():
                        st.error("⚠️ 「顧客コード」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [
                            now_str, applicant, customer_code, customer_name, store_name, store_code,
                            ot_category, ot_category_detail, ot_content, ot_contact, ot_comment,
                            "申請中", "", ""
                        ]

                        payload = {
                            "action": "SUBMIT_OTHER_MAINTENANCE_CHANGE",
                            "target_sheet_url": OT_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["ot_searched_ccode"] = ""
                            st.session_state["ot_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(OT_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > OT_COL["status_sign"]:
                rejected_df = df[df.iloc[:, OT_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = OT_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            with st.form(key=f"ot_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"ot_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"ot_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"ot_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"ot_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"ot_re_app_{row_id}")

                                cur_category = _v("category")
                                cat_index = OT_CATEGORY_OPTIONS.index(cur_category) if cur_category in OT_CATEGORY_OPTIONS else len(OT_CATEGORY_OPTIONS) - 1
                                edit_category = st.selectbox("種別", OT_CATEGORY_OPTIONS, index=cat_index, key=f"ot_re_category_{row_id}")
                                edit_category_detail = st.text_input("その他の内容（種別が「その他」の場合のみ入力）", value=_v("category_detail"), key=f"ot_re_category_detail_{row_id}")
                                edit_content = st.text_area("内容", value=_v("content"), key=f"ot_re_content_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"ot_re_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"ot_re_comment_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip():
                                        st.error("⚠️ 「顧客コード」は必須項目です。")
                                    else:
                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code,
                                            edit_category, edit_category_detail, edit_content, edit_contact, edit_comment,
                                            "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_OTHER_MAINTENANCE_CHANGE",
                                            "target_sheet_url": OT_TARGET_SHEET_URL,
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
            df = pd.read_csv(OT_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > OT_COL["status_sign"]:
                pending_df = df[df.iloc[:, OT_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = OT_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            with st.form(key=f"ot_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"ot_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"ot_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"ot_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"ot_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"ot_m_app_{row_id}")

                                cur_category = _v("category")
                                cat_index = OT_CATEGORY_OPTIONS.index(cur_category) if cur_category in OT_CATEGORY_OPTIONS else len(OT_CATEGORY_OPTIONS) - 1
                                edit_category = st.selectbox("種別", OT_CATEGORY_OPTIONS, index=cat_index, key=f"ot_m_category_{row_id}")
                                edit_category_detail = st.text_input("その他の内容（種別が「その他」の場合のみ入力）", value=_v("category_detail"), key=f"ot_m_category_detail_{row_id}")
                                edit_content = st.text_area("内容", value=_v("content"), key=f"ot_m_content_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"ot_m_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"ot_m_comment_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"ot_mgr_com_{row_id}")

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
                                        edit_category, edit_category_detail, edit_content, edit_contact, edit_comment
                                    ]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_OTHER_MAINTENANCE_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_OTHER_MAINTENANCE_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_OTHER_MAINTENANCE_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": OT_TARGET_SHEET_URL,
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
            df = pd.read_csv(OT_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= OT_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, OT_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, OT_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = OT_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"ot_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"ot_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"ot_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"ot_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"ot_v_app_{row_id}")

                            category_val = _v("category")
                            category_detail_val = _v("category_detail")
                            category_disp_val = f"{category_val}（{category_detail_val}）" if category_val == "その他" and category_detail_val.strip() else category_val

                            o3_c1, o3_c2 = st.columns(2)
                            o3_c1.text_input("種別", value=category_disp_val, disabled=True, key=f"ot_v_category_{row_id}")
                            o3_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"ot_v_app2_{row_id}")

                            content_val = _v("content")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            if content_val.strip() or contact_val.strip() or comment_val.strip():
                                st.write("---")
                                if content_val.strip():
                                    st.text_area("内容", value=content_val, disabled=True, key=f"ot_v_content_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"ot_v_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"ot_v_comment_{row_id}")

                            st.write("---")
                            with st.form(key=f"ot_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"ot_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(OT_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_OTHER_MAINTENANCE_TO_OPERATOR",
                                        "target_sheet_url": OT_TARGET_SHEET_URL,
                                        "dest_sheet_url": OT_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": OT_COL["status_sign"] + 1,
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
                                            for i in range(OT_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_OTHER_MAINTENANCE_CHANGE",
                                            "target_sheet_url": OT_TARGET_SHEET_URL,
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
            df_dest = pd.read_csv(OT_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="ot_chk_show_checked")

                if not show_checked and len(df_dest.columns) > OT_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, OT_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = OT_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"ot_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"ot_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"ot_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"ot_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"ot_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"ot_chk_app_{row_id}")

                            category_val = _v("category")
                            category_detail_val = _v("category_detail")
                            category_disp_val = f"{category_val}（{category_detail_val}）" if category_val == "その他" and category_detail_val.strip() else category_val

                            c6, c7 = st.columns(2)
                            c6.text_input("種別", value=category_disp_val, disabled=True, key=f"ot_chk_category_{row_id}")
                            c7.text_input("処理者", value=op_user_val, disabled=True, key=f"ot_chk_op_{row_id}")

                            c8, c9 = st.columns(2)
                            c8.text_input("承認者", value=mgr_name_val, disabled=True, key=f"ot_chk_mgr_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            content_val = _v("content")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            if content_val.strip() or contact_val.strip() or comment_val.strip():
                                st.write("---")
                                if content_val.strip():
                                    st.text_area("内容", value=content_val, disabled=True, key=f"ot_chk_content_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"ot_chk_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"ot_chk_comment_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"ot_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"ot_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < OT_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[OT_COL["check_time"]] = check_time
                                clean_base_row[OT_COL["check_user"]] = checker_name
                                # ※ print_time列（印刷済）はここでは触らない。既存の値を保持する。

                                payload = {
                                    "action": "UPDATE_OTHER_MAINTENANCE_CHECK",
                                    "target_sheet_url": OT_DEST_SHEET_URL,
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
            df_print = pd.read_csv(OT_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > OT_COL["check_time"]:
                    checked_mask = df_print.iloc[:, OT_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > OT_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, OT_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = OT_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="ot_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(OT_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_ot_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = OT_COL[col_key]
                                return str(r_row.iloc[i]) if len(r_row) > i and pd.notna(r_row.iloc[i]) else ""

                            manager = _f("status_sign") or "未確認"
                            operator = _f("process_user") or st.session_state["user_name"]
                            contact = _f("contact_person")
                            contact_disp = f"{contact} 様" if contact.strip() else ""
                            raw_cname = _f("cust_name")
                            cust_name_disp = f"{raw_cname} 様" if raw_cname.strip() else ""

                            category = _f("category")
                            category_detail = _f("category_detail")
                            if category == "その他" and category_detail.strip():
                                category_disp = f"その他（{category_detail}）"
                            else:
                                category_disp = category or "未設定"

                            return {
                                "store_code": _f("store_code"), "cust_name": cust_name_disp,
                                "manager": manager, "operator": operator,
                                "cust_code": _f("cust_code"), "applicant": _f("applicant"),
                                "category_disp": category_disp,
                                "content": _f("content") or "特になし",
                                "comment": _f("comment") or "特記事項なし",
                                "contact_disp": contact_disp,
                            }

                        def ot_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            A/B/D/E(+0)=加盟店コード/顧客名(結合B:C)/責任者確認/処理者,
                            A(+2、A:B結合)=種別, C(+2)=提出者, D(+2)=連絡担当者様, E(+2)=シャトルコード,
                            A(+4、A:E結合)=内容, A(+6、A:E結合)=特記事項"""
                            if not rec:
                                rec = {k: "" for k in [
                                    "store_code", "cust_name", "manager", "operator",
                                    "cust_code", "applicant", "category_disp", "content",
                                    "comment", "contact_disp",
                                ]}
                            return [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 2, "value": rec["cust_name"]},
                                {"offset": 0, "col": 4, "value": rec["manager"]},
                                {"offset": 0, "col": 5, "value": rec["operator"]},
                                {"offset": 2, "col": 1, "value": rec["category_disp"]},
                                {"offset": 2, "col": 3, "value": rec["applicant"]},
                                {"offset": 2, "col": 4, "value": rec["contact_disp"]},
                                {"offset": 2, "col": 5, "value": rec["cust_code"]},
                                {"offset": 4, "col": 1, "value": rec["content"]},
                                {"offset": 6, "col": 1, "value": rec["comment"]},
                            ]

                        chunk_size = len(OT_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(OT_PRINT_BASE_ROWS):
                                rec = build_ot_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": ot_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    st.caption(f"種別: {rec['category_disp']} ｜ 提出者: {rec['applicant']} ｜ 連絡担当者様: {rec['contact_disp']} ｜ シャトルコード: {rec['cust_code']}")
                                    st.caption(f"内容: {rec['content']}")
                                    st.caption(f"特記事項: {rec['comment']}")

                            if st.button("📥 反映してPDFを作成する", key=f"ot_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": OT_PRINT_SHEET_URL,
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
                                        "target_sheet_url": OT_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": OT_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = OT_PRINT_BASE_ROWS[len(chunk) - 1] + 6 if len(chunk) > 0 else 10
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, gid=OT_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_other_maintenance_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"ot_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({OT_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
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
