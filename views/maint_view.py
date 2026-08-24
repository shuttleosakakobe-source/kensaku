import streamlit as st
from datetime import datetime, timezone, timedelta
import io
import json
import time
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import requests

GAS_URL = "https://script.google.com/macros/s/AKfycbwLUMtoHyxx8kX0PpwxeNqnH-uVF1kVGFi3WVo8f6URehPcpexohXlltFPfwYe5dkjiGw/exec"

TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=0#gid=0"
TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv"
DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=457221393#gid=457221393"
DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=457221393"
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"

# 1. 認証スコープの設定
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# 日本時間（JST = UTC+9）のタイムゾーン定義
JST = timezone(timedelta(hours=+9), 'JST')


def get_gspread_client():
    creds_dict = st.secrets["gcp_service_account"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def transfer_and_export_pdf_for_store(selected_store_name, store_df):
    """指定された加盟店のデータを転写・配置し、PDFデータを取得する関数"""
    spreadsheet_id = "1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI"
    src_gid = "0"
    dest_gid = "457221393"

    try:
        client = get_gspread_client()
        ss = client.open_by_key(spreadsheet_id)
    except Exception as e:
        st.error(f"スプレッドシートへの接続に失敗しました: {e}")
        return None

    src_sheet = None
    dest_sheet = None
    for sheet in ss.worksheets():
        if str(sheet.id) == src_gid:
            src_sheet = sheet
        elif str(sheet.id) == dest_gid:
            dest_sheet = sheet

    if not src_sheet or not dest_sheet:
        st.error("指定されたシート（gid）が見つかりませんでした。")
        return None

    # 転写先シートをクリア
    dest_sheet.clear()

    updates = []
    # C1セル：加盟店名 ＋ "様"
    updates.append({
        'range': 'C1',
        'values': [[f"{selected_store_name}様 "]]
    })

    for idx, (_, row) in enumerate(store_df.iterrows()):
        val = lambda i: str(row.iloc[i]) if i < len(row) and pd.notna(row.iloc[i]) else ""

        store_code = val(5)     # 加盟店コード
        customer_name = val(3)  # 顧客名
        sekininsha = val(30)    # 責任者 (管理職名)
        shyorisha = val(32)     # 処理者
        
        if idx == 0:
            updates.append({
                'range': 'A4:E4',
                'values': [[store_code, f"{customer_name}様 ", "", sekininsha, shyorisha]]
            })
        break

    if updates:
        dest_sheet.batch_update(updates)

    # PDFのエクスポート処理
    export_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=pdf&gid={dest_gid}&size=A4&portrait=true&fitw=true"

    access_token = client.auth.token
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(export_url, headers=headers)

    if response.status_code == 200:
        return response.content
    else:
        st.error(f"PDFのエクスポートに失敗しました。(ステータスコード: {response.status_code})")
        return None


def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=10)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def maintenance_admin_screen():
    st.markdown("""
        <style>
        input:disabled, textarea:disabled {
            -webkit-text-fill-color: #31333F !important;
            color: #31333F !important;
            opacity: 1 !important;
        }
        div[data-testid="stForm"] button[disabled] {
            display: none !important;
        }
        @media print {
            body { background: white !important; color: black !important; }
            header, footer, [data-testid="stSidebar"], .stButton, button, .no-print { display: none !important; }
            .print-sheet { page-break-after: always; border: none !important; padding: 0px !important; margin: 0px !important; background: white !important; box-shadow: none !important; }
        }
        .print-sheet {
            border: 1px solid #d6d6d6;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 25px;
            background: #ffffff;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            font-family: monospace, sans-serif;
        }
        .sheet-block {
            border: 1px solid #aaa;
            padding: 10px;
            margin-bottom: 15px;
            background: #fafafa;
            border-radius: 4px;
        }
        .block-title {
            font-size: 13px;
            font-weight: bold;
            color: #333;
            margin-bottom: 6px;
            border-bottom: 1px solid #ddd;
            padding-bottom: 3px;
        }
        .grid-row {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 5px;
            font-size: 11px;
            margin-bottom: 4px;
        }
        .grid-cell {
            background: #fff;
            border: 1px solid #ccc;
            padding: 4px 6px;
            border-radius: 3px;
        }
        .grid-cell span.lbl { font-size: 9px; color: #666; display: block; }
        .grid-cell span.val { font-weight: bold; color: #111; }
        .memo-cell {
            background: #fff;
            border: 1px solid #ccc;
            padding: 6px;
            font-size: 11px;
            margin-top: 4px;
            border-radius: 3px;
        }
        </style>
    """, unsafe_allow_html=True)

    st.header("📦 メンテナンス申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

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

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📝 スタッフ申請・差戻し対応", 
        "🔍 管理職チェック", 
        "🚚 業務担当：シート転記", 
        "✅ メンテナンスチェック",
        "🖨️ 加盟店別 印刷プレビュー"
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with tab1:
        st.subheader("📝 新規申請 / 差戻しデータ修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):
            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input("🔍 顧客コード入力", value=st.session_state["searched_ccode"], key=f"cust_code_search{clear_suffix}")
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary")

            if btn_search:
                if cust_code_input:
                    try:
                        df_master = pd.read_csv(CUSTOMER_MASTER_CSV, dtype=str, storage_options={"User-Agent": "Mozilla/5.0"})
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
                        full_row = [now_str, applicant, customer_code, customer_name, store_name, store_code, delivery_date, route_code, delivery_person] + items_flat + [app_comment, "申請中", "", ""]
                        payload = {"action": "SUBMIT_MAINTENANCE", "target_sheet_url": TARGET_SHEET_URL, "full_row": full_row}
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["searched_ccode"] = ""
                            st.session_state["form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

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
        except Exception as e:
            st.error(f"データ取得エラー: {e}")

    # ==========================================
    # TAB 3: 業務担当
    # ==========================================
    with tab3:
        st.subheader("🚚 業務担当：承認済みデータの転記・処理")

    # ==========================================
    # TAB 4: メンテナンスチェック画面
    # ==========================================
    with tab4:
        st.subheader("✅ メンテナンスチェック画面")

    # ==========================================
    # TAB 5: 加盟店別 印刷プレビュー画面 ＋ gspread自動転写・PDFダウンロード連携
    # ==========================================
    with tab5:
        st.subheader("🖨️ 加盟店別 印刷プレビュー & PDF発行")
        st.caption("加盟店を選択してボタンを押すと、データを自動転写してGoogleスプレッドシートから直接PDFを生成・ダウンロードできます。")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                store_col_idx = 4
                df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                stores = df_print["_store_name"].unique()

                selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="print_store_select_v2")

                if selected_store:
                    store_df = df_print[df_print["_store_name"] == selected_store]
                    total_records = len(store_df)

                    st.info(f"🏪 加盟店: **{selected_store}** （対象データ件数: {total_records} 件）")

                    if st.button(f"📥 「{selected_store}」のデータをシートに転写してPDFダウンロード", type="primary", key="btn_gspread_pdf_export"):
                        with st.spinner("スプレッドシートへ転写し、PDFを生成中..."):
                            pdf_bytes = transfer_and_export_pdf_for_store(selected_store, store_df)
                            if pdf_bytes:
                                st.download_button(
                                    label=f"⬇️ {selected_store}_印刷用出力.pdf をダウンロード",
                                    data=pdf_bytes,
                                    file_name=f"{selected_store}_print_output.pdf",
                                    mime="application/pdf",
                                    key="download_pdf_final_file"
                                )
                                st.success("PDFの準備が完了しました！上のボタンからダウンロードしてください。")

                    st.write("---")
                    st.write("👁️ **画面プレビュー確認**")

                    chunk_size = 3
                    chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                    for page_idx, chunk in enumerate(chunks):
                        c1_val = f"{selected_store} 様"

                        html_output = f"""
                        <div class="print-sheet">
                            <div style="font-size: 14px; font-weight: bold; border-bottom: 2px solid #333; padding-bottom: 5px; margin-bottom: 10px; display: flex; justify-content: space-between;">
                                <span>[C1] 当て先: {c1_val}</span>
                                <span style="font-size: 12px; color: #555;">ページ: {page_idx + 1} / {len(chunks)}</span>
                            </div>
                        """

                        for sub_i, (_, r_row) in enumerate(chunk.iterrows()):
                            store_code = str(r_row.iloc[5]) if len(r_row) > 5 and pd.notna(r_row.iloc[5]) else ""
                            raw_cname = str(r_row.iloc[3]) if len(r_row) > 3 and pd.notna(r_row.iloc[3]) else ""
                            cust_name = f"{raw_cname} 様" if raw_cname.strip() else ""
                            manager = str(r_row.iloc[30]) if len(r_row) > 30 and pd.notna(r_row.iloc[30]) else "未確認"
                            operator = str(r_row.iloc[32]) if len(r_row) > 32 and pd.notna(r_row.iloc[32]) else st.session_state["user_name"]
                            
                            cust_code = str(r_row.iloc[2]) if len(r_row) > 2 and pd.notna(r_row.iloc[2]) else ""
                            applicant = str(r_row.iloc[1]) if len(r_row) > 1 and pd.notna(r_row.iloc[1]) else ""
                            delivery_person = str(r_row.iloc[8]) if len(r_row) > 8 and pd.notna(r_row.iloc[8]) else ""
                            delivery_date = str(r_row.iloc[6]) if len(r_row) > 6 and pd.notna(r_row.iloc[6]) else ""
                            route_code = str(r_row.iloc[7]) if len(r_row) > 7 and pd.notna(r_row.iloc[7]) else ""
                            special_note = str(r_row.iloc[29]) if len(r_row) > 29 and pd.notna(r_row.iloc[29]) else "特記事項なし"

                            items_data = []
                            for pi in range(5):
                                b_idx = 9 + (pi * 4)
                                p_code = str(r_row.iloc[b_idx]) if b_idx < len(r_row) and pd.notna(r_row.iloc[b_idx]) else ""
                                if p_code.strip():
                                    p_qty = str(r_row.iloc[b_idx+1]) if b_idx+1 < len(r_row) and pd.notna(r_row.iloc[b_idx+1]) else ""
                                    p_price = str(r_row.iloc[b_idx+2]) if b_idx+2 < len(r_row) and pd.notna(r_row.iloc[b_idx+2]) else ""
                                    p_flg = str(r_row.iloc[b_idx+3]) if b_idx+3 < len(r_row) and pd.notna(r_row.iloc[b_idx+3]) else ""
                                    items_data.append((p_code, p_qty, p_price, p_flg))
                                else:
                                    items_data.append(("", "", "", ""))

                            it1 = items_data[0]
                            it2 = items_data[1]
                            it3 = items_data[2]
                            it4 = items_data[3]
                            it5 = items_data[4]

                            html_output += f"""
                            <div class="sheet-block">
                                <div class="block-title">📋 登録データ [{sub_i + 1}件目]</div>
                                <div class="grid-row">
                                    <div class="grid-cell"><span class="lbl">[A4] 加盟店コード</span><span class="val">{store_code}</span></div>
                                    <div class="grid-cell" style="grid-column: span 2;"><span class="lbl">[B4] 顧客名</span><span class="val">{cust_name}</span></div>
                                    <div class="grid-cell"><span class="lbl">[D4] 責任者</span><span class="val">{manager}</span></div>
                                    <div class="grid-cell"><span class="lbl">[E4] 処理者</span><span class="val">{operator}</span></div>
                                </div>
                                <div class="grid-row">
                                    <div class="grid-cell"><span class="lbl">[A6] 商品記号1</span><span class="val">{it1[0]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[B6] 発注数</span><span class="val">{it1[1]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[C6] 単価</span><span class="val">{it1[2]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[D6] 伝票出力</span><span class="val">{it1[3]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[E6] 顧客コード</span><span class="val">{cust_code}</span></div>
                                </div>
                                <div class="grid-row">
                                    <div class="grid-cell"><span class="lbl">[A8] 商品記号2</span><span class="val">{it2[0]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[B8] 発注数</span><span class="val">{it2[1]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[C8] 単価</span><span class="val">{it2[2]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[D8] 伝票出力</span><span class="val">{it2[3]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[E8] 申請者</span><span class="val">{applicant}</span></div>
                                </div>
                                <div class="grid-row">
                                    <div class="grid-cell"><span class="lbl">[A10] 商品記号3</span><span class="val">{it3[0]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[B10] 発注数</span><span class="val">{it3[1]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[C10] 単価</span><span class="val">{it3[2]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[D10] 伝票出力</span><span class="val">{it3[3]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[E10] 納品者</span><span class="val">{delivery_person}</span></div>
                                </div>
                                <div class="grid-row">
                                    <div class="grid-cell"><span class="lbl">[A12] 商品記号4</span><span class="val">{it4[0]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[B12] 発注数</span><span class="val">{it4[1]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[C12] 単価</span><span class="val">{it4[2]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[D12] 伝票出力</span><span class="val">{it4[3]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[E12] 納品日</span><span class="val">{delivery_date}</span></div>
                                </div>
                                <div class="grid-row">
                                    <div class="grid-cell"><span class="lbl">[A14] 商品記号5</span><span class="val">{it5[0]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[B14] 発注数</span><span class="val">{it5[1]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[C14] 単価</span><span class="val">{it5[2]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[D14] 伝票出力</span><span class="val">{it5[3]}</span></div>
                                    <div class="grid-cell"><span class="lbl">[E14] ルートコード</span><span class="val">{route_code}</span></div>
                                </div>
                                <div class="memo-cell">
                                    <span class="lbl">[A16] 特記事項</span>
                                    <div>{special_note}</div>
                                </div>
                            </div>
                            """

                        html_output += "</div>"
                        st.markdown(html_output, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"印刷データの読み込みエラー: {e}")
