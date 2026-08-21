import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime
import time

GAS_URL = "https://script.google.com/macros/s/AKfycbySnxfJOaQo7g7bFeHbnfsFBoJSxr3to0vg8GAavB-d49FuCXfxb8BeT5groozOPQks/exec"  # ⚠️ ご自身のGASデプロイURLに置き換えてください

TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0"

# 顧客マスタデータ用URL（指定スプレッドシートのCSV形式）
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"


def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def maintenance_admin_screen():
    st.header("📦 メンテナンス申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "担当者"

    # マスタ検索結果の保持用セッション状態（初期化）
    if "master_cname" not in st.session_state:
        st.session_state["master_cname"] = ""
    if "master_sname" not in st.session_state:
        st.session_state["master_sname"] = ""
    if "master_scode" not in st.session_state:
        st.session_state["master_scode"] = ""
    if "searched_ccode" not in st.session_state:
        st.session_state["searched_ccode"] = ""

    tab1, tab2, tab3 = st.tabs(["📝 スタッフ申請・差戻し対応", "🔍 管理職チェック", "🚚 業務担当：シート転記"])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with tab1:
        st.subheader("📝 新規申請 / 差戻しデータ修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            # --- 顧客コード検索エリア ---
            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input("🔍 顧客コード入力", value=st.session_state["searched_ccode"], key="cust_code_search")
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary")

            if btn_search:
                if cust_code_input:
                    try:
                        df_master = pd.read_csv(
                            CUSTOMER_MASTER_CSV,
                            dtype=str,
                            storage_options={"User-Agent": "Mozilla/5.0"}
                        )
                        # B列（index 1）: 顧客コード で照合
                        matched = df_master[df_master.iloc[:, 1].astype(str).str.strip() == str(cust_code_input).strip()]

                        if not matched.empty:
                            last_row = matched.iloc[-1]
                            st.session_state["searched_ccode"] = str(cust_code_input)
                            st.session_state["master_sname"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""  # A列: 加盟店名
                            st.session_state["master_cname"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""  # C列: 顧客名
                            st.session_state["master_scode"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""  # E列: 加盟店コード
                            st.toast("顧客情報を取得しました！", icon="✅")
                            time.sleep(0.5)
                            st.rerun()  # 画面を再描画してフォームに反映
                        else:
                            st.warning("該当する顧客データが見つかりませんでした。")
                    except Exception as e:
                        st.error(f"マスタ参照エラー: {e}")
                else:
                    st.warning("顧客コードを入力してください。")

            st.write("---")

            # --- 申請フォーム ---
            with st.form("submit_form"):
                st.write("**📋 申請基本情報**")
                
                # 1行目： 顧客コード | 顧客名（得意先名） | 加盟店コード（店舗コード）
                row1_col1, row1_col2, row1_col3 = st.columns(3)
                customer_code = row1_col1.text_input("顧客コード", value=st.session_state["searched_ccode"])
                customer_name = row1_col2.text_input("顧客名（得意先名）", value=st.session_state["master_cname"])
                store_code = row1_col3.text_input("加盟店コード（店舗コード）", value=st.session_state["master_scode"])

                # 2行目： 加盟店名（店舗名） | ルートコード | 納品日
                row2_col1, row2_col2, row2_col3 = st.columns(3)
                store_name = row2_col1.text_input("加盟店名（店舗名）", value=st.session_state["master_sname"])
                route_code = row2_col2.text_input("ルートコード", value="")
                delivery_date = row2_col3.date_input("納品日").strftime("%Y/%m/%d")

                # 3行目： 納品者 | 申請者名
                row3_col1, row3_col2, row3_col3 = st.columns(3)
                delivery_person = row3_col1.text_input("納品者", value=st.session_state["user_name"])
                applicant = row3_col2.text_input("申請者名", value=st.session_state["user_name"])

                st.write("---")
                st.write("**📦 申請商品（最大5件）**")
                items_flat = []
                for i in range(5):
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                    p_code = c1.text_input(f"商品コード {i+1}", key=f"p_{i}")
                    qty = c2.number_input(f"数量 {i+1}", min_value=0, value=0, key=f"q_{i}")
                    price = c3.number_input(f"単価 {i+1}", min_value=0, value=0, key=f"pr_{i}")
                    print_flg = c4.selectbox(f"伝票出力 {i+1}", ["有", "無"], key=f"flg_{i}")
                    
                    items_flat.extend([p_code, str(qty), str(price), print_flg])

                st.write("---")
                app_comment = st.text_area("申請コメント", placeholder="連絡事項や補足説明があれば入力してください")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    # 💡 A列（タイムスタンプ）を先頭(0番目)に配置して全33列のデータを正確に生成
                    now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                    full_row = [
                        now_str,           # A列: タイムスタンプ
                        applicant,         # B列: 申請者名
                        customer_code,     # C列: 顧客コード
                        customer_name,     # D列: 顧客名
                        store_name,        # E列: 加盟店名
                        store_code,        # F列: 加盟店コード
                        delivery_date,     # G列: 納品日
                        route_code,        # H列: ルートコード
                        delivery_person    # I列: 納品者
                    ] + items_flat + [app_comment, "申請中", "", ""]  # 商品20列 + コメント + ステータス等

                    payload = {
                        "status": "SUBMIT_MAINTENANCE",
                        "target_sheet_url": TARGET_SHEET_URL,
                        "full_row": full_row
                    }
                    res = post_to_gas(payload)
                    if res.get("status") == "success":
                        st.toast("新規申請を送信しました！", icon="🎉")
                        # 入力状態をクリア
                        st.session_state["searched_ccode"] = ""
                        st.session_state["master_cname"] = ""
                        st.session_state["master_sname"] = ""
                        st.session_state["master_scode"] = ""
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
                                st.write("**📋 申請基本情報修正**")
                                
                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード（入力用）", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"re_ccode_{row_id}")
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
                                    q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else "0"
                                    pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else "0"
                                    flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else "有"

                                    r1, r2, r3, r4 = st.columns([3, 2, 2, 2])
                                    p_in = r1.text_input(f"商品コード {i+1}", value=p_val, key=f"re_p_{row_id}_{i}")
                                    q_in = r2.text_input(f"数量 {i+1}", value=q_val, key=f"re_q_{row_id}_{i}")
                                    pr_in = r3.text_input(f"単価 {i+1}", value=pr_val, key=f"re_pr_{row_id}_{i}")
                                    flg_idx = 0 if flg_val in ["有", "要", ""] else 1
                                    flg_in = r4.selectbox(f"伝票出力 {i+1}", ["有", "無"], index=flg_idx, key=f"re_flg_{row_id}_{i}")

                                    edit_items.extend([p_in, q_in, pr_in, flg_in])

                                st.write("---")
                                edit_app_comment = st.text_area("申請コメント", value=str(row.iloc[29]) if len(row) > 29 and pd.notna(row.iloc[29]) else "", key=f"re_com_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    updated_row = [
                                        str(row.iloc[0]), edit_applicant, edit_cust_code, edit_cust_name,
                                        edit_store_name, edit_store_code, edit_deliv_date, edit_route_code, edit_deliv_person
                                    ] + edit_items + [edit_app_comment, "申請中", "", ""]

                                    payload = {
                                        "status": "RESUBMIT_MAINTENANCE",
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
                                st.write("**📋 申請基本情報（修正可能）**")
                                
                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード（入力用）", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"m_ccode_{row_id}")
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
                                    q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else "0"
                                    pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else "0"
                                    flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else "有"

                                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                                    p_in = c1.text_input(f"商品コード {i+1}", value=p_val, key=f"m_p_{row_id}_{i}")
                                    q_in = c2.text_input(f"数量 {i+1}", value=q_val, key=f"m_q_{row_id}_{i}")
                                    pr_in = c3.text_input(f"単価 {i+1}", value=pr_val, key=f"m_pr_{row_id}_{i}")
                                    flg_idx = 0 if flg_val in ["有", "要", ""] else 1
                                    flg_in = c4.selectbox(f"伝票出力 {i+1}", ["有", "無"], index=flg_idx, key=f"m_flg_{row_id}_{i}")

                                    edit_items.extend([p_in, q_in, pr_in, flg_in])

                                st.write("---")
                                edit_app_comment = st.text_area("申請者コメント", value=str(row.iloc[29]) if len(row) > 29 and pd.notna(row.iloc[29]) else "", key=f"m_app_com_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"mgr_com_{row_id}")
                                
                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認（変更内容を反映）", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    updated_row = [
                                        str(row.iloc[0]), edit_app, edit_ccode, edit_cname,
                                        edit_sname, edit_scode, edit_ddate, edit_rcode, edit_dperson
                                    ] + edit_items + [edit_app_comment]

                                    status_type = ""
                                    if btn_approve:
                                        status_type = "APPROVE_MAINTENANCE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        status_type = "REJECT_MAINTENANCE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        status_type = "DELETE_MAINTENANCE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "status": status_type,
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

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2
                        timestamp = str(row.iloc[0]) if pd.notna(row.iloc[0]) else ""
                        cust_code = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ""
                        cust_name = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ""
                        mgr_name = str(row.iloc[30]) if pd.notna(row.iloc[30]) else ""

                        expander_label = f"🟢【承認済】{cust_name}（{cust_code}） | 承認者: {mgr_name} | 申請日: {timestamp}"

                        with st.expander(expander_label):
                            st.write("**📋 申請内容**")
                            
                            o1_1, o1_2, o1_3 = st.columns(3)
                            o1_1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", disabled=True, key=f"op_ccode_{row_id}")
                            o1_2.text_input("顧客名（得意先名）", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", disabled=True, key=f"op_cname_{row_id}")
                            o1_3.text_input("加盟店コード", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", disabled=True, key=f"op_scode_{row_id}")

                            o2_1, o2_2, o2_3 = st.columns(3)
                            o2_1.text_input("加盟店名（店舗名）", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", disabled=True, key=f"op_sname_{row_id}")
                            o2_2.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "", disabled=True, key=f"op_rcode_{row_id}")
                            o2_3.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "", disabled=True, key=f"op_ddate_{row_id}")

                            o3_1, o3_2, o3_3 = st.columns(3)
                            o3_1.text_input("納品者", value=str(row.iloc[8]) if pd.notna(row.iloc[8]) else "", disabled=True, key=f"op_dperson_{row_id}")
                            o3_2.text_input("申請者名", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "", disabled=True, key=f"op_app_{row_id}")

                            st.write("---")
                            st.write("**📦 申請商品**")
                            for i in range(5):
                                base_idx = 9 + (i * 4)
                                p_val = str(row.iloc[base_idx]) if base_idx < len(row) and pd.notna(row.iloc[base_idx]) else ""
                                q_val = str(row.iloc[base_idx+1]) if base_idx+1 < len(row) and pd.notna(row.iloc[base_idx+1]) else "0"
                                pr_val = str(row.iloc[base_idx+2]) if base_idx+2 < len(row) and pd.notna(row.iloc[base_idx+2]) else "0"
                                flg_val = str(row.iloc[base_idx+3]) if base_idx+3 < len(row) and pd.notna(row.iloc[base_idx+3]) else "有"

                                c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                                c1.text_input(f"商品コード {i+1}", value=p_val, disabled=True, key=f"op_p_{row_id}_{i}")
                                c2.text_input(f"数量 {i+1}", value=q_val, disabled=True, key=f"op_q_{row_id}_{i}")
                                c3.text_input(f"単価 {i+1}", value=pr_val, disabled=True, key=f"op_pr_{row_id}_{i}")
                                c4.text_input(f"伝票出力 {i+1}", value=flg_val, disabled=True, key=f"op_flg_{row_id}_{i}")

                            st.text_area("申請者コメント", value=str(row.iloc[29]) if len(row) > 29 and pd.notna(row.iloc[29]) else "", disabled=True, key=f"op_app_com_{row_id}")

                            with st.form(key=f"transfer_form_{row_id}"):
                                op_memo = st.text_input("業務メモ / 伝票番号など（任意）", key=f"op_memo_{row_id}")
                                btn_transfer = st.form_submit_button("📋 別シート（業務管理用）へ出力・転記", type="primary", use_container_width=True)

                                if btn_transfer:
                                    action_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                                    op_user = st.session_state["user_name"]

                                    base_row = ["" if pd.isna(x) else str(x) for x in row.values.tolist()]
                                    transfer_row = base_row + [action_time, op_user, op_memo]

                                    payload = {
                                        "status": "TRANSFER_TO_OPERATOR",
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

        except Exception as e:
            st.error(f"データ取得エラー: {e}")
