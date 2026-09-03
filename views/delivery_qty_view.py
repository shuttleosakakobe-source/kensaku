"""「納品数量変更」モード（申請・承認・業務転記・チェックの4タブ。印刷プレビューは後日追加予定）。
顧客検索や画面の流れは他モードと同じ。商品情報（商品記号・単価・契約数）は
契約内容変更モードと同じ「ご契約データ」からの抽出方法を再利用し（get_contract_products等）、
変更前・変更後の2系統ではなく、抽出した商品情報の横に「変更数」を1つ入力する形にしている。
契約数はA〜D週の内訳ではなく、契約内容変更の「契約数」と同じ考え方（0以外の納品数を採用）で
1つにまとめた数値として表示する（周期は表示しない）。これを5商品分（商品①〜⑤）並べ、その後に
納品日・理由・特記事項・連絡担当者様を入力する。"""
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
from views.contract_view import (
    get_contract_products, _cc_product_labels, _cc_hide_zero, _cc_sum4,
)


# ==========================================
# 「納品数量変更」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
DQ_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=683944837#gid=683944837"
DQ_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=683944837"
# TAB3・TAB4用（転記〜チェック）
DQ_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1651430066#gid=1651430066"
DQ_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=1651430066"

# 納品数量変更：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G〜 商品①〜⑤（1商品あたり4列＝商品記号/単価/契約数/変更数。下のDQ_ITEM_FIELDS順）,
# （その後）納品ルート, 納品日, 理由, 特記事項, 連絡担当者様, サイン(ステータス/承認者名), 日時(承認日時), コメント(承認コメント/差戻し理由),
# 処理日, 処理者, チェック日, チェック者, 印刷済
# 💡 「納品ルート」列は印刷テンプレート対応のため追加。Googleスプレッドシート側（TAB1・2用シート／
#    TAB3・4用シート）にも、商品ブロックの直後・「納品日」列の直前に「納品ルート」列を挿入すること。
DQ_ITEM_FIELDS = ["code", "price", "count", "change_qty"]
DQ_ITEM_COUNT = 5
DQ_ITEMS_START_COL = 6  # G列（0始まり）から商品①の「商品記号」が始まる
DQ_ITEMS_END_COL = DQ_ITEMS_START_COL + DQ_ITEM_COUNT * len(DQ_ITEM_FIELDS)  # 商品ブロックの直後の列

DQ_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "route": DQ_ITEMS_END_COL,
    "delivery_date": DQ_ITEMS_END_COL + 1,
    "reason": DQ_ITEMS_END_COL + 2,
    "comment": DQ_ITEMS_END_COL + 3,
    "contact_person": DQ_ITEMS_END_COL + 4,
    "status_sign": DQ_ITEMS_END_COL + 5,
    "approval_time": DQ_ITEMS_END_COL + 6,
    "approval_comment": DQ_ITEMS_END_COL + 7,
    "process_time": DQ_ITEMS_END_COL + 8,
    "process_user": DQ_ITEMS_END_COL + 9,
    "check_time": DQ_ITEMS_END_COL + 10,
    "check_user": DQ_ITEMS_END_COL + 11,
    "print_time": DQ_ITEMS_END_COL + 12,
}

# 「納品数量変更」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
DQ_PRINT_SHEET_GID = "765708679"
DQ_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={DQ_PRINT_SHEET_GID}#gid={DQ_PRINT_SHEET_GID}"
# 1ページに3件まで配置。各件の起点行（A列、店名/顧客名/責任者/処理者の行）：1件目=4, 2件目=21, 3件目=38
# （実テンプレートをクリックして確認：ブロックの高さは17行で均一）
DQ_PRINT_BASE_ROWS = [4, 21, 38]


def dq_item_col(item_idx, field):
    """item_idx: 0〜4（商品①〜⑤）, field: DQ_ITEM_FIELDSのいずれか。列インデックス（0始まり）を返す"""
    return DQ_ITEMS_START_COL + item_idx * len(DQ_ITEM_FIELDS) + DQ_ITEM_FIELDS.index(field)


