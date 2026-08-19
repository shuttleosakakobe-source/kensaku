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
        
        # 顧客マスターのロード
        cust_master = load_customer_master()
        
        c_code_input = st.text_input("顧客コードを入力").strip()
        
        store_name = ""
        cust_name = ""
        store_code = ""
        
        if c_code_input in cust_master:
            info = cust_master[c_code_input]
            store_name = info.get("store_name", "")
            cust_name = info.get("cust_name", "")
            store_code = info.get("store_code", "")
            st.success(f"【該当顧客】 {cust_name} （加盟店: {store_name}）")
        elif c_code_input:
            st.caption("※該当する顧客コードがマスターに見つかりません。手入力してください。")

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
                delivery_date = st.date_input("納品希望日", datetime.now()).strftime("%Y/%m/%d")
            with d2:
                route_code = st.text_input("納品ルートコード", value="")

            st.write("---")
            st.write("##### 📦 申請商品（最大5件）")

            items_flat = []
            for i in range(1, 6):
                st.markdown(f"**商品 {i}**")
                ic1, ic2, ic3, ic4 = st.columns([2, 1, 1, 1])
                with ic1:
                    p_code = st.text_input(f"品記号", key=f"p_code_{i}")
                with ic2:
                    qty = st.number_input(f"数量", min_value=0, value=0, key=f"qty_{i}")
                with ic3:
                    amt = st.number_input(f"金額", min_value=0, value=0, key=f"amt_{i}")
                with ic4:
                    slip = st.selectbox(f"伝票出力", ["要", "不要"], key=f"slip_{i}")

                items_flat.extend([p_code, qty, amt, slip])

            submitted = st.form_submit_button("送信する", type="primary", use_container_width=True)

            if submitted:
                if not customer_code or not applicant:
                    st.error("担当者名と顧客コードは必須入力です。")
                else:
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
                    
                    with st.spinner("スプレッドシートへ送信中..."):
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.success("🎉 申請の書き込みが完了しました！")
                        else:
                            st.error(f"送信エラー: {res.get('message')}")

    # ----------------------------------------------------
    # TAB 2: 管理職チェック
    # ----------------------------------------------------
    with tab2:
        st.write("#### 🔍 未チェック一覧（管理職専用）")
        st.caption("スプレッドシートに蓄積された申請データを確認します。")

        TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/export?format=csv&gid=0"

        try:
            df = pd.read_csv(TARGET_SHEET_CSV)

            if df.empty:
                st.info("現在、申請データはありません。")
            else:
                st.dataframe(df, use_container_width=True)
                st.write("---")

                st.markdown("##### 📄 申請詳細・明細確認")
                
                for idx, row in df.iloc[::-1].iterrows():
                    timestamp = row.iloc[0] if len(row) > 0 else ""
                    applicant = row.iloc[1] if len(row) > 1 else ""
                    cust_code = row.iloc[2] if len(row) > 2 else ""
                    cust_name = row.iloc[3] if len(row) > 3 else ""
                    store_name = row.iloc[4] if len(row) > 4 else ""
                    store_code = row.iloc[5] if len(row) > 5 else ""
                    delivery_date = row.iloc[6] if len(row) > 6 else ""
                    route_code = row.iloc[7] if len(row) > 7 else ""

                    expander_label = f"【{timestamp}】 {applicant} 担当 | {cust_name}（{cust_code}）"
                    
                    with st.expander(expander_label):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f"**担当者:** {applicant}")
                            st.markdown(f"**顧客名:** {cust_name} (`{cust_code}`)")
                            st.markdown(f"**加盟店名:** {store_name} (`{store_code}`)")
                        with c2:
                            st.markdown(f"**納品指定日:** {delivery_date}")
                            st.markdown(f"**納品ルート:** {route_code}")
                            st.markdown(f"**申請日時:** {timestamp}")

                        items_list = []
                        for i in range(5):
                            base_col = 8 + (i * 4)
                            if base_col < len(row):
                                p_code = str(row.iloc[base_col]).strip() if pd.notna(row.iloc[base_col]) else ""
                                if p_code:
                                    qty = row.iloc[base_col + 1] if base_col + 1 < len(row) else 0
                                    amt = row.iloc[base_col + 2] if base_col + 2 < len(row) else 0
                                    slip = row.iloc[base_col + 3] if base_col + 3 < len(row) else ""
                                    items_list.append({
                                        "枠": f"商品{i+1}",
                                        "品記号": p_code,
                                        "数量": qty,
                                        "金額": amt,
                                        "伝票出力": slip
                                    })

                        st.markdown("**📋 申請商品明細:**")
                        if items_list:
                            st.table(pd.DataFrame(items_list))
                        else:
                            st.caption("※明細商品なし")

        except Exception as e:
            st.error(f"⚠️ データの取得に失敗しました: {e}")
