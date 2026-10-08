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
    post_to_gas, build_print_pdf_url, read_csv_cached,
    tab_visible, RESTRICTED_TAB_MSG, send_staff_comment, render_section_pending_banner,
    render_tab_header_pending_css, handle_tab4_reject,
    render_tab2_own_approvals_section, render_tab2_notifications_section, render_tab3_own_transfers_section,
    render_internal_note, render_tab4_own_checks_section, is_already_transferred,
    render_duplicate_transfer_guard, render_tab5_own_prints_section,
)
from views.contract_view import get_contract_products, _cc_product_labels

KZ_MODE_NAME = "客中残訂正"


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
    # 💡 rejector_name・reject_dateは「差戻し一覧」用に、差戻し修正(TAB1)・管理職チェック(TAB2)
    # だけがTARGET_SHEET側で使う列（process_time・process_userと同じ列番号だが、あちらは
    # 転記後のDEST_SHEET側の列として使われるため実際には衝突しない）。
    "rejector_name": KZ_ITEMS_END_COL + 6, "reject_date": KZ_ITEMS_END_COL + 7,
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

    def _tab6_body():
        st.subheader("🔍 過去の申請検索")
        st.caption("承認・処理が完了した過去の申請データを検索できます。")

        _col6 = KZ_COL

        col_f1, col_f2, col_f3 = st.columns(3)
        f_cust_code = col_f1.text_input("顧客コード", key="k_tab_search_cust_code")
        f_applicant = col_f2.text_input("担当者名", key="k_tab_search_applicant")
        f_date_type = col_f3.selectbox("期間の基準日", ["申請日", "処理日"], key="k_tab_search_date_type")

        col_d1, col_d2 = st.columns(2)
        f_date_from = col_d1.date_input("開始日", value=None, key="k_tab_search_date_from")
        f_date_to = col_d2.date_input("終了日", value=None, key="k_tab_search_date_to")

        if st.button("🔍 検索する", key="k_tab_search_btn"):
            try:
                read_csv_cached.clear()
                df_search = read_csv_cached(KZ_DEST_SHEET_CSV)
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
                            st.write("**📋 申請内容**")

                            s6_c1, s6_c2, s6_c3 = st.columns(3)
                            s6_c1.text_input("顧客コード", value=cust_code_v, disabled=True, key=f"s6_ccode_{idx}")
                            s6_c2.text_input("顧客名", value=cust_name_v, disabled=True, key=f"s6_cname_{idx}")
                            s6_c3.text_input("加盟店コード", value=_val(_col6.get("store_code")), disabled=True, key=f"s6_scode_{idx}")

                            s6_d1, s6_d2, s6_d3 = st.columns(3)
                            s6_d1.text_input("加盟店名", value=store_name_v, disabled=True, key=f"s6_sname_{idx}")
                            s6_d2.text_input("申請者名", value=applicant_v, disabled=True, key=f"s6_app_{idx}")
                            s6_d3.text_input("承認者", value=_val(_col6.get("status_sign")), disabled=True, key=f"s6_mgr_{idx}")

                            st.write("---")
                            st.write("**📦 商品①〜⑤（商品記号／現在の客中残／変更後の客中残）**")
                            for s6_i in range(KZ_ITEM_COUNT):
                                s6_code = _val(kz_item_col(s6_i, "code"))
                                if s6_code.strip():
                                    s6_f1, s6_f2, s6_f3 = st.columns(3)
                                    s6_f1.text_input(f"商品記号 {s6_i+1}", value=s6_code, disabled=True, key=f"s6_p_{idx}_{s6_i}")
                                    s6_f2.text_input(f"現在の客中残 {s6_i+1}", value=_val(kz_item_col(s6_i, "current_balance")), disabled=True, key=f"s6_cur_{idx}_{s6_i}")
                                    s6_f3.text_input(f"変更後の客中残 {s6_i+1}", value=_val(kz_item_col(s6_i, "new_balance")), disabled=True, key=f"s6_new_{idx}_{s6_i}")

                            st.text_input("理由", value=_val(_col6.get("reason")), disabled=True, key=f"s6_reason_{idx}")
                            st.text_input("連絡担当者様", value=_val(_col6.get("contact_person")), disabled=True, key=f"s6_contact_{idx}")
                            s6_com = _val(_col6.get("comment"))
                            if s6_com.strip():
                                st.text_area("特記事項", value=s6_com, disabled=True, key=f"s6_com_{idx}")

                            st.write("---")
                            st.write(f"**処理日時：** {process_time_v}　**処理者：** {_val(_col6.get('process_user'))}")

    _k_tab_all_labels = [
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 加盟店別 印刷",
        "🔍 過去の申請検索",
    ]
    _k_tab_visible_nums = [_n for _n in range(1, 7) if tab_visible(_n)]
    if not _k_tab_visible_nums:
        st.info(RESTRICTED_TAB_MSG)
        _tab_map = {}
    else:
        render_tab_header_pending_css(
            KZ_TARGET_SHEET_CSV, KZ_DEST_SHEET_CSV,
            KZ_COL["status_sign"], KZ_COL["check_time"], KZ_COL["print_time"],
            _k_tab_visible_nums,
        )
        _k_tab_objs = st.tabs([_k_tab_all_labels[_n - 1] for _n in _k_tab_visible_nums])
        _tab_map = dict(zip(_k_tab_visible_nums, _k_tab_objs))

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
                        df_master = read_csv_cached(
                            CUSTOMER_MASTER_CSV,
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

                # ---- 商品記号はプルダウンから選ぶだけでなく、一覧に無い商品記号を直接入力する
                # こともできる。以前はaccept_new_options方式（プルダウンと入力欄が一体化した
                # もの）だったが、スマホ・タブレットで文字入力ができない不具合があったため、
                # 通常のプルダウン＋別枠の手入力テキスト欄に分離した（手入力時はそちらを優先）。
                # 単価・周期などの自動抽出は行わず、「現在の客中残」「変更後の客中残」は手入力。 ----
                row1 = st.columns(3)

                pick = row1[0].selectbox(
                    "商品記号", [None] + list(range(len(products))),
                    format_func=lambda i: "" if i is None else product_labels[i],
                    key=f"kz_code_{n}{rclear}",
                )
                item_code_manual = st.text_input(
                    "商品記号（一覧に無い場合はここに直接入力。入力時はこちらが優先されます）",
                    key=f"kz_code_manual_{n}{rclear}",
                )
                item_code = item_code_manual.strip() or (
                    products[pick]["code"] if isinstance(pick, int) else ""
                )
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
            df = read_csv_cached(KZ_TARGET_SHEET_CSV)
            if not df.empty and len(df.columns) > KZ_COL["status_sign"]:
                # 💡 差戻し一覧は「自分が申請したもの」だけに絞る。以前は絞り込みが無く、
                # 他のスタッフが申請して差し戻された案件まで全員の画面に出てしまい、
                # 本人以外が気づいて触ってしまう不具合があった。
                _current_user = str(st.session_state.get("user_name", "")).strip()
                rejected_df = df[
                    (df.iloc[:, KZ_COL["status_sign"]].astype(str).str.strip() == "差戻し") &
                    (df.iloc[:, KZ_COL["applicant"]].astype(str).str.strip() == _current_user)
                ]
                render_section_pending_banner("差戻し", len(rejected_df))
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = KZ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")
                        rejector_name = _v("rejector_name")
                        reject_date = _v("reject_date") or _v("approval_time")
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
                                btn_withdraw = st.form_submit_button("🗑️ 削除（この申請を取り下げる）")

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
                                            edit_reason, edit_contact, edit_comment,
                                            "申請中", "", "", rejector_name, reject_date,
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_CUSTOMER_BALANCE_CHANGE",
                                            "target_sheet_url": KZ_TARGET_SHEET_URL,
                                            "row_index": row_id,
                                            "updated_row": updated_row
                                        }
                                        res = post_to_gas(payload)
                                        if res.get("status") == "success":
                                            if rejector_name:
                                                send_staff_comment(
                                                    "客中残訂正", edit_cust_code, edit_cust_name, rejector_name,
                                                    "差戻しを修正し、再申請しました。",
                                                    st.session_state.get("user_name", ""),
                                                )
                                            st.toast("再申請が完了しました！")
                                            time.sleep(1)
                                            st.rerun()
                                        else:
                                            st.error(f"処理に失敗しました: {res.get('message')}")

                                elif btn_withdraw:
                                    item_values = []
                                    for item in items:
                                        for f in KZ_ITEM_FIELDS:
                                            item_values.append(item[f])
                                    withdrawn_row = [
                                        _v("timestamp"), _v("applicant"), _v("cust_code"), _v("cust_name"),
                                        _v("store_name"), _v("store_code")
                                    ] + item_values + [
                                        _v("reason"), _v("contact_person"), _v("comment"),
                                        "削除", datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S"), "",
                                        rejector_name, reject_date,
                                    ]

                                    payload = {
                                        "action": "DELETE_CUSTOMER_BALANCE_CHANGE",
                                        "target_sheet_url": KZ_TARGET_SHEET_URL,
                                        "row_index": row_id,
                                        "updated_row": withdrawn_row,
                                    }
                                    res = post_to_gas(payload)
                                    if res.get("status") == "success":
                                        if rejector_name:
                                            send_staff_comment(
                                                "客中残訂正", _v("cust_code"), _v("cust_name"), rejector_name,
                                                "差し戻された申請を削除（取り下げ）しました。",
                                                st.session_state.get("user_name", ""),
                                            )
                                        st.toast("削除しました。")
                                        time.sleep(1)
                                        st.rerun()
                                    else:
                                        st.error(f"削除に失敗しました: {res.get('message')}")
            else:
                st.info("現在、差戻しデータはありません。")
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
        render_tab2_notifications_section(KZ_MODE_NAME)
        render_tab2_own_approvals_section(
            KZ_MODE_NAME, KZ_COL, KZ_TARGET_SHEET_CSV, KZ_TARGET_SHEET_URL, "RESUBMIT_CUSTOMER_BALANCE_CHANGE",
        )
        try:
            df = read_csv_cached(KZ_TARGET_SHEET_CSV)
            if not df.empty and len(df.columns) > KZ_COL["status_sign"]:
                pending_df = df[df.iloc[:, KZ_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                render_section_pending_banner("承認待ち", len(pending_df))
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
                                        updated_row.extend([mgr_name, now_str, mgr_comment, "", ""])
                                    elif btn_reject:
                                        action_type = "REJECT_CUSTOMER_BALANCE_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment, mgr_name, now_str])
                                    elif btn_delete:
                                        action_type = "DELETE_CUSTOMER_BALANCE_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment, "", ""])

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
            else:
                st.info("現在、未承認の申請はありません。")
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
        render_tab3_own_transfers_section(
            KZ_MODE_NAME, KZ_COL, KZ_DEST_SHEET_CSV, KZ_TARGET_SHEET_CSV,
            KZ_TARGET_SHEET_URL, KZ_DEST_SHEET_URL,
            "APPROVE_CUSTOMER_BALANCE_CHANGE", "REJECT_CUSTOMER_BALANCE_CHANGE", "UPDATE_CUSTOMER_BALANCE_CHECK",
        )
        try:
            df = read_csv_cached(KZ_TARGET_SHEET_CSV)

            if df.empty or len(df.columns) <= KZ_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, KZ_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, KZ_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]
                render_section_pending_banner("メンテナンス処理", len(approved_df))

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 未承認のデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = KZ_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")
                        items = kz_extract_items(row)

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            render_internal_note(_v("approval_comment"))
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

                            render_duplicate_transfer_guard(
                                f"kz_dup_pending_{row_id}", row, row_id, KZ_COL,
                                KZ_TARGET_SHEET_URL, "APPROVE_CUSTOMER_BALANCE_CHANGE",
                            )

                            with st.form(key=f"kz_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                staff_comment_val = st.text_area(
                                    "💬 申請者への連絡コメント（任意・差戻しにはなりません）", key=f"kz_staff_comment_{row_id}",
                                    placeholder="転記時に申請者へ伝えたい連絡事項があれば入力してください",
                                )
                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"kz_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    # 💡 二重クリックや複数人の同時操作で同じ申請がDEST_SHEETに
                                    #    重複登録されるのを防ぐ（印刷時に同じ顧客が複数スロットに
                                    #    表示される不具合の原因だった）。転記直前に最新状態を読み直す。
                                    read_csv_cached.clear()
                                    if is_already_transferred(KZ_DEST_SHEET_CSV, KZ_COL, _v("cust_code"), _v("timestamp")):
                                        st.session_state[f"kz_dup_pending_{row_id}"] = True
                                        st.rerun()
                                    else:
                                        clean_base_row = [
                                            "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                            for i in range(KZ_COL["status_sign"] + 3)
                                        ]
                                        if staff_comment_val.strip():
                                            _note = f"【業務担当】{staff_comment_val.strip()}"
                                            _orig_note = clean_base_row[KZ_COL["approval_comment"]]
                                            clean_base_row[KZ_COL["approval_comment"]] = (
                                                f"{_orig_note}\n{_note}" if _orig_note.strip() else _note
                                            )
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
                                                read_csv_cached.clear()
                                                if staff_comment_val.strip():
                                                    send_staff_comment(
                                                        mode_name="客中残訂正",
                                                        cust_code=_v("cust_code"), cust_name=_v("cust_name"),
                                                        applicant=_v("applicant"),
                                                        comment=staff_comment_val,
                                                        staff_name=op_user,
                                                        extra_recipient=mgr_name,
                                                    )
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
                                            read_csv_cached.clear()
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
        render_tab4_own_checks_section(
            KZ_MODE_NAME, KZ_COL, KZ_DEST_SHEET_CSV, KZ_DEST_SHEET_URL, "UPDATE_CUSTOMER_BALANCE_CHECK",
        )

        try:
            df_dest = read_csv_cached(KZ_DEST_SHEET_CSV)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                if len(df_dest.columns) > KZ_COL["check_time"]:
                    _unchecked_count = int((df_dest.iloc[:, KZ_COL["check_time"]].fillna("").astype(str).str.strip() == "").sum())
                else:
                    _unchecked_count = 0
                render_section_pending_banner("メンテナンスチェック", _unchecked_count)

                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="kz_chk_show_checked")

                if not show_checked and len(df_dest.columns) > KZ_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, KZ_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                col_sort1, col_sort2 = st.columns([3, 1])
                sort_store = col_sort1.checkbox("🏪 加盟店別（店舗名）で並び替える", value=False, key="kz_chk_sort_store")
                sort_order = col_sort2.selectbox("並び順", ["昇順 (あ〜わ)", "降順 (わ〜あ)"], index=0, key="kz_chk_sort_order", label_visibility="collapsed")

                df_display = df_dest.copy()
                if sort_store:
                    store_col_idx = KZ_COL["store_name"]
                    if len(df_display.columns) > store_col_idx:
                        is_ascending = (sort_order == "昇順 (あ〜わ)")
                        df_display["_sort_store"] = df_display.iloc[:, store_col_idx].fillna("")
                        df_display = df_display.sort_values(by="_sort_store", ascending=is_ascending)

                for idx, row in df_display.iterrows():
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
                        render_internal_note(_v("approval_comment"))
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
                                    read_csv_cached.clear()
                                    st.toast(f"行 {row_id} のメンテナンスチェックを完了しました！", icon="✅")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"更新失敗: {res.get('message')}")

                            elif btn_checked_reject:
                                if not reject_reason.strip():
                                    st.error("⚠️ 差戻しを行う場合は「差戻し理由」を入力してください。")
                                else:
                                    ok, msg = handle_tab4_reject(
                                        row, row_id, reject_target, reject_reason,
                                        st.session_state["user_name"],
                                        KZ_COL, KZ_TARGET_SHEET_CSV, KZ_TARGET_SHEET_URL, KZ_DEST_SHEET_URL,
                                        "APPROVE_CUSTOMER_BALANCE_CHANGE", "REJECT_CUSTOMER_BALANCE_CHANGE", "UPDATE_CUSTOMER_BALANCE_CHECK",
                                        KZ_MODE_NAME,
                                    )
                                    if ok:
                                        read_csv_cached.clear()
                                        st.toast(msg, icon="↩️")
                                        time.sleep(1.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)

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
        render_tab5_own_prints_section(KZ_MODE_NAME, KZ_COL, KZ_DEST_SHEET_CSV, KZ_DEST_SHEET_URL, "UPDATE_CUSTOMER_BALANCE_CHECK")

        try:
            df_print = read_csv_cached(KZ_DEST_SHEET_CSV)

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

                render_section_pending_banner("印刷", len(df_print))

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

                            # 💡「反映」と「印刷済みにする」を別ボタンに分離し、実際に印刷（またはPDF保存）
                            #    したことをユーザー自身に確認してもらってから印刷済みマークを付ける
                            #    （以前は反映と同時に印刷済みマークを付けていたため、PDFのダウンロードに
                            #    失敗した場合や実際には印刷していない場合でも一覧から消えてしまっていた）。
                            pending_key = f"kz_print_pending_{selected_store}_{page_idx}"

                            if pending_key not in st.session_state:
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
                                        st.session_state[pending_key] = {
                                            "row_ids": page_row_ids,
                                            "print_time": datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S"),
                                        }
                                        st.rerun()
                                    else:
                                        st.error(f"反映に失敗しました: {res.get('message')}")
                            else:
                                st.success("✅ 印刷用スプレッドシートへの反映が完了しています。")
                                try:
                                    pdf_row_end = KZ_PRINT_BASE_ROWS[len(chunk) - 1] + 11 if len(chunk) > 0 else 15
                                    with st.spinner("PDFを作成しています..."):
                                        pdf_res = requests.get(
                                            build_print_pdf_url(row_end=pdf_row_end, gid=KZ_PRINT_SHEET_GID),
                                            timeout=30
                                        )
                                    content_type = pdf_res.headers.get("Content-Type", "")
                                    if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                        st.download_button(
                                            "📄 PDFをダウンロード",
                                            data=pdf_res.content,
                                            file_name=f"{selected_store}_kz_p{page_idx + 1}.pdf",
                                            mime="application/pdf",
                                            key=f"kz_pdf_dl_{page_idx}",
                                        )
                                    else:
                                        st.warning(
                                            "アプリ上でのPDF取得に失敗しました（共有設定などが原因の可能性があります）。"
                                            f"[印刷用スプレッドシートを開く]({KZ_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                        )
                                except Exception as pdf_e:
                                    st.warning(f"PDF作成中にエラーが発生しました: {pdf_e}")

                                st.info("🖨️ 印刷（またはPDF保存）が終わったら、下のボタンでこの一覧から消してください。")
                                col_done, col_cancel = st.columns(2)
                                if col_done.button("✅ 印刷済みにする（一覧から消す）", key=f"kz_print_done_btn_{page_idx}", type="primary"):
                                    pending = st.session_state[pending_key]
                                    mark_res = post_to_gas({
                                        "action": "MARK_PRINTED",
                                        "target_sheet_url": KZ_DEST_SHEET_URL,
                                        "row_indices": pending["row_ids"],
                                        "print_time": pending["print_time"],
                                        "print_col": KZ_COL["print_time"] + 1,
                                    })
                                    if mark_res.get("status") == "success":
                                        del st.session_state[pending_key]
                                        read_csv_cached.clear()
                                        st.rerun()
                                    else:
                                        st.error(f"印刷済みマークの更新に失敗しました: {mark_res.get('message')}")
                                if col_cancel.button("↩️ まだ印刷していない（反映をやり直す）", key=f"kz_print_cancel_btn_{page_idx}"):
                                    del st.session_state[pending_key]
                                    st.rerun()

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
    if 5 in _tab_map:
        with _tab_map[5]:
            _tab5_body()
    if 6 in _tab_map:
        with _tab_map[6]:
            _tab6_body()
