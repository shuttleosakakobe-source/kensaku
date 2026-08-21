import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime
import time

GAS_URL = "https://script.google.com/macros/s/AKfycbzg61d-nNxC4WXWKLMgqSiEuMjE_5BvUvKvRU0DWzDEPgo71MXuNdC3vCdHdIWNTMnM/exec"

TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0"


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

    # マスタ検索結果およびフォームリセット用のセッション状態設定
    if "master_cname" not in st.session_state:
        st.session_state["master_cname"] = ""
    if "master_sname" not in st.session_state:
        st.session_state["master_sname"] = ""
    if "master_scode" not in st.session_state:
        st.session_state["master_scode"] = ""
    if "searched_ccode" not in st.session_state:
        st.session_state["searched_ccode"] = ""
    if "form_clear_key" not in st.session_state:
        st.session_state["form_clear_key"] = 0

    tab1, tab2, tab3 = st.tabs(["📝 スタッフ申請・差戻し対応", "🔍 管理職チェック", "🚚 業務担当：シート転記"])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with tab1:
        st.subheader("📝 新規申請 / 差戻しデータ修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            # --- 顧客コード検索エリア ---
            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力", 
                value=st.session_state["searched_ccode"], 
                key=f"cust_code_search_{st.session_state['form_clear_key']}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary")

            if btn_search:
                if cust_code_input.strip():
                    with st.spinner("顧客データを検索中..."):
                        payload = {
                            "status": "GET_CUSTOMER_MASTER",
                            "customer_code": cust_code_input.strip()
                        }
                        res = post_to_gas(payload)

                        if res.get("status") == "success":
                            cust_data = res.get("data")
                            if cust_data:
                                st.session_state["searched_ccode"] = cust_code_input.strip()
                                st.session_state["master_sname"] = cust_data.get("sname", "")
                                st.session_state["master_cname"] = cust_data.get("cname", "")
                                st.session_state["master_scode"] = cust_data.get("scode", "")

                                st.toast("顧客情報を取得しました！", icon="✅")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.warning(f"「{cust_code_input}」に該当する顧客データが見つかりませんでした。")
                        else:
                            st.error(f"取得エラー: {res.get('message')}")
                else:
                    st.warning("顧客コードを入力してください。")

            st.write("---")

            # --- 申請フォーム ---
            with st.form("submit_form"):
                st.write("**📋 申請基本情報**")
                
                clear_suffix = f"_{st.session_state['form_clear_key']}"
                
                # 1行目： 顧客コード | 顧客名 | 納品書印字顧客コード
                row1_col1, row1_col2, row1_col3 = st.columns(3)
                customer_code = row1_col1.text_input("顧客コード", value=st.session_state["searched_ccode"], key=f"ccode{clear_suffix}")
                customer_name = row1_col2.text_input("顧客名（得意先名）", value=st.session_state["master_cname"], key=f"cname{clear_suffix}")
                store_code = row1_col3.text_input("納品書印字顧客コード", value=st.session_state["master_scode"], key=f"scode{clear_suffix}")

                # 2行目： 顧客担当者名 | ルートコード | 納品日
                row2_col1, row2_col2, row2_col3 = st.columns(3)
                store_name = row2_col1.text_input("顧客担当者名", value=st.session_state["master_sname"], key=f"sname{clear_suffix}")
                route_code = row2_col2.text_input("ルートコード", value="", key=f"rcode{clear_suffix}")
                delivery_date_val = row2_col3.date_input("納品日", value=None, key=f"ddate{clear_suffix}")
                delivery_date = delivery_date_val.strftime("%Y/%m/%d") if delivery_date_val else ""

                # 3行目： 納品者 | 申請者名
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
                        now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                        full_row = [
                            now_str,           # A列
                            applicant,         # B列
                            customer_code,     # C列
                            customer_name,     # D列
                            store_name,        # E列
                            store_code,        # F列
                            delivery_date,     # G列
                            route_code,        # H列
                            delivery_person    # I列
                        ] + items_flat + [app_comment, "申請中", "", ""]

                        payload = {
                            "status": "SUBMIT_MAINTENANCE",
                            "target_sheet_url": TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            
                            st.session_state["searched_ccode"] = ""
                            st.session_state["master_cname"] = ""
                            st.session_state["master_sname"] = ""
                            st.session_state["master_scode"] = ""
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
                                st.write("**📋 申請基本情報修正**")
                                
                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "", key=f"re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名（得意先名）", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "", key=f"re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("納品書印字顧客コード", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "", key=f"re_scode_{row_id}")

                                r2_1, r2_2, r2_3 = st.columns(3)
                                edit_store_name = r2_1.text_input("顧客担当者名", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "", key=f"re_sname_{row_id}")
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
    # TAB 2: 管理具体的な状況や問題の文脈（「解決策1」の内容など）がわからないため、的確なアドバイスをするために詳しい情報を教えていただけますでしょうか？

もし差し支えなければ、以下の点について教えてください。

* **どのような問題（または課題）を解決しようとしていますか？**
* **「解決策1」ではどのような方法を検討・試されましたか？**

詳細を教えていただければ、より適切な「解決策2」をご提案いたします。
