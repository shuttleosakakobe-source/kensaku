import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timezone, timedelta
import time

GAS_URL = "https://script.google.com/macros/s/AKfycbywXIMKfujyW1-mjwGGMi7q9WpXha5HpXWmjRxoPd34d4bgPJ-DvVLzMUGa6xwBntXh/exec"

TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0"
DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv"
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"

# 日本時間（JST = UTC+9）のタイムゾーン定義
JST = timezone(timedelta(hours=+9), 'JST')


def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def maintenance_admin_screen():
    # 💡 【CSS修正】disabled入力欄の文字色調整 ＆ フォーム内のダミーボタンを完全に非表示にする
    st.markdown("""
        <style>
        input:disabled, textarea:disabled {
            -webkit-text-fill-color: #31333F !important;
            color: #31333F !important;
            opacity: 1 !important;
        }
        /* フォーム内にある「無効化されたボタン」を完全に消す */
        div[data-testid="stForm"] button[disabled] {
            display: none !important;
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("📦 メンテナンス申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "担当者"

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

    tab1, tab2, tab3, tab4 = st.tabs([
        "📝 スタッフ申請・差戻し対応", 
        "🔍 管理職チェック", 
        "🚚 業務担当：シート転記", 
        "✅ メンテナンスチェック"
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with tab1:
        st.subheader("📝 新規申請 / 差戻しデータ修正")
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

                st.write("**📋 申請基本情報**")
                
                row1_col1, row1_col2, row1_col3 = st.columns(3)
                customer_code = row1_col1.text_input("顧客コード", key=f"ccode{clear_suffix}")
                customer_name = row1_col2.text_input("顧客名（得意先名）", key=f"cname{clear_suffix}")
                store_code = row1_col3.text_input("加盟店コード（店舗コード）", key=f"scode{clear_suffix}")

                row2_col1, row2_col2, row2_col3 = st.columns(3)
                store_name = row2_col1.text_input("加盟店名（店舗名）", key=f"sname{clear_suffix}")
                route_code = row2_col2.text_input("ルートコード", value="", key=f"rcode{clear_suffix}")
                delivery_date_val = row2_col3.date_input("納品日", value=None, key=f"ddate{clear_suffix}")
                delivery_date = delivery_date_val.strftime("%Y/%m/%d") if delivery_date_val else ""

                row3_col1, row3_col2, row3_col3 = st.columns(3)
                delivery_person = row3_col1.text_input("納品者", value=st.session_state["user_name"], key=f"dperson{clear_suffix}")
                applicant = row3_col2.text_input("申請者名", value=st.session_state["user_name"], key=f"app{clear_suffix}")

                st.write("---")
                st.write("**📦 申請商品（最大5件）**")
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

                                st.write("**📋 申請基本情報修正**")
                                
                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名（得意先名）", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", key=f"re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード（店舗コード）", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", key=f"re_scode_{row_id}")

                                r2_1, r2_2, r2_3 = st.columns(3)
                                edit_store_name = r2_1.text_input("加盟店名（店舗名）", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", key=f"re_sname_{row_id}")
                                edit_route_code = r2_2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", key=f"re_rcode_{row_id}")
                                edit_deliv_date = r2_3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", key=f"re_ddate_{row_id}")

                                r3_1, r3_2, r3_3 = st.columns(3)
                                edit_deliv_person = r3_1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", key=f"re_dperson_{row_id}")
                                edit_applicant = r3_2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", key=f"re_app_{row_id}")

                                st.write("---")
                                st.write("**📦 申請商品修正**")
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
        st.subheader("🔍 管理職：申請承認・編集")
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

                                st.write("**📋 申請基本情報（修正可能）**")
                                
                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名（得意先名）", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", key=f"m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード（店舗コード）", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", key=f"m_scode_{row_id}")

                                m2_1, m2_2, m2_3 = st.columns(3)
                                edit_sname = m2_1.text_input("加盟店名（店舗名）", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", key=f"m_sname_{row_id}")
                                edit_rcode = m2_2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", key=f"m_rcode_{row_id}")
                                edit_ddate = m2_3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", key=f"m_ddate_{row_id}")

                                m3_1, m3_2, m3_3 = st.columns(3)
                                edit_dperson = m3_1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", key=f"m_dperson_{row_id}")
                                edit_app = m3_2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", key=f"m_app_{row_id}")

                                st.write("---")
                                st.write("**📦 申請商品（修正可能）**")
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
        st.subheader("🚚 業務担当：承認済みデータの転記・処理")
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
                            o1_c2.text_input("顧客名（得意先名）", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", disabled=True, key=f"v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード（店舗コード）", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", disabled=True, key=f"v_scode_{row_id}")

                            o2_c1, o2_c2, o2_c3 = st.columns(3)
                            o2_c1.text_input("加盟店名（店舗名）", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", disabled=True, key=f"v_sname_{row_id}")
                            o2_c2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", disabled=True, key=f"v_rcode_{row_id}")
                            o2_c3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", disabled=True, key=f"v_ddate_{row_id}")

                            o3_c1, o3_c2, o3_c3 = st.columns(3)
                            o3_c1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", disabled=True, key=f"v_dperson_{row_id}")
                            o3_c2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", disabled=True, key=f"v_app_{row_id}")
                            o3_c3.text_input("承認者", value=mgr_name, disabled=True, key=f"v_mgr_{row_id}")

                            st.write("---")
                            st.write("**📦 申請商品**")
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
    # TAB 4: メンテナンスチェック画面
    # ==========================================
    with tab4:
        st.subheader("✅ メンテナンスチェック画面")
        st.caption("業務担当（TAB 3）で転記されたデータ（元データ）を一覧で確認し、チェックや追加の差戻し等を行うことができます。")

        try:
            st.cache_data.clear()
            df_dest = pd.read_csv(DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
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
                    
                    # 💡 承認者・処理者情報の取得 (列インデックスは保存形式に準拠)
                    mgr_name_val = str(row.iloc[30]) if len(row) > 30 and pd.notna(row.iloc[30]) else "不明"
                    op_user_val = str(row.iloc[32]) if len(row) > 32 and pd.notna(row.iloc[32]) else "不明"

                    expander_label = f"📌 【加盟店: {store_name or '未設定'}】 顧客名: {cust_name}（{cust_code}） | 納品日: {deliv_date}"

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

                            # 💡 TAB4でも承認者・処理者を表示
                            c7, c8, c9 = st.columns(3)
                            c7.text_input("承認者", value=mgr_name_val, disabled=True, key=f"chk_mgr_{row_id}")
                            c8.text_input("処理者（業務担当）", value=op_user_val, disabled=True, key=f"chk_op_{row_id}")
                            c9.text_input("", value="", disabled=True, label_visibility="hidden", key=f"chk_dummy_{row_id}")

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
                                st.toast(f"行 {row_id} のメンテナンスチェックを完了しました！", icon="✅")
                                time.sleep(1)
                                st.rerun()

                            elif btn_checked_reject:
                                if not reject_reason.strip():
                                    st.error("⚠️ 差戻しを行う場合は「差戻し理由」を入力してください。")
                                else:
                                    st.toast(f"【{reject_target}】へ差戻しを行いました（理由: {reject_reason}）", icon="↩️")
                                    time.sleep(1.5)
                                    st.rerun()

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
