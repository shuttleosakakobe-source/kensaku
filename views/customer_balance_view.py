"""「客中残訂正」モード（申請・承認・業務転記・チェックの4タブ。印刷プレビューは今回無し）。
顧客検索は他モードと同じ。商品記号は契約内容変更モードと同じ「ご契約データ」からの
一覧を再利用しつつ、プルダウンに無い商品記号も直接入力できるようにしている
（契約内容変更の「変更後」商品記号ピッカーと同じ accept_new_options 方式）。
単価・周期・契約数などの自動抽出は行わず、行ごとに「現在の客中残」「変更後の客中残」を
そのまま手入力する。これを5商品分（商品①〜⑤）並べ、その後に理由・連絡担当者様・特記事項を入力する。"""
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
from views.contract_view import get_contract_products, _cc_product_labels


# ==========================================
# 「客中残訂正」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
KZ_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=1426054920#gid=1426054920"
KZ_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=1426054920"
# TAB3・TAB4用（転記〜チェック）
KZ_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=311903417#gid=311903417"
KZ_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=311903417"

# 客中残訂正：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G〜 商品①〜⑤（1商品あたり3列＝商品記号/現在の客中残/変更後の客中残。下のKZ_ITEM_FIELDS順）,
# （その後）理由, 連絡担当者様, 特記事項, サイン(ステータス/承認者名), 日時(承認日時), コメント(承認コメント/差戻し理由),
# 処理日, 処理者, チェック日, チェック者, 印刷済
KZ_ITEM_FIELDS = ["code", "current_balance", "new_balance"]
KZ_ITEM_COUNT = 5
KZ_ITEMS_START_COL = 6  # G列（0始まり）から商品①の「商品記号」が始まる
KZ_ITEMS_END_COL = KZ_ITEMS_START_COL + KZ_ITEM_COUNT * len(KZ_ITEM_FIELDS)  # 商品ブロックの直後の列

KZ_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "reason": KZ_ITEMS_END_COL,
    "contact_person": KZ_ITEMS_END_COL + 1,
    "comment": KZ_ITEMS_END_COL + 2,
    "status_sign": KZ_ITEMS_END_COL + 3,
    "approval_time": KZ_ITEMS_END_COL + 4,
    "approval_comment": KZ_ITEMS_END_COL + 5,
    "process_time": KZ_ITEMS_END_COL + 6,
    "process_user": KZ_ITEMS_END_COL + 7,
    "check_time": KZ_ITEMS_END_COL + 8,
    "check_user": KZ_ITEMS_END_COL + 9,
    "print_time": KZ_ITEMS_END_COL + 10,
}

# 「客中残訂正」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
KZ_PRINT_SHEET_GID = "1068328164"
KZ_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={KZ_PRINT_SHEET_GID}#gid={KZ_PRINT_SHEET_GID}"
# 1ページに3件まで配置。各件の起点行（A列、店名/顧客名/責任者/処理者の行）：1件目=4, 2件目=19, 3件目=34
# （実テンプレートをクリックして確認：ブロックの高さは15行で均一）
KZ_PRINT_BASE_ROWS = [4, 19, 34]


def kz_item_col(item_idx, field):
    """item_idx: 0〜4（商品①〜⑤）, field: KZ_ITEM_FIELDSのいずれか。列インデックス（0始まり）を返す"""
    return KZ_ITEMS_START_COL + item_idx * len(KZ_ITEM_FIELDS) + KZ_ITEM_FIELDS.index(field)


def kz_extract_items(row):
    """行データから、5商品分（商品①〜⑤）のフィールドを辞書のリストとして取り出す"""
    items = []
    for n in range(KZ_ITEM_COUNT):
        d = {}
        for f in KZ_ITEM_FIELDS:
            idx = kz_item_col(n, f)
            d[f] = str(row.iloc[idx]) if len(row) > idx and pd.notna(row.iloc[idx]) else ""
        items.append(d)
    return items


def kz_items_display_df(items):
    """5商品分のitems（kz_extract_itemsの戻り値）から、表示用のDataFrameを作る。
    商品記号が空の行（未入力スロット）は表示しない"""
    rows = []
    for n, d in enumerate(items):
        if not d["code"].strip():
            continue
        rows.append({
            "商品": f"{n + 1}",
            "商品記号": d["code"],
            "現在の客中残": d["current_balance"], "変更後の客中残": d["new_balance"],
        })
    return pd.DataFrame(rows)