def dq_extract_items(row):
    """行データから、5商品分（商品①〜⑤）のフィールドを辞書のリストとして取り出す"""
    items = []
    for n in range(DQ_ITEM_COUNT):
        d = {}
        for f in DQ_ITEM_FIELDS:
            idx = dq_item_col(n, f)
            d[f] = str(row.iloc[idx]) if len(row) > idx and pd.notna(row.iloc[idx]) else ""
        items.append(d)
    return items


def dq_items_display_df(items):
    """5商品分のitems（dq_extract_itemsの戻り値）から、表示用のDataFrameを作る。
    商品記号が空の行（未入力スロット）は表示しない"""
    rows = []
    for n, d in enumerate(items):
        if not d["code"].strip():
            continue
        rows.append({
            "商品": f"{n + 1}",
            "商品記号": d["code"], "単価": d["price"],
            "契約数": d["count"], "変更数": d["change_qty"],
        })
    return pd.DataFrame(rows)


def dq_render_items_readonly(items, key_prefix):
    """5商品分のitems（dq_extract_itemsの戻り値）を読み取り専用フォームで表示する
    （TAB2〜4の確認画面用）。商品記号が空の行（未入力スロット）は表示しない"""
    any_shown = False
    for n, d in enumerate(items):
        if not d["code"].strip():
            continue
        any_shown = True
        st.markdown(f"**商品 {n + 1}**")

        row1 = st.columns(4)
        row1[0].text_input("商品記号", value=d["code"], disabled=True, key=f"{key_prefix}_code_{n}")
        row1[1].text_input("契約数", value=d["count"], disabled=True, key=f"{key_prefix}_count_{n}")
        row1[2].text_input("単価", value=d["price"], disabled=True, key=f"{key_prefix}_price_{n}")
        row1[3].text_input("変更数", value=d["change_qty"], disabled=True, key=f"{key_prefix}_chgqty_{n}")

        st.write("---")
    if not any_shown:
        st.caption("商品情報が入力されていません。")


