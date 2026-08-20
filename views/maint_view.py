import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime
import time

# --- 定数設定（実際のURLを埋め込み済み） ---
GAS_URL = "https://script.google.com/macros/s/AKfycbyQFSv5PqIlOiBZB8bN4jR7I0tQ0UtXM23wE16mnHOZe640eDZXPjPP1Wzt9bSB4RzWtg/exec"  # ⚠️ ご自身のGASウェブアプリデプロイURLに置き換えてください

# 元データ用スプレッドシート
TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"

# 業務担当用スプレッドシート（転記先）
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=0#gid=0"


# --- GAS通信用ヘルパー関数 ---
def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers)
    return response.json()


# --- メイン画面関数 ---
def maintenance_admin_screen():
    st.title("📦 メンテナンス申請・承認・業務処理システム")

    # ユーザー名（サイドバー）
    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "担当者"
    st.sidebar.text_input("操作者名", key="user_name")

    # タブ作成
    tab1, tab2, tab3 = st.tabs(["📝 スタッフ申請・差戻し対応", "🔍 管理職チェック", "🚚 業務担当：シート転記"])

    # ====================================================
    # TAB 1: スタッフ申請・差戻し対応
    # ====================================================
    with tab1:
        st.write("### 📝 新規申請 / 差戻しデータ修正")
        
        # --- 新規申請フォーム ---
        with st.expander("➕ 新規申請フォームを開く", expanded=False):
            with st.form("submit_form"):
                col1, col2 = st.columns(2)
                with col1:
                    applicant = st.text_input("申請者名", value=st.session_state["user_name"])
                    customer_code = st.text_input("得意先コード")
                    customer_name = st.text_input("得意先名")
                    store_name = st.text_input("店舗名")
                with col2:
                    store_code = st.text_input("店舗コード")
                    delivery_date = st.date_input("納品日").strftime("%Y/%m/%d")
                    route_code = st.text_input("ルートコード")

                st.write("---")
                st.write("**📦 申請商品（最大5件）**")
                items_flat = []
                for i in range(5):
                    c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
                    p_code = c1.text_input(f"商品コード {i+1}", key=f"p_{i}")
                    qty = c2.number_input(f"数量 {i+1}", min_value=0, value=0, key=f"q_{i}")
                    price = c3.number_input(f"単価 {i+1}", min_value=0, value=0, key=f"pr_{i}")
                    print_flg = c4.selectbox(f"伝票出力 {i+1}", ["有", "無"], key=f"flg_{i}")
                    if p_code:
                        items_flat.extend([p_code, str(qty), str(price), print_flg])

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    payload = {
                        "status": "SUBMIT_MAINTENANCE",
                        "target_sheet_url": TARGET_SHEET_URL,
                        "applicant": applicant,
                        "customer_code": customer_code,
                        "customer_name": customer_name,
                        "store_name": store_name,
                        "store_code": store_code,
                        "delivery_date": delivery_date,
                        "route_code": route_code,
                        "items_flat": items_flat
                    }
                    res = post_to_gas(payload)
                    if res.get("status") == "success":
                        st.toast("新規申請を送信しました！", icon="🎉")
                        time.sleep(1)
                        st.rerun()

        # --- 差戻しデータ対応 ---
        st.write("---")
        st.write("#### ⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(TARGET_SHEET_CSV)
            if not df.empty and len(df.columns) >= 29:
                rejected_df = df[df.iloc[:, 28].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2
                        cust_name = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ""
                        comment = str(row.iloc[29]) if pd.notna(row.iloc[29]) else ""
                        
                        with st.expander(f"🔴 【差戻し】{cust_name} (行: {row_id}) | 理由: {comment}"):
                            with st.form(key=f"resubmit_form_{row_id}"):
                                edit_applicant = st.text_input("申請者", value=str(row.iloc[1]) if pd.notna(row.iloc[1]) else "")
                                edit_cust_code = st.text_input("得意先コード", value=str(row.iloc[2]) if pd.notna(row.iloc[2]) else "")
                                edit_cust_name = st.text_input("得意先名", value=str(row.iloc[3]) if pd.notna(row.iloc[3]) else "")
                                edit_store_name = st.text_input("店舗名", value=str(row.iloc[4]) if pd.notna(row.iloc[4]) else "")
                                edit_store_code = st.text_input("店舗コード", value=str(row.iloc[5]) if pd.notna(row.iloc[5]) else "")
                                edit_deliv_date = st.text_input("納品日", value=str(row.iloc[6]) if pd.notna(row.iloc[6]) else "")
                                edit_route_code = st.text_input("ルートコード", value=str(row.iloc[7]) if pd.notna(row.iloc[7]) else "")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    updated_row = [
                                        str(row.iloc[0]), edit_applicant, edit_cust_code, edit_cust_name,
                                        edit_store_name, edit_store_code, edit_deliv_date, edit_route_code
                                    ]
                                    updated_row.extend([str(x) if pd.notna(x) else "" for x in row.iloc[8:28].values])
                                    updated_row.extend(["申請中", "", ""])

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

    # ====================================================
    # TAB 2: 管理職チェック（承認・差戻し・削除）
    # ====================================================
    with tab2:
        st.write("### 🔍 管理職：申請承認・チェック")
        try:
            st.cache_data.clear()
            df = pd.read_csv(TARGET_SHEET_CSV)
            if not df.empty and len(df.columns) >= 29:
                pending_df = df[df.iloc[:, 28].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2
                        cust_name = str(row.iloc[3]) if pd.notna(row.iloc[3]) else ""
                        cust_code = str(row.iloc[2]) if pd.notna(row.iloc[2]) else ""

                        with st.expander(f"⏳ 【承認待ち】{cust_name}（{cust_code}） | 行: {row_id}"):
                            st.dataframe(pd.DataFrame([row.fillna("")]), use_container_width=True)
                            with st.form(key=f"mgr_form_{row_id}"):
                                comment = st.text_input("コメント / 差戻し理由", key=f"comment_{row_id}")
                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now().strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    updated_row = [str(x) if pd.notna(x) else "" for x in row.iloc[:28].values]
                                    status_type = ""

                                    if btn_approve:
                                        status_type = "APPROVE_MAINTENANCE"
                                        updated_row.extend([mgr_name, now_str, comment])
                                    elif btn_reject:
                                        status_type = "REJECT_MAINTENANCE"
                                        updated_row.extend(["差戻し", now_str, comment])
                                    elif btn_delete:
                                        status_type = "DELETE_MAINTENANCE"
                                        updated_row.extend(["削除", now_str, comment])

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

    # ====================================================
    # TAB 3: 業務担当（承認済みデータを別シートへ転記）
    # ====================================================
    with tab3:
        st.write("### 🚚 業務担当：承認済みデータの転記・処理")
        try:
            st.cache_data.clear()
            df = pd.read_csv(TARGET_SHEET_CSV)

            if df.empty or len(df.columns) < 29:
                st.info("現在、処理可能なデータはありません。")
            else:
                ac_series = df.iloc[:, 28].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, 28].isna()) & 
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
                        mgr_name = str(row.iloc[28]) if pd.notna(row.iloc[28]) else ""

                        expander_label = f"🟢【承認済】{cust_name}（{cust_code}） | 承認者: {mgr_name} | 申請日: {timestamp}"

                        with st.expander(expander_label):
                            st.dataframe(pd.DataFrame([row.fillna("")]), use_container_width=True)

                            with st.form(key=f"transfer_form_{row_id}"):
                                op_memo = st.text_input("業務メモ / 伝票番号など（任意）", key=f"op_memo_{row_id}")
                                btn_transfer = st.form_submit_button("📋 別シート（業務管理用）へ出力・転記", type="primary", use_container_width=True)

                                if btn_transfer:
                                    action_time = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
                                    op_user = st.session_state["user_name"]

                                    # 元データ1行分 + 末尾に「業務転記日時」「業務担当者名」「業務メモ」を追加
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
