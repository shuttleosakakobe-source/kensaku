import streamlit as st
import pandas as pd
from datetime import datetime
from utils import post_to_gas
from data_loader import load_customer_master

def maintenance_admin_screen():
    st.markdown("### 📦 臨時納品・メンテナンス管理")
    
    if st.button("⬅️ メイン画面に戻る"):
        st.session_state.current_page = "main"
        st.rerun()

    tab1, tab2 = st.tabs(["📝 申請フォーム", "🔍 管理職チェック"])

    # ----------------------------------------------------
    # TAB 1: 申請フォーム
    # ----------------------------------------------------
    with tab1:
        st.write("#### 臨時納品 申請入力")
        cust_master = load_customer_master()
        c_code_input = st.text_input("顧客コードを入力").strip()
        
        store_name, cust_name, store_code = "", "", ""
        if c_code_input in cust_master:
            info = cust_master[c_code_input]
            store_name = info.get("store_name", "")
            cust_name = info.get("cust_name", "")
            store_code = info.get("store_code", "")
            st.success(f"【該当顧客】 {cust_name} （加盟店: {store_name}）")

        with st.form("maint_form"):
            applicant = st.text_input("担当者名", value=st.session_state.get("user_name", ""))
            
            c1, c2 = st.columns(2)
            with c1:
                customer_code = st.text_input("顧客コード", value=c_code_input)
                customer_name = st.text_input("顧客名", value=cust_name)
            with c2:
                store_code_val = st.text_input("加盟店コード", value=store_code)
                store_name_val = st.text_input("加盟店名", value=store_name)

            d1, d2 = st.columns(2)
            with d1:
                delivery_date = st.text_input("納品希望日 (YYYY/MM/DD)", value=datetime.now().strftime("%Y/%m/%d"))
            with d2:
                route_code = st.text_input("納品ルートコード", value="")

            st.write("---")
            st.write("##### 📦 申請商品（最大5件）")

            # 入力保持用データ構造
            item_inputs = []
            for i in range(1, 6):
                ic1, ic2, ic3, ic4 = st.columns([2, 1, 1, 1])
                with ic1: 
                    p_code = st.text_input(f"商品記号 {i}", key=f"p_code_{i}").strip()
                with ic2: 
                    qty_str = st.text_input(f"数量 {i}", value="0", key=f"qty_{i}").strip()
                with ic3: 
                    unit_price_str = st.text_input(f"単価 {i}", value="0", key=f"amt_{i}").strip()
                with ic4: 
                    slip = st.selectbox(f"伝票出力 {i}", ["有", "無"], key=f"slip_{i}")
                
                item_inputs.append({
                    "p_code": p_code,
                    "qty_str": qty_str,
                    "price_str": unit_price_str,
                    "slip": slip
                })

            submitted = st.form_submit_button("送信する", type="primary", use_container_width=True)

            if submitted:
                # 基本情報の未入力バリデーション（商品記号・単価・数量 以外のすべての項目）
                required_fields = [
                    ("担当者名", applicant),
                    ("顧客コード", customer_code),
                    ("顧客名", customer_name),
                    ("加盟店コード", store_code_val),
                    ("加盟店名", store_name_val),
                    ("納品希望日", delivery_date),
                    ("納品ルートコード", route_code)
                ]
                
                missing_labels = [label for label, val in required_fields if not str(val).strip()]

                if missing_labels:
                    st.error(f"⚠️ 以下の必須項目が未入力です: {', '.join(missing_labels)}")
                else:
                    # 商品データの成形（商品記号がない場合は伝票出力を空文字にする）
                    items_flat = []
                    for item in item_inputs:
                        p_code = item["p_code"]
                        qty = int(item["qty_str"]) if item["qty_str"].isdigit() else 0
                        price = int(item["price_str"]) if item["price_str"].isdigit() else 0
                        
                        if p_code:
                            slip_val = item["slip"]
                        else:
                            slip_val = ""  # 商品記号がない場合は伝票出力を設定しない
                        
                        items_flat.extend([p_code, qty, price, slip_val])

                    payload = {
                        "status": "SUBMIT_MAINTENANCE",
                        "target_sheet_url": "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0",
                        "applicant": applicant,
                        "customer_code": customer_code,
                        "customer_name": customer_name,
                        "store_name": store_name_val,
                        "store_code": store_code_val,
                        "delivery_date": delivery_date,
                        "route_code": route_code,
                        "items_flat": items_flat
                    }
                    
                    with st.spinner("送信中..."):
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.success("🎉 申請の書き込みが完了しました！")
                        else:
                            st.error(f"送信エラー: {res.get('message')}")

    # ----------------------------------------------------
    # TAB 2: 管理職チェック（訂正・差戻し対応）
    # ----------------------------------------------------
    with tab2:
        st.write("#### 🔍 申請データ確認・訂正・承認")

        TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/export?format=csv&gid=0"

        try:
            df = pd.read_csv(TARGET_SHEET_CSV)

            if df.empty:
                st.info("現在、申請データはありません。")
            else:
                fc1, fc2, fc3 = st.columns(3)
                with fc1:
                    filter_status = st.selectbox("ステータス表示", ["未対応（申請中）のみ", "差戻しのみ", "承認済みのみ", "すべて"])
                with fc2:
                    filter_applicant = st.selectbox("担当者絞り込み", ["すべて"] + list(df.iloc[:, 1].dropna().unique()))
                with fc3:
                    search_kw = st.text_input("顧客名・コード検索", "").strip()

                filtered_df = df.copy()

                if len(filtered_df.columns) >= 29:
                    if filter_status == "未対応（申請中）のみ":
                        filtered_df = filtered_df[filtered_df.iloc[:, 28].isna() | (filtered_df.iloc[:, 28] == "申請中")]
                    elif filter_status == "差戻しのみ":
                        filtered_df = filtered_df[filtered_df.iloc[:, 28] == "差戻し"]
                    elif filter_status == "承認済みのみ":
                        filtered_df = filtered_df[filtered_df.iloc[:, 28] == "承認済み"]

                if filter_applicant != "すべて":
                    filtered_df = filtered_df[filtered_df.iloc[:, 1] == filter_applicant]
                if search_kw:
                    filtered_df = filtered_df[
                        filtered_df.iloc[:, 2].astype(str).str.contains(search_kw, na=False) |
                        filtered_df.iloc[:, 3].astype(str).str.contains(search_kw, na=False)
                    ]

                st.dataframe(filtered_df, use_container_width=True)
                st.write("---")

                for idx, row in filtered_df.iloc[::-1].iterrows():
                    row_id = idx + 2
                    
                    timestamp = str(row.iloc[0]) if len(row) > 0 and pd.notna(row.iloc[0]) else ""
                    applicant = str(row.iloc[1]) if len(row) > 1 and pd.notna(row.iloc[1]) else ""
                    cust_code = str(row.iloc[2]) if len(row) > 2 and pd.notna(row.iloc[2]) else ""
                    cust_name = str(row.iloc[3]) if len(row) > 3 and pd.notna(row.iloc[3]) else ""
                    store_name = str(row.iloc[4]) if len(row) > 4 and pd.notna(row.iloc[4]) else ""
                    store_code = str(row.iloc[5]) if len(row) > 5 and pd.notna(row.iloc[5]) else ""
                    delivery_date = str(row.iloc[6]) if len(row) > 6 and pd.notna(row.iloc[6]) else ""
                    route_code = str(row.iloc[7]) if len(row) > 7 and pd.notna(row.iloc[7]) else ""
                    
                    status_val = str(row.iloc[28]) if len(row) >= 29 and pd.notna(row.iloc[28]) else "申請中"
                    comment_val = str(row.iloc[29]) if len(row) >= 30 and pd.notna(row.iloc[29]) else ""

                    badge = "🟡 申請中" if status_val == "申請中" else ("🔴 差戻し" if status_val == "差戻し" else "🟢 承認済み")
                    expander_label = f"{badge} | 【{timestamp}】 {applicant} 担当 | {cust_name}（{cust_code}）"
                    
                    with st.expander(expander_label):
                        st.markdown(f"**現在のステータス:** `{status_val}`" + (f" | **備考・差戻理由:** {comment_val}" if comment_val else ""))
                        st.markdown("##### ✏️ データの確認・訂正")
                        
                        with st.form(key=f"edit_form_{row_id}"):
                            ec1, ec2 = st.columns(2)
                            with ec1:
                                edit_applicant = st.text_input("担当者名", value=applicant, key=f"e_app_{row_id}")
                                edit_cust_code = st.text_input("顧客コード", value=cust_code, key=f"e_ccode_{row_id}")
                                edit_cust_name = st.text_input("顧客名", value=cust_name, key=f"e_cname_{row_id}")
                                edit_delivery = st.text_input("納品希望日", value=delivery_date, key=f"e_deliv_{row_id}")
                            with ec2:
                                edit_store_name = st.text_input("加盟店名", value=store_name, key=f"e_sname_{row_id}")
                                edit_store_code = st.text_input("加盟店コード", value=store_code, key=f"e_scode_{row_id}")
                                edit_route = st.text_input("納品ルート", value=route_code, key=f"e_route_{row_id}")

                            st.markdown("**📋 商品明細の訂正**")
                            updated_items = []
                            for i in range(5):
                                b_col = 8 + (i * 4)
                                p_val = str(row.iloc[b_col]).strip() if b_col < len(row) and pd.notna(row.iloc[b_col]) else ""
                                q_val = str(row.iloc[b_col+1]) if b_col+1 < len(row) and pd.notna(row.iloc[b_col+1]) else "0"
                                a_val = str(row.iloc[b_col+2]) if b_col+2 < len(row) and pd.notna(row.iloc[b_col+2]) else "0"
                                s_val = str(row.iloc[b_col+3]).strip() if b_col+3 < len(row) and pd.notna(row.iloc[b_col+3]) else "有"

                                ic1, ic2, ic3, ic4 = st.columns([2, 1, 1, 1])
                                with ic1: ep = st.text_input(f"商品記号 {i+1}", value=p_val, key=f"ep_{row_id}_{i}").strip()
                                with ic2: eq = st.text_input(f"数量 {i+1}", value=q_val, key=f"eq_{row_id}_{i}").strip()
                                with ic3: ea = st.text_input(f"単価 {i+1}", value=a_val, key=f"ea_{row_id}_{i}").strip()
                                with ic4: es = st.selectbox(f"伝票出力 {i+1}", ["有", "無"], index=0 if s_val != "無" else 1, key=f"es_{row_id}_{i}")
                                
                                # 商品記号がない場合は数量・単価・伝票出力を空で処理
                                eq_num = int(eq) if eq.isdigit() else 0
                                ea_num = int(ea) if ea.isdigit() else 0
                                es_str = es if ep else ""
                                
                                updated_items.extend([ep, eq_num, ea_num, es_str])

                            st.write("---")
                            mgr_comment = st.text_input("管理職コメント（承認時のメモ / 差戻し理由）", value=comment_val, key=f"comm_{row_id}")

                            b_col1, b_col2 = st.columns(2)
                            with b_col1:
                                btn_approve = st.form_submit_button("✅ 訂正内容を保存して【承認】", type="primary", use_container_width=True)
                            with b_col2:
                                btn_reject = st.form_submit_button("↩️ 【差戻し】を実行", use_container_width=True)

                            if btn_approve:
                                updated_row = [
                                    timestamp, edit_applicant, edit_cust_code, edit_cust_name,
                                    edit_store_name, edit_store_code, edit_delivery, edit_route
                                ] + updated_items
                                
                                payload = {
                                    "status": "APPROVE_MAINTENANCE",
                                    "target_sheet_url": "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0",
                                    "row_index": row_id,
                                    "updated_row": updated_row,
                                    "comment": mgr_comment,
                                    "manager_name": st.session_state.get("user_name", "管理職")
                                }
                                with st.spinner("承認処理中..."):
                                    res = post_to_gas(payload)
                                    if res.get("status") == "success":
                                        st.success("🎉 承認処理が完了しました！")
                                        st.rerun()

                            if btn_reject:
                                if not mgr_comment:
                                    st.error("⚠️ 差戻しの場合は「管理職コメント」に理由を入力してください。")
                                else:
                                    payload = {
                                        "status": "REJECT_MAINTENANCE",
                                        "target_sheet_url": "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0",
                                        "row_index": row_id,
                                        "comment": mgr_comment,
                                        "manager_name": st.session_state.get("user_name", "管理職")
                                    }
                                    with st.spinner("差戻し処理中..."):
                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            st.warning("↩️ 差戻し処理を完了しました。")
                                            st.rerun()

        except Exception as e:
            st.error(f"⚠️ データの取得に失敗しました: {e}")