def render_delivery_qty_change_tabs():
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

    st.header("🔢 納品数量変更申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "dq_form_clear_key" not in st.session_state:
        st.session_state["dq_form_clear_key"] = 0

    rclear = f"_{st.session_state['dq_form_clear_key']}"

    for _key, _default in [
        (f"dq_ccode{rclear}", ""), (f"dq_cname{rclear}", ""),
        (f"dq_scode{rclear}", ""), (f"dq_sname{rclear}", ""),
        (f"dq_products{rclear}", []),
        (f"dq_past_results{rclear}", None),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    for _n in range(DQ_ITEM_COUNT):
        for _suf in ["price", "count"]:
            _key = f"dq_{_suf}_{_n}{rclear}"
            if _key not in st.session_state:
                st.session_state[_key] = ""

    if "dq_searched_ccode" not in st.session_state:
        st.session_state["dq_searched_ccode"] = ""

    def _tab6_body():
        st.subheader("🔍 過去の申請検索")
        st.caption("承認・処理が完了した過去の申請データを検索できます。")

        _col6 = DQ_COL

        col_f1, col_f2, col_f3 = st.columns(3)
        f_cust_code = col_f1.text_input("顧客コード", key="d_tab_search_cust_code")
        f_applicant = col_f2.text_input("担当者名", key="d_tab_search_applicant")
        f_date_type = col_f3.selectbox("期間の基準日", ["申請日", "処理日"], key="d_tab_search_date_type")

        col_d1, col_d2 = st.columns(2)
        f_date_from = col_d1.date_input("開始日", value=None, key="d_tab_search_date_from")
        f_date_to = col_d2.date_input("終了日", value=None, key="d_tab_search_date_to")

        if st.button("🔍 検索する", key="d_tab_search_btn"):
            try:
                st.cache_data.clear()
                df_search = pd.read_csv(DQ_DEST_SHEET_CSV, dtype=str)
            except Exception as e:
                st.error(f"データ取得エラー: {e}")
                df_search = pd.DataFrame()

            if df_search.empty:
                st.info("対象データがありません。")
            else:
                mask = pd.Series(True, index=df_search.index)
                idx_cust_code = _col6.get("cust_code")
                idx_applicant = _col6.get("applicant")
                idx_timestamp = _col6.get("timestamp")
                idx_process_time = _col6.get("process_time")
                idx_cust_name = _col6.get("cust_name")
                idx_store_name = _col6.get("store_name")

                if f_cust_code and idx_cust_code is not None and len(df_search.columns) > idx_cust_code:
                    mask &= df_search.iloc[:, idx_cust_code].fillna("").astype(str).str.strip() == str(f_cust_code).strip()

                if f_applicant and idx_applicant is not None and len(df_search.columns) > idx_applicant:
                    mask &= df_search.iloc[:, idx_applicant].fillna("").astype(str).str.contains(str(f_applicant).strip(), na=False)

                date_col_idx = idx_timestamp if f_date_type == "申請日" else idx_process_time
                if (f_date_from or f_date_to) and date_col_idx is not None and len(df_search.columns) > date_col_idx:
                    parsed_dates = pd.to_datetime(df_search.iloc[:, date_col_idx], errors="coerce")
                    if f_date_from:
                        mask &= parsed_dates >= pd.Timestamp(f_date_from)
                    if f_date_to:
                        mask &= parsed_dates <= (pd.Timestamp(f_date_to) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))

                result_df = df_search[mask]

                if result_df.empty:
                    st.info("条件に一致するデータは見つかりませんでした。")
                else:
                    st.success(f"📋 検索結果: **{len(result_df)} 件**")
                    for idx, row in result_df.iterrows():
                        def _val(col_idx):
                            if col_idx is None or len(row) <= col_idx or pd.isna(row.iloc[col_idx]):
                                return ""
                            return str(row.iloc[col_idx])

                        cust_code_v = _val(idx_cust_code)
                        cust_name_v = _val(idx_cust_name)
                        store_name_v = _val(idx_store_name)
                        applicant_v = _val(idx_applicant)
                        timestamp_v = _val(idx_timestamp)
                        process_time_v = _val(idx_process_time)

                        expander_label = f"📌 【{store_name_v or '未設定'}】 {cust_name_v}（{cust_code_v}） | 申請日: {timestamp_v}"
                        with st.expander(expander_label):
                            st.write(f"**担当者名：** {applicant_v}")
                            st.write(f"**処理日時：** {process_time_v}")
                            st.dataframe(row.to_frame().T, use_container_width=True, hide_index=True)

    _d_tab_all_labels = [
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
        "🔍 過去の申請検索",
    ]
    _d_tab_visible_nums = [_n for _n in range(1, 7) if tab_visible(_n)]
    if not _d_tab_visible_nums:
        st.info(RESTRICTED_TAB_MSG)
        _tab_map = {}
    else:
        _d_tab_objs = st.tabs([_d_tab_all_labels[_n - 1] for _n in _d_tab_visible_nums])
        _tab_map = dict(zip(_d_tab_visible_nums, _d_tab_objs))

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    def _tab1_body():
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["dq_searched_ccode"],
                key=f"dq_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"dq_search_btn{rclear}")

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
                            st.session_state["dq_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"dq_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"dq_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"dq_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"dq_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            st.session_state[f"dq_products{rclear}"] = get_contract_products(cust_code_input)

                            st.toast("顧客情報を取得しました！", icon="✅")
                            time.sleep(0.3)
                            st.rerun()
                        else:
                            st.warning("該当する顧客データが見つかりませんでした。")
                    except Exception as e:
                        st.error(f"マスタ参照エラー: {e}")
                else:
                    st.warning("顧客コードを入力してください。")

            with st.expander("🕘 過去の申請から選ぶ（顧客情報・商品情報を反映）", expanded=False):
                st.caption("過去に送った申請を検索し、顧客情報・商品情報をこのフォームに反映できます（納品ルート・納品日は反映されません。改めて入力してください）。")
                col_p1, col_p2 = st.columns([4, 1])
                past_ccode_input = col_p1.text_input(
                    "顧客コードで検索", key=f"dq_past_ccode_search{rclear}"
                )
                btn_past_search = col_p2.button(
                    "🔍 検索", use_container_width=True, key=f"dq_past_search_btn{rclear}"
                )

                if btn_past_search:
                    if past_ccode_input:
                        try:
                            st.cache_data.clear()
                            df_past = pd.read_csv(DQ_DEST_SHEET_CSV, dtype=str)
                            idx_cc = DQ_COL["cust_code"]
                            if not df_past.empty and len(df_past.columns) > idx_cc:
                                st.session_state[f"dq_past_results{rclear}"] = df_past[
                                    df_past.iloc[:, idx_cc].fillna("").astype(str).str.strip() == str(past_ccode_input).strip()
                                ]
                            else:
                                st.session_state[f"dq_past_results{rclear}"] = df_past.iloc[0:0]
                        except Exception as e:
                            st.error(f"データ取得エラー: {e}")
                            st.session_state[f"dq_past_results{rclear}"] = None
                    else:
                        st.warning("顧客コードを入力してください。")

                past_results = st.session_state.get(f"dq_past_results{rclear}")
                if past_results is not None:
                    if past_results.empty:
                        st.info("該当する過去の申請データが見つかりませんでした。")
                    else:
                        idx_ts = DQ_COL["timestamp"]
                        idx_cc = DQ_COL["cust_code"]
                        idx_cn = DQ_COL["cust_name"]
                        idx_sn = DQ_COL["store_name"]
                        idx_sc = DQ_COL["store_code"]

                        def _pv(r, idx):
                            return str(r.iloc[idx]) if len(r) > idx and pd.notna(r.iloc[idx]) else ""

                        for p_idx, p_row in past_results.iloc[::-1].iterrows():
                            p_ts = _pv(p_row, idx_ts)
                            p_items = dq_extract_items(p_row)

                            with st.expander(f"📄 申請日: {p_ts}　|　{_pv(p_row, idx_cn)}（{_pv(p_row, idx_cc)}）"):
                                r1, r2, r3 = st.columns(3)
                                r1.text_input("顧客コード", value=_pv(p_row, idx_cc), disabled=True, key=f"dq_past_view_ccode_{p_idx}{rclear}")
                                r2.text_input("顧客名", value=_pv(p_row, idx_cn), disabled=True, key=f"dq_past_view_cname_{p_idx}{rclear}")
                                r3.text_input("加盟店名", value=_pv(p_row, idx_sn), disabled=True, key=f"dq_past_view_sname_{p_idx}{rclear}")

                                dq_render_items_readonly(p_items, key_prefix=f"dq_past_view_{p_idx}{rclear}")

                                if st.button("🔄 この内容をフォームに反映", key=f"dq_past_apply_{p_idx}{rclear}"):
                                    cc_val = _pv(p_row, idx_cc)
                                    st.session_state[f"dq_ccode{rclear}"] = cc_val
                                    st.session_state[f"dq_cname{rclear}"] = _pv(p_row, idx_cn)
                                    st.session_state[f"dq_sname{rclear}"] = _pv(p_row, idx_sn)
                                    st.session_state[f"dq_scode{rclear}"] = _pv(p_row, idx_sc)

                                    fresh_products = get_contract_products(cc_val)
                                    st.session_state[f"dq_products{rclear}"] = fresh_products

                                    for n, it in enumerate(p_items):
                                        if n >= DQ_ITEM_COUNT:
                                            break
                                        code = it["code"].strip()
                                        if not code:
                                            st.session_state[f"dq_code_{n}{rclear}"] = None
                                            st.session_state[f"dq_price_{n}{rclear}"] = ""
                                            st.session_state[f"dq_count_{n}{rclear}"] = ""
                                            st.session_state[f"dq_change_qty_{n}{rclear}"] = ""
                                            continue
                                        match_idx = next(
                                            (i for i, prod in enumerate(fresh_products) if prod.get("code") == code),
                                            None
                                        )
                                        if match_idx is not None:
                                            st.session_state[f"dq_code_{n}{rclear}"] = match_idx
                                            st.session_state[f"dq_price_{n}{rclear}"] = _cc_hide_zero(fresh_products[match_idx]["price"])
                                            st.session_state[f"dq_count_{n}{rclear}"] = _cc_sum4(
                                                fresh_products[match_idx]["week_a"], fresh_products[match_idx]["week_b"],
                                                fresh_products[match_idx]["week_c"], fresh_products[match_idx]["week_d"]
                                            )
                                        else:
                                            # 現在のご契約データに同じ商品記号が見つからない場合
                                            # （契約内容が変わった等）は、選択は空にし、当時の値を
                                            # 参考としてそのまま表示する。
                                            st.session_state[f"dq_code_{n}{rclear}"] = None
                                            st.session_state[f"dq_price_{n}{rclear}"] = it["price"]
                                            st.session_state[f"dq_count_{n}{rclear}"] = it["count"]
                                        st.session_state[f"dq_change_qty_{n}{rclear}"] = it["change_qty"]

                                    st.toast("過去の申請内容をフォームに反映しました（納品ルート・納品日は未入力です）", icon="✅")
                                    time.sleep(0.3)
                                    st.rerun()

            st.write("---")
            st.write("**📋 入力情報**")

            row1_col1, row1_col2, row1_col3 = st.columns(3)
            customer_code = row1_col1.text_input("顧客コード", key=f"dq_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"dq_cname{rclear}")
            store_name = row1_col3.text_input("加盟店名", key=f"dq_sname{rclear}")

            row1b_col1, row1b_col2 = st.columns(2)
            store_code = row1b_col1.text_input("加盟店コード", key=f"dq_scode{rclear}")
            applicant = row1b_col2.text_input("担当者", value=st.session_state["user_name"], key=f"dq_app{rclear}")

            products = st.session_state[f"dq_products{rclear}"]
            product_labels = _cc_product_labels(products)

            st.write("---")

            items_data = []

            for n in range(DQ_ITEM_COUNT):
                st.markdown(f"**商品 {n + 1}**")

                def _make_pick_cb(_n=n, _rclear=rclear):
                    def _cb():
                        _products = st.session_state.get(f"dq_products{_rclear}", [])
                        _idx = st.session_state.get(f"dq_code_{_n}{_rclear}")
                        _match = _products[_idx] if isinstance(_idx, int) and 0 <= _idx < len(_products) else None
                        if _match:
                            st.session_state[f"dq_price_{_n}{_rclear}"] = _cc_hide_zero(_match["price"])
                            st.session_state[f"dq_count_{_n}{_rclear}"] = _cc_sum4(
                                _match["week_a"], _match["week_b"], _match["week_c"], _match["week_d"]
                            )
                        else:
                            st.session_state[f"dq_price_{_n}{_rclear}"] = ""
                            st.session_state[f"dq_count_{_n}{_rclear}"] = ""
                    return _cb

                # ---- 商品記号を選ぶと契約数（A〜D週のうち0以外の納品数）・単価が自動表示
                # （契約内容変更と同じ抽出方法。週ごとの内訳や周期は表示せず契約数1つにまとめる）。
                # その横（同じ行）に「変更数」の入力欄を追加。 ----
                row1 = st.columns(4)

                pick_idx = row1[0].selectbox(
                    "商品記号", [None] + list(range(len(products))),
                    format_func=lambda i: "" if i is None else product_labels[i],
                    key=f"dq_code_{n}{rclear}", on_change=_make_pick_cb(),
                )
                item_code = products[pick_idx]["code"] if isinstance(pick_idx, int) else ""
                item_count = row1[1].text_input("契約数", key=f"dq_count_{n}{rclear}", disabled=True)
                item_price = row1[2].text_input("単価", key=f"dq_price_{n}{rclear}", disabled=True)
                item_change_qty = row1[3].text_input("変更数", key=f"dq_change_qty_{n}{rclear}")

                items_data.append({
                    "code": item_code, "price": item_price,
                    "count": item_count, "change_qty": item_change_qty,
                })

                st.write("---")

            with st.form("dq_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                dq_route = st.text_input("納品ルート", key=f"dq_route{rclear}")
                dq_delivery_date_val = st.date_input("納品日", value=None, key=f"dq_delivery_date{rclear}")
                dq_delivery_date = dq_delivery_date_val.strftime("%Y/%m/%d") if dq_delivery_date_val else ""
                dq_reason = st.text_input("理由", key=f"dq_reason{rclear}")
                dq_comment = st.text_area("特記事項", key=f"dq_comment{rclear}")
                dq_contact = st.text_input("連絡担当者様", key=f"dq_contact{rclear}")

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip():
                        st.error("⚠️ 「顧客コード」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [now_str, applicant, customer_code, customer_name, store_name, store_code]
                        for item in items_data:
                            for f in DQ_ITEM_FIELDS:
                                full_row.append(item[f])
                        full_row += [dq_route, dq_delivery_date, dq_reason, dq_comment, dq_contact, "申請中", "", ""]

                        payload = {
                            "action": "SUBMIT_DELIVERY_QTY_CHANGE",
                            "target_sheet_url": DQ_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["dq_searched_ccode"] = ""
                            st.session_state["dq_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(DQ_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > DQ_COL["status_sign"]:
                rejected_df = df[df.iloc[:, DQ_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = DQ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")
                        items = dq_extract_items(row)

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            st.write("**現在の内容**")
                            df_items = dq_items_display_df(items)
                            if not df_items.empty:
                                st.dataframe(df_items, use_container_width=True, hide_index=True)

                            with st.form(key=f"dq_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"dq_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"dq_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"dq_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"dq_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"dq_re_app_{row_id}")

                                st.caption("商品内容は上の表の内容がそのまま再申請されます。商品自体を修正したい場合は新規申請からやり直してください。")

                                edit_route = st.text_input("納品ルート", value=_v("route"), key=f"dq_re_route_{row_id}")
                                edit_delivery_date = st.text_input("納品日", value=_v("delivery_date"), key=f"dq_re_delivery_date_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"dq_re_reason_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"dq_re_comment_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"dq_re_contact_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip():
                                        st.error("⚠️ 「顧客コード」は必須項目です。")
                                    else:
                                        item_values = []
                                        for item in items:
                                            for f in DQ_ITEM_FIELDS:
                                                item_values.append(item[f])

                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code
                                        ] + item_values + [
                                            edit_route, edit_delivery_date, edit_reason, edit_comment, edit_contact, "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_DELIVERY_QTY_CHANGE",
                                            "target_sheet_url": DQ_TARGET_SHEET_URL,
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
            df = pd.read_csv(DQ_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > DQ_COL["status_sign"]:
                pending_df = df[df.iloc[:, DQ_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = DQ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        items = dq_extract_items(row)

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            dq_render_items_readonly(items, key_prefix=f"dq_m_view_{row_id}")

                            with st.form(key=f"dq_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"dq_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"dq_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"dq_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"dq_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"dq_m_app_{row_id}")

                                edit_route = st.text_input("納品ルート", value=_v("route"), key=f"dq_m_route_{row_id}")
                                edit_delivery_date = st.text_input("納品日", value=_v("delivery_date"), key=f"dq_m_delivery_date_{row_id}")
                                edit_reason = st.text_input("理由", value=_v("reason"), key=f"dq_m_reason_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"dq_m_comment_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"dq_m_contact_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"dq_mgr_com_{row_id}")

                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認（変更内容を反映）", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    item_values = []
                                    for item in items:
                                        for f in DQ_ITEM_FIELDS:
                                            item_values.append(item[f])

                                    updated_row = [
                                        _v("timestamp"), edit_app, edit_ccode, edit_cname,
                                        edit_sname, edit_scode
                                    ] + item_values + [edit_route, edit_delivery_date, edit_reason, edit_comment, edit_contact]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_DELIVERY_QTY_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_DELIVERY_QTY_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_DELIVERY_QTY_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": DQ_TARGET_SHEET_URL,
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
            df = pd.read_csv(DQ_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= DQ_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, DQ_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, DQ_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = DQ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")
                        items = dq_extract_items(row)

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"dq_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"dq_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"dq_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"dq_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"dq_v_app_{row_id}")

                            dq_render_items_readonly(items, key_prefix=f"dq_v_view_{row_id}")

                            route_val = _v("route")
                            delivery_date_val = _v("delivery_date")
                            reason_val = _v("reason")
                            comment_val = _v("comment")
                            contact_val = _v("contact_person")
                            if route_val.strip() or delivery_date_val.strip() or reason_val.strip() or comment_val.strip() or contact_val.strip():
                                if route_val.strip():
                                    st.text_input("納品ルート", value=route_val, disabled=True, key=f"dq_v_route_{row_id}")
                                if delivery_date_val.strip():
                                    st.text_input("納品日", value=delivery_date_val, disabled=True, key=f"dq_v_delivery_date_{row_id}")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"dq_v_reason_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"dq_v_comment_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"dq_v_contact_{row_id}")

                            st.write("---")
                            with st.form(key=f"dq_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"dq_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(DQ_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_DELIVERY_QTY_TO_OPERATOR",
                                        "target_sheet_url": DQ_TARGET_SHEET_URL,
                                        "dest_sheet_url": DQ_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": DQ_COL["status_sign"] + 1,
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
                                            for i in range(DQ_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_DELIVERY_QTY_CHANGE",
                                            "target_sheet_url": DQ_TARGET_SHEET_URL,
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
            df_dest = pd.read_csv(DQ_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="dq_chk_show_checked")

                if not show_checked and len(df_dest.columns) > DQ_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, DQ_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = DQ_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")
                    items = dq_extract_items(row)

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"dq_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"dq_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"dq_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"dq_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"dq_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"dq_chk_app_{row_id}")

                            dq_render_items_readonly(items, key_prefix=f"dq_chk_view_{row_id}")

                            c6, c7 = st.columns(2)
                            c6.text_input("処理者", value=op_user_val, disabled=True, key=f"dq_chk_op_{row_id}")
                            c7.text_input("承認者", value=mgr_name_val, disabled=True, key=f"dq_chk_mgr_{row_id}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            route_val = _v("route")
                            delivery_date_val = _v("delivery_date")
                            reason_val = _v("reason")
                            comment_val = _v("comment")
                            contact_val = _v("contact_person")
                            if route_val.strip() or delivery_date_val.strip() or reason_val.strip() or comment_val.strip() or contact_val.strip():
                                st.write("---")
                                if route_val.strip():
                                    st.text_input("納品ルート", value=route_val, disabled=True, key=f"dq_chk_route_{row_id}")
                                if delivery_date_val.strip():
                                    st.text_input("納品日", value=delivery_date_val, disabled=True, key=f"dq_chk_delivery_date_{row_id}")
                                if reason_val.strip():
                                    st.text_input("理由", value=reason_val, disabled=True, key=f"dq_chk_reason_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"dq_chk_comment_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"dq_chk_contact_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"dq_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"dq_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < DQ_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[DQ_COL["check_time"]] = check_time
                                clean_base_row[DQ_COL["check_user"]] = checker_name
                                # ※ print_time列（印刷済）はここでは触らない。既存の値を保持する。

                                payload = {
                                    "action": "UPDATE_DELIVERY_QTY_CHECK",
                                    "target_sheet_url": DQ_DEST_SHEET_URL,
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
    if 4 in _tab_map:
        with _tab_map[4]:
            _tab4_body()
    def _tab5_body():
        st.subheader("🖨️ 加盟店別 印刷")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(DQ_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > DQ_COL["check_time"]:
                    checked_mask = df_print.iloc[:, DQ_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > DQ_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, DQ_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = DQ_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="dq_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(DQ_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_dq_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = DQ_COL[col_key]
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
                                "route": _f("route"), "delivery_date": _f("delivery_date"),
                                "reason": _f("reason"),
                                "comment": _f("comment") or "特記事項なし",
                                "contact_disp": contact_disp,
                                "items": dq_extract_items(r_row),
                            }

                        def dq_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            A/B/D/E(+0)=加盟店コード/顧客名(結合B:C)/責任者確認/処理者,
                            A/B/C/D(+2)=商品①記号/変更前納品数(契約数)/単価/変更後納品数(変更数), E(+2)=シャトルコード,
                            A/B/C/D(+4)=商品②, E(+4)=発注者(担当者),
                            A/B/C/D(+6)=商品③, E(+6)=納品日,
                            A/B/C/D(+8)=商品④, E(+8)=納品ルート,
                            A/B/C/D(+10)=商品⑤, E(+10)=連絡担当者様,
                            A(+12、A:E結合)=理由, A(+14、A:E結合)=特記事項"""
                            empty_items = [{"code": "", "price": "", "count": "", "change_qty": ""} for _ in range(DQ_ITEM_COUNT)]
                            if not rec:
                                rec = {
                                    "store_code": "", "cust_name": "", "manager": "", "operator": "",
                                    "applicant": "", "cust_code": "", "route": "", "delivery_date": "",
                                    "reason": "", "comment": "", "contact_disp": "", "items": empty_items,
                                }

                            cells = [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 2, "value": rec["cust_name"]},
                                {"offset": 0, "col": 4, "value": rec["manager"]},
                                {"offset": 0, "col": 5, "value": rec["operator"]},
                                {"offset": 2, "col": 5, "value": rec["cust_code"]},
                                {"offset": 4, "col": 5, "value": rec["applicant"]},
                                {"offset": 6, "col": 5, "value": rec["delivery_date"]},
                                {"offset": 8, "col": 5, "value": rec["route"]},
                                {"offset": 10, "col": 5, "value": rec["contact_disp"]},
                                {"offset": 12, "col": 1, "value": rec["reason"]},
                                {"offset": 14, "col": 1, "value": rec["comment"]},
                            ]
                            item_offsets = [2, 4, 6, 8, 10]
                            for n, item in enumerate(rec["items"]):
                                off = item_offsets[n]
                                cells.append({"offset": off, "col": 1, "value": item["code"]})
                                cells.append({"offset": off, "col": 2, "value": item["count"]})
                                cells.append({"offset": off, "col": 3, "value": item["price"]})
                                cells.append({"offset": off, "col": 4, "value": item["change_qty"]})
                            return cells

                        chunk_size = len(DQ_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            c1_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(DQ_PRINT_BASE_ROWS):
                                rec = build_dq_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": dq_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ 責任者: {rec['manager']} ／ 処理者: {rec['operator']}**")
                                    st.caption(f"シャトルコード: {rec['cust_code']} ｜ 発注者: {rec['applicant']} ｜ 納品日: {rec['delivery_date']} ｜ 納品ルート: {rec['route']}")
                                    df_items = dq_items_display_df(rec["items"])
                                    if not df_items.empty:
                                        st.dataframe(df_items, use_container_width=True, hide_index=True)
                                    st.caption(f"理由: {rec['reason']} ｜ 連絡担当者様: {rec['contact_disp']}")
                                    st.caption(f"特記事項: {rec['comment']}")

                            if st.button("📥 反映してPDFを作成する", key=f"dq_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": DQ_PRINT_SHEET_URL,
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
                                        "target_sheet_url": DQ_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": DQ_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = DQ_PRINT_BASE_ROWS[len(chunk) - 1] + 14 if len(chunk) > 0 else 18
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, gid=DQ_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_dq_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"dq_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({DQ_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
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
    if 6 in _tab_map:
        with _tab_map[6]:
            _tab6_body()
