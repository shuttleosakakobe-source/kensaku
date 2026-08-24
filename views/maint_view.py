import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timezone, timedelta

GAS_URL = "https://script.google.com/macros/s/AKfycbwLUMtoHyxx8kX0PpwxeNqnH-uVF1kVGFi3WVo8f6URehPcpexohXlltFPfwYe5dkjiGw/exec"

TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=457221393#gid=457221393"
DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=457221393"
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"

JST = timezone(timedelta(hours=+9), 'JST')


def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def maintenance_admin_screen():
    st.set_page_config(page_title="メンテナンス申請管理システム", layout="wide")
    st.header("📦 メンテナンス申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "form_clear_key" not in st.session_state:
        st.session_state["form_clear_key"] = 0

    clear_suffix = f"_{st.session_state['form_clear_key']}"

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📝 スタッフ申請・差戻し対応", 
        "🔍 管理職チェック", 
        "🚚 業務担当：シート転記", 
        "✅ メンテナンスチェック",
        "🖨️ フォーマット転記・PDF出力"
    ])

    with tab1:
        st.subheader("📝 新規メンテナンス申請 / 差戻しデータの修正・再申請")
        try:
            df_main = pd.read_csv(TARGET_SHEET_CSV, dtype=str)
        except Exception:
            df_main = pd.DataFrame()

        rejected_df = pd.DataFrame()
        if not df_main.empty and len(df_main.columns) >= 29:
            rejected_df = df_main[df_main.iloc[:, 28].fillna("").str.strip() == "差戻し"]

        edit_mode = False
        target_row_index = None
        default_vals = {}

        if not rejected_df.empty:
            st.markdown("---")
            st.warning(f"⚠️ 差戻しされているデータが **{len(rejected_df)} 件** あります。")
            selected_reject_idx = st.selectbox(
                "修正する差戻しデータを選択", 
                options=rejected_df.index,
                format_func=lambda idx: f"行 {idx+1} | 加盟店: {rejected_df.loc[idx, df_main.columns[4]] if len(df_main.columns)>4 else ''}",
                key=f"sel_reject{clear_suffix}"
            )
            if selected_reject_idx is not None:
                if st.button("この差戻しデータを読み込んで修正する", key=f"load_rej{clear_suffix}"):
                    edit_mode = True
                    target_row_index = int(selected_reject_idx) + 1
                    row_data = rejected_df.loc[selected_reject_idx]
                    default_vals = {
                        "applicant": row_data.iloc[1] if len(row_data) > 1 else "",
                        "customer_code": row_data.iloc[2] if len(row_data) > 2 else "",
                        "customer_name": row_data.iloc[3] if len(row_data) > 3 else "",
                        "store_name": row_data.iloc[4] if len(row_data) > 4 else "",
                        "store_code": row_data.iloc[5] if len(row_data) > 5 else "",
                        "delivery_date": row_data.iloc[6] if len(row_data) > 6 else "",
                        "route_code": row_data.iloc[7] if len(row_data) > 7 else "",
                    }
                    st.session_state["edit_defaults"] = default_vals
                    st.session_state["edit_row_index"] = target_row_index
                    st.rerun()

        if "edit_defaults" in st.session_state and st.session_state.get("edit_row_index"):
            edit_mode = True
            default_vals = st.session_state["edit_defaults"]
            target_row_index = st.session_state["edit_row_index"]
            st.info(f"ℹ️ 行番号 {target_row_index} のデータを編集中です。")
            if st.button("新規申請モードに戻る", key=f"cancel_edit{clear_suffix}"):
                del st.session_state["edit_defaults"]
                del st.session_state["edit_row_index"]
                st.rerun()

        with st.form(key=f"maintenance_form{clear_suffix}"):
            col1, col2 = st.columns(2)
            with col1:
                applicant = st.text_input("申請者名", value=default_vals.get("applicant", st.session_state["user_name"]))
                customer_code = st.text_input("顧客コード", value=default_vals.get("customer_code", ""))
                customer_name = st.text_input("顧客名", value=default_vals.get("customer_name", ""))
            with col2:
                store_name = st.text_input("加盟店名", value=default_vals.get("store_name", ""))
                store_code = st.text_input("加盟店コード", value=default_vals.get("store_code", ""))
                delivery_date = st.text_input("納品日", value=default_vals.get("delivery_date", ""))
                route_code = st.text_input("ルートコード", value=default_vals.get("route_code", ""))

            st.markdown("### 📦 商品明細（最大5件）")
            items_flat = []
            for i in range(1, 6):
                st.markdown(f"**商品 {i}**")
                ic1, ic2, ic3, ic4 = st.columns(4)
                with ic1:
                    p_code = st.text_input(f"商品記号 {i}", key=f"p_code_{i}{clear_suffix}")
                with ic2:
                    p_qty = st.text_input(f"発注数 {i}", key=f"p_qty_{i}{clear_suffix}")
                with ic3:
                    p_price = st.text_input(f"商品単価 {i}", key=f"p_price_{i}{clear_suffix}")
                with ic4:
                    p_flag = st.text_input(f"伝票出力 {i}", key=f"p_flag_{i}{clear_suffix}")
                items_flat.extend([p_code, p_qty, p_price, p_flag])

            submitted = st.form_submit_button("🚀 申請を送信する", type="primary")
            if submitted:
                payload = {
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
                if edit_mode and target_row_index:
                    payload["status"] = "RESUBMIT_MAINTENANCE"
                    payload["row_index"] = target_row_index
                else:
                    payload["status"] = "SUBMIT_MAINTENANCE"

                with st.spinner("送信中..."):
                    res = post_to_gas(payload)
                    if res.get("status") == "success":
                        st.success("✨ 申請が正常に送信されました！")
                        if "edit_defaults" in st.session_state:
                            del st.session_state["edit_defaults"]
                            del st.session_state["edit_row_index"]
                        st.session_state["form_clear_key"] += 1
                        st.rerun()
                    else:
                        st.error(f"送信エラー: {res.get('message')}")

    with tab2:
        st.subheader("🔍 管理職チェック・承認 / 差戻し / 削除")
        try:
            df_mgr = pd.read_csv(TARGET_SHEET_CSV, dtype=str)
        except Exception:
            df_mgr = pd.DataFrame()

        if df_mgr.empty:
            st.info("データがありません。")
        else:
            st.dataframe(df_mgr, use_container_width=True)
            st.markdown("---")
            row_idx_input = st.number_input("処理する行番号を選択", min_value=1, max_value=len(df_mgr)+1, value=1, step=1)
            manager_name = st.text_input("承認者（管理職名）", value=st.session_state["user_name"])
            comment_input = st.text_input("コメント（差戻し理由など）", value="")

            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("✅ 承認する", type="primary"):
                    res = post_to_gas({
                        "status": "APPROVE_MAINTENANCE", "target_sheet_url": TARGET_SHEET_URL,
                        "row_index": int(row_idx_input), "manager_name": manager_name, "comment": comment_input
                    })
                    if res.get("status") == "success":
                        st.success("承認完了")
                        st.rerun()
            with c2:
                if st.button("↩️ 差戻しする"):
                    res = post_to_gas({
                        "status": "REJECT_MAINTENANCE", "target_sheet_url": TARGET_SHEET_URL,
                        "row_index": int(row_idx_input), "comment": comment_input
                    })
                    if res.get("status") == "success":
                        st.warning("差戻し完了")
                        st.rerun()
            with c3:
                if st.button("🗑️ 削除する"):
                    res = post_to_gas({
                        "status": "DELETE_MAINTENANCE", "target_sheet_url": TARGET_SHEET_URL,
                        "row_index": int(row_idx_input), "comment": comment_input
                    })
                    if res.get("status") == "success":
                        st.error("削除完了")
                        st.rerun()

    with tab3:
        st.subheader("🚚 業務担当：承認済みデータの別シート転記")
        try:
            df_op = pd.read_csv(TARGET_SHEET_CSV, dtype=str)
        except Exception:
            df_op = pd.DataFrame()

        if df_op.empty:
            st.info("データがありません。")
        else:
            st.dataframe(df_op, use_container_width=True)
            st.markdown("---")
            op_row_idx = st.number_input("転記する行番号を選択", min_value=1, max_value=len(df_op)+1, value=1, step=1, key="op_row_idx")
            op_user = st.text_input("業務担当者名", value=st.session_state["user_name"], key="op_user_name")

            if st.button("📥 指定行を業務専用シートへ転記する", type="primary"):
                target_row_data = df_op.iloc[op_row_idx - 1].fillna("").tolist()
                res = post_to_gas({
                    "status": "TRANSFER_TO_OPERATOR", "target_sheet_url": TARGET_SHEET_URL,
                    "dest_sheet_url": DEST_SHEET_URL, "row_index": int(op_row_idx),
                    "transfer_row": target_row_data, "action_time": datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S"), "op_user": op_user
                })
                if res.get("status") == "success":
                    st.success("転記完了！")
                    st.rerun()

    with tab4:
        st.subheader("✅ メンテナンスチェック画面")
        try:
            df_check = pd.read_csv(DEST_SHEET_CSV, dtype=str)
        except Exception:
            df_check = pd.DataFrame()
        if df_check.empty:
            st.info("チェック対象データがありません。")
        else:
            st.dataframe(df_check, use_container_width=True)

    with tab5:
        st.subheader("🖨️ 専用スプレッドシートフォーマット出力・PDF印刷")
        st.caption("選択した加盟店のデータを指定フォーマット（最大3件/ページ）に自動転記し、スプレッドシートを開いてPDF出力を行います。")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、出力対象となるデータがありません。")
            else:
                store_col_idx = 4
                df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                stores = df_print["_store_name"].unique()

                selected_store = st.selectbox("🖨️ 出力する加盟店を選択してください", stores, key="format_print_store_v2")

                if selected_store:
                    store_df = df_print[df_print["_store_name"] == selected_store]
                    total_records = len(store_df)

                    st.success(f"🏪 加盟店: **{selected_store}** （対象データ件数: {total_records} 件）※3件ごとにページが分かれます。")

                    if st.button("🚀 スプレッドシートのフォーマットに転記して印刷画面を開く", type="primary"):
                        records_payload = []
                        for _, r_row in store_df.iterrows():
                            prods = []
                            for pi in range(5):
                                b_idx = 9 + (pi * 4)
                                p_c = str(r_row.iloc[b_idx]) if b_idx < len(r_row) and pd.notna(r_row.iloc[b_idx]) else ""
                                p_q = str(r_row.iloc[b_idx+1]) if b_idx+1 < len(r_row) and pd.notna(r_row.iloc[b_idx+1]) else ""
                                p_pr = str(r_row.iloc[b_idx+2]) if b_idx+2 < len(r_row) and pd.notna(r_row.iloc[b_idx+2]) else ""
                                p_flg = str(r_row.iloc[b_idx+3]) if b_idx+3 < len(r_row) and pd.notna(r_row.iloc[b_idx+3]) else ""
                                prods.append({"code": p_c, "qty": p_q, "price": p_pr, "flag": p_flg})

                            rec_dict = {
                                "customer_code": str(r_row.iloc[2]) if len(r_row) > 2 and pd.notna(r_row.iloc[2]) else "",
                                "customer_name": str(r_row.iloc[3]) if len(r_row) > 3 and pd.notna(r_row.iloc[3]) else "",
                                "store_name": str(r_row.iloc[4]) if len(r_row) > 4 and pd.notna(r_row.iloc[4]) else "",
                                "store_code": str(r_row.iloc[5]) if len(r_row) > 5 and pd.notna(r_row.iloc[5]) else "",
                                "delivery_date": str(r_row.iloc[6]) if len(r_row) > 6 and pd.notna(r_row.iloc[6]) else "",
                                "route_code": str(r_row.iloc[7]) if len(r_row) > 7 and pd.notna(r_row.iloc[7]) else "",
                                "delivery_person": str(r_row.iloc[8]) if len(r_row) > 8 and pd.notna(r_row.iloc[8]) else "",
                                "app_user": str(r_row.iloc[1]) if len(r_row) > 1 and pd.notna(r_row.iloc[1]) else "",
                                "mgr_user": str(r_row.iloc[30]) if len(r_row) > 30 and pd.notna(r_row.iloc[30]) else "",
                                "op_user": str(r_row.iloc[32]) if len(r_row) > 32 and pd.notna(r_row.iloc[32]) else st.session_state["user_name"],
                                "app_comment": str(r_row.iloc[29]) if len(r_row) > 29 and pd.notna(r_row.iloc[29]) else "",
                                "p1_code": prods[0]["code"], "p1_qty": prods[0]["qty"], "p1_price": prods[0]["price"], "p1_flag": prods[0]["flag"],
                                "p2_code": prods[1]["code"], "p2_qty": prods[1]["qty"], "p2_price": prods[1]["price"], "p2_flag": prods[1]["flag"],
                                "p3_code": prods[2]["code"], "p3_qty": prods[2]["qty"], "p3_price": prods[2]["price"], "p3_flag": prods[2]["flag"],
                                "p4_code": prods[3]["code"], "p4_qty": prods[3]["qty"], "p4_price": prods[3]["price"], "p4_flag": prods[3]["flag"],
                                "p5_code": prods[4]["code"], "p5_qty": prods[4]["qty"], "p5_price": prods[4]["price"], "p5_flag": prods[4]["flag"],
                            }
                            records_payload.append(rec_dict)

                        res = post_to_gas({
                            "status": "EXPORT_PRINT_FORMAT",
                            "dest_sheet_url": DEST_SHEET_URL,
                            "records": records_payload
                        })

                        if res.get("status") == "success":
                            sheet_url = res.get("sheet_url")
                            st.success("🎉 指定フォーマットへの転記が完了しました！")
                            st.markdown(f"👉 **[印刷用スプレッドシート（指定フォーマット）を開く]({sheet_url})**")
                            st.info("スプレッドシートを開き、印刷プレビュー（Ctrl+P / ⌘+P）からPDFとして保存してください。")
                        else:
                            st.error(f"転記失敗: {res.get('message')}")

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")

if __name__ == "__main__":
    maintenance_admin_screen()