def kz_render_items_readonly(items, key_prefix):
    """5商品分のitems（kz_extract_itemsの戻り値）を読み取り専用フォームで表示する
    （TAB2〜4の確認画面用）。商品記号が空の行（未入力スロット）は表示しない"""
    any_shown = False
    for n, d in enumerate(items):
        if not d["code"].strip():
            continue
        any_shown = True
        st.markdown(f"**商品 {n + 1}**")

        row1 = st.columns(3)
        row1[0].text_input("商品記号", value=d["code"], disabled=True, key=f"{key_prefix}_code_{n}")
        row1[1].text_input("現在の客中残", value=d["current_balance"], disabled=True, key=f"{key_prefix}_cur_{n}")
        row1[2].text_input("変更後の客中残", value=d["new_balance"], disabled=True, key=f"{key_prefix}_new_{n}")

        st.write("---")
    if not any_shown:
        st.caption("商品情報が入力されていません。")


def render_customer_balance_correction_tabs():
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

    st.header("🧾 客中残訂正申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "kz_form_clear_key" not in st.session_state:
        st.session_state["kz_form_clear_key"] = 0

    rclear = f"_{st.session_state['kz_form_clear_key']}"

    for _key, _default in [
        (f"kz_ccode{rclear}", ""), (f"kz_cname{rclear}", ""),
        (f"kz_scode{rclear}", ""), (f"kz_sname{rclear}", ""),
        (f"kz_products{rclear}", []),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    if "kz_searched_ccode" not in st.session_state:
        st.session_state["kz_searched_ccode"] = ""

    k_tab1, k_tab2, k_tab3, k_tab4, k_tab5 = st.tabs([
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    def _tab1_body():
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["kz_searched_ccode"],
                key=f"kz_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"kz_search_btn{rclear}")

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
                            st.session_state["kz_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"kz_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"kz_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"kz_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"kz_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            st.session_state[f"kz_products{rclear}"] = get_contract_products(cust_code_input)

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
            customer_code = row1_col1.text_input("顧客コード", key=f"kz_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"kz_cname{rclear}")
            store_name = row1_col3.text_input("加盟店名", key=f"kz_sname{rclear}")

            row1b_col1, row1b_col2 = st.columns(2)
            store_code = row1b_col1.text_input("加盟店コード", key=f"kz_scode{rclear}")
            applicant = row1b_col2.text_input("担当者", value=st.session_state["user_name"], key=f"kz_app{rclear}")

            products = st.session_state[f"kz_products{rclear}"]
            product_labels = _cc_product_labels(products)

            st.write("---")

            items_data = []

            for n in range(KZ_ITEM_COUNT):
                st.markdown(f"**商品 {n + 1}**")

                # ---- 商品記号はプルダウンから選ぶだけでなく、無い商品記号を直接入力することもできる
                # （契約内容変更の「変更後」商品記号ピッカーと同じ accept_new_options 方式）。
                # 単価・周期などの自動抽出は行わず、「現在の客中残」「変更後の客中残」は手入力。 ----
                row1 = st.columns(3)

                pick = row1[0].selectbox(
                    "商品記号",
                    list(range(len(products))),
                    index=None,
                    accept_new_options=True,
                    format_func=lambda i: product_labels[i] if isinstance(i, int) else str(i),
                    placeholder="選択 or 入力",
                    key=f"kz_code_{n}{rclear}",
                )
                item_code = products[pick]["code"] if isinstance(pick, int) else (pick or "")
                item_current = row1[1].text_input("現在の客中残", key=f"kz_cur_{n}{rclear}")
                item_new = row1[2].text_input("変更後の客中残", key=f"kz_new_{n}{rclear}")

                items_data.append({
                    "code": item_code, "current_balance": item_current, "new_balance": item_new,
                })

                st.write("---")

            with st.form("kz_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                kz_reason = st.text_input("理由", key=f"kz_reason{rclear}")
                kz_contact = st.text_input("連絡担当者様", key=f"kz_contact{rclear}")
                kz_comment = st.text_area("特記事項", key=f"kz_comment{rclear}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip():
                        st.error("⚠️ 「顧客コード」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [now_str, applicant, customer_code, customer_name, store_name, store_code]
                        for item in items_data:
                            for f in KZ_ITEM_FIELDS:
                                full_row.append(item[f])
                        full_row += [kz_reason, kz_contact, kz_comment, "申請中", "", ""]

                        payload = {
                            "action": "SUBMIT_CUSTOMER_BALANCE_CHANGE",
                            "target_sheet_url": KZ_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["kz_searched_ccode"] = ""
                            st.session_state["kz_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(KZ_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > KZ_COL["status_sign"]:
                rejected_df = df[df.iloc[:, KZ_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = KZ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")
                        items = kz_extract_items(row)

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            st.write("**現在の内容**")
                            df_items = kz_items_display_df(items)
                            if not df_items.empty:
                                st.dataframe(df_items, use_container_width=True, hide_index=True)

                            with st.form(key=f"kz_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"kz_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"kz_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"kz_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"kz_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"kz_re_app_{row_id}")

                                st.caption("商品内容は上の表の内容がそのまま再申請されます。商品自体を修正したい場合は新規申請からやり直してください。")

                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"kz_re_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"kz_re_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"kz_re_comment_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip():
                                        st.error("⚠️ 「顧客コード」は必須項目です。")
                                    else:
                                        item_values = []
                                        for item in items:
                                            for f in KZ_ITEM_FIELDS:
                                                item_values.append(item[f])

                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code
                                        ] + item_values + [
                                            edit_reason, edit_contact, edit_comment, "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_CUSTOMER_BALANCE_CHANGE",
                                            "target_sheet_url": KZ_TARGET_SHEET_URL,
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
    with k_tab1:
        if tab_visible(1):
            _tab1_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab2_body():
        st.subheader("🔍 管理職チェック")
        try:
            st.cache_data.clear()
            df = pd.read_csv(KZ_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > KZ_COL["status_sign"]:
                pending_df = df[df.iloc[:, KZ_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = KZ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        items = kz_extract_items(row)

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            kz_render_items_readonly(items, key_prefix=f"kz_m_view_{row_id}")

                            with st.form(key=f"kz_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"kz_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"kz_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"kz_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"kz_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"kz_m_app_{row_id}")

                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"kz_m_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"kz_m_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"kz_m_comment_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"kz_mgr_com_{row_id}")

                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認（変更内容を反映）", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    item_values = []
                                    for item in items:
                                        for f in KZ_ITEM_FIELDS:
                                            item_values.append(item[f])

                                    updated_row = [
                                        _v("timestamp"), edit_app, edit_ccode, edit_cname,
                                        edit_sname, edit_scode
                                    ] + item_values + [edit_reason, edit_contact, edit_comment]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_CUSTOMER_BALANCE_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_CUSTOMER_BALANCE_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_CUSTOMER_BALANCE_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": KZ_TARGET_SHEET_URL,
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
    with k_tab2:
        if tab_visible(2):
            _tab2_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab3_body():
        st.subheader("🚚 業務担当メンテナンス処理")
        try:
            st.cache_data.clear()
            df = pd.read_csv(KZ_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= KZ_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, KZ_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, KZ_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = KZ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")
                        items = kz_extract_items(row)

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"kz_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"kz_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"kz_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"kz_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"kz_v_app_{row_id}")

                            kz_render_items_readonly(items, key_prefix=f"kz_v_view_{row_id}")

                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            if reason_val.strip() or contact_val.strip() or comment_val.strip():
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"kz_v_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"kz_v_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"kz_v_comment_{row_id}")

                            st.write("---")
                            with st.form(key=f"kz_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"kz_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(KZ_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_CUSTOMER_BALANCE_TO_OPERATOR",
                                        "target_sheet_url": KZ_TARGET_SHEET_URL,
                                        "dest_sheet_url": KZ_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": KZ_COL["status_sign"] + 1,
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
                                            for i in range(KZ_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_CUSTOMER_BALANCE_CHANGE",
                                            "target_sheet_url": KZ_TARGET_SHEET_URL,
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
    with k_tab3:
        if tab_visible(3):
            _tab3_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab4_body():
        st.subheader("✅ メンテナンスチェック画面")

        try:
            st.cache_data.clear()
            df_dest = pd.read_csv(KZ_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="kz_chk_show_checked")

                if not show_checked and len(df_dest.columns) > KZ_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, KZ_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = KZ_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")
                    items = kz_extract_items(row)

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"kz_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"kz_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"kz_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"kz_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"kz_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"kz_chk_app_{row_id}")

                            kz_render_items_readonly(items, key_prefix=f"kz_chk_view_{row_id}")

                            c6, c7 = st.columns(2)
                            c6.text_input("処理者", value=op_user_val, disabled=True, key=f"kz_chk_op_{row_id}")
                            c7.text_input("承認者", value=mgr_name_val, disabled=True, key=f"kz_chk_mgr_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            if reason_val.strip() or contact_val.strip() or comment_val.strip():
                                st.write("---")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"kz_chk_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"kz_chk_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"kz_chk_comment_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"kz_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"kz_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < KZ_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[KZ_COL["check_time"]] = check_time
                                clean_base_row[KZ_COL["check_user"]] = checker_name
                                # ※ print_time列（印刷済）はここでは触らない。既存の値を保持する。

                                payload = {
                                    "action": "UPDATE_CUSTOMER_BALANCE_CHECK",
                                    "target_sheet_url": KZ_DEST_SHEET_URL,
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
    # TAB 5: 加盟店別 印刷プレビュー
    # ==========================================
    with k_tab4:
        if tab_visible(4):
            _tab4_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
    def _tab5_body():
        st.subheader("🖨️ 加盟店別 印刷")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(KZ_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > KZ_COL["check_time"]:
                    checked_mask = df_print.iloc[:, KZ_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > KZ_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, KZ_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = KZ_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="kz_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(KZ_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_kz_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = KZ_COL[col_key]
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
                                "applicant": _f("applicant"), "cust_code": _f("cust_code"),
                                "reason": _f("reason"),
                                "comment": _f("comment") or "特記事項なし",
                                "contact_disp": contact_disp,
                                "items": kz_extract_items(r_row),
                            }

                        def kz_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            A/B/D/E(+0)=加盟店コード/顧客名(結合B:C)/責任者確認/処理者,
                            A/B/C(+2)=商品①記号/変更前客中残/変更後客中残, D/E(+2)=担当者名/シャトルコード,
                            A/B/C(+4)=商品②記号/変更前客中残/変更後客中残, D(+4、D:E結合で+4〜+8まで縦結合)=理由,
                            A/B/C(+6)=商品③記号/変更前客中残/変更後客中残,
                            A/B/C(+8)=商品④記号/変更前客中残/変更後客中残,
                            A/B/C(+10)=商品⑤記号/変更前客中残/変更後客中残, D(+10、D:E結合)=連絡担当者様,
                            A(+11、A:E結合)=特記事項"""
                            empty_items = [{"code": "", "current_balance": "", "new_balance": ""} for _ in range(KZ_ITEM_COUNT)]
                            if not rec:
                                rec = {
                                    "store_code": "", "cust_name": "", "manager": "", "operator": "",
                                    "applicant": "", "cust_code": "", "reason": "", "comment": "",
                                    "contact_disp": "", "items": empty_items,
                                }

                            cells = [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 2, "value": rec["cust_name"]},
                                {"offset": 0, "col": 4, "value": rec["manager"]},
                                {"offset": 0, "col": 5, "value": rec["operator"]},
                                {"offset": 2, "col": 4, "value": rec["applicant"]},
                                {"offset": 2, "col": 5, "value": rec["cust_code"]},
                                {"offset": 4, "col": 4, "value": rec["reason"]},
                                {"offset": 10, "col": 4, "value": rec["contact_disp"]},
                                {"offset": 11, "col": 1, "value": rec["comment"]},
                            ]
                            item_offsets = [2, 4, 6, 8, 10]
                            for n, item in enumerate(rec["items"]):
                                off = item_offsets[n]
                                cells.append({"offset": off, "col": 1, "value": item["code"]})
                                cells.append({"offset": off, "col": 2, "value": item["current_balance"]})
                                cells.append({"offset": off, "col": 3, "value": item["new_balance"]})
                            return cells

                        chunk_size = len(KZ_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(KZ_PRINT_BASE_ROWS):
                                rec = build_kz_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": kz_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    st.caption(f"担当者名: {rec['applicant']} ｜ シャトルコード: {rec['cust_code']}")
                                    df_items = kz_items_display_df(rec["items"])
                                    if not df_items.empty:
                                        st.dataframe(df_items, use_container_width=True, hide_index=True)
                                    st.caption(f"理由: {rec['reason']} ｜ 連絡担当者様: {rec['contact_disp']}")
                                    st.caption(f"特記事項: {rec['comment']}")

                            if st.button("📥 反映してPDFを作成する", key=f"kz_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": KZ_PRINT_SHEET_URL,
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
                                        "target_sheet_url": KZ_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": KZ_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = KZ_PRINT_BASE_ROWS[len(chunk) - 1] + 11 if len(chunk) > 0 else 15
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, gid=KZ_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_kz_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"kz_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({KZ_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                            )
                                    except Exception as pdf_e:
                                        st.warning(f"PDF作成中にエラーが発生しました: {pdf_e}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"反映に失敗しました: {res.get('message')}")

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
    with k_tab5:
        if tab_visible(5):
            _tab5_body()
        else:
            st.info(RESTRICTED_TAB_MSG)
