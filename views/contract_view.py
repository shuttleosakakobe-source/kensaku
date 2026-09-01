"""「契約内容変更」モード（申請・承認・業務転記・チェック・印刷の5タブ）。"""
import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import time

from views.maint_common import (
    JST, CUSTOMER_MASTER_CSV, PRINT_SHEET_ID,
    CONTRACT_COL_CUST_CODE, CONTRACT_WEEK_COLS,
    post_to_gas, build_print_pdf_url, _load_contract_df,
)


# 「契約内容変更」モードTAB5用：加盟店別 印刷フォーマットのスプレッドシート（同じブック内・別タブ）
CC_PRINT_SHEET_GID = "88627179"
CC_PRINT_SHEET_URL = f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/edit?gid={CC_PRINT_SHEET_GID}#gid={CC_PRINT_SHEET_GID}"
# 1ページに3件まで配置。各件の起点行（A列）：1件目=4, 2件目=18, 3件目=32
CC_PRINT_BASE_ROWS = [4, 18, 32]

# ==========================================
# 「契約内容変更」モード用シート
# ==========================================
# TAB1・TAB2用（申請〜承認）
CC_TARGET_SHEET_URL = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/edit?gid=40673825#gid=40673825"
CC_TARGET_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid=40673825"
# TAB3・TAB4用（転記〜チェック）
CC_DEST_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=1232708804#gid=1232708804"
CC_DEST_SHEET_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=1232708804"

# 契約内容変更：列インデックス（0始まり）
# A タイムスタンプ, B 担当者(申請者), C 顧客コード, D 顧客名, E 加盟店, F 加盟店コード,
# G〜 商品①〜⑤（1商品あたり14列＝変更前7列＋変更後7列。下のCC_ITEM_FIELDS順）,
# （その後）理由, 連絡担当者様, 特記事項, 増減金額, 次回訪問日, サイン(ステータス/承認者名), 日時(承認日時), コメント(承認コメント/差戻し理由),
# 処理日, 処理者, チェック日, チェック者, 印刷済
# ※特記事項列はTAB1/2シート・TAB3/4シートどちらにも「連絡担当者様」の直後・「増減金額」の直前に追加が必要
# ※次回訪問日列はTAB1/2シート・TAB3/4シートどちらにも「増減金額」の直後・「サイン」の直前（CC列）に追加が必要
CC_ITEM_FIELDS = [
    "before_code", "before_price", "before_cycle", "before_a", "before_b", "before_c", "before_d",
    "after_code", "after_price", "after_cycle", "after_a", "after_b", "after_c", "after_d",
]
CC_ITEM_COUNT = 5
CC_ITEMS_START_COL = 6  # G列（0始まり）から商品①の「変更前商品記号」が始まる
CC_ITEMS_END_COL = CC_ITEMS_START_COL + CC_ITEM_COUNT * len(CC_ITEM_FIELDS)  # 商品ブロックの直後の列

CC_COL = {
    "timestamp": 0, "applicant": 1, "cust_code": 2, "cust_name": 3,
    "store_name": 4, "store_code": 5,
    "reason": CC_ITEMS_END_COL,
    "contact_person": CC_ITEMS_END_COL + 1,
    "comment": CC_ITEMS_END_COL + 2,
    "amount_diff": CC_ITEMS_END_COL + 3,
    "next_visit": CC_ITEMS_END_COL + 4,
    "status_sign": CC_ITEMS_END_COL + 5,
    "approval_time": CC_ITEMS_END_COL + 6,
    "approval_comment": CC_ITEMS_END_COL + 7,
    "process_time": CC_ITEMS_END_COL + 8,
    "process_user": CC_ITEMS_END_COL + 9,
    "check_time": CC_ITEMS_END_COL + 10,
    "check_user": CC_ITEMS_END_COL + 11,
    "print_time": CC_ITEMS_END_COL + 12,
}


def cc_item_col(item_idx, field):
    """item_idx: 0〜4（商品①〜⑤）, field: CC_ITEM_FIELDSのいずれか。列インデックス（0始まり）を返す"""
    return CC_ITEMS_START_COL + item_idx * len(CC_ITEM_FIELDS) + CC_ITEM_FIELDS.index(field)


# ご契約データシートの列（契約内容変更用）：商品記号=K(10)、商品単価=I(8)、交換周期=L(11)
# A〜D週納品数はCONTRACT_WEEK_COLS(M/N/O/P=12/13/14/15)を共用
CONTRACT_COL_PRODUCT_CODE = 10
CONTRACT_COL_PRODUCT_PRICE = 8
CONTRACT_COL_PRODUCT_CYCLE = 11


def get_contract_products(cust_code):
    """ご契約データから、指定した顧客コードの商品一覧
    （商品記号・商品単価・交換周期・A〜D週納品数）を行ごとに返す（契約内容変更用）"""
    if not cust_code or not str(cust_code).strip():
        return []
    df_contract = _load_contract_df()
    if df_contract is None:
        return []

    matched = df_contract[
        df_contract.iloc[:, CONTRACT_COL_CUST_CODE].astype(str).str.strip() == str(cust_code).strip()
    ]
    if matched.empty:
        return []

    def _cell(r, idx):
        return str(r.iloc[idx]).strip() if idx < len(r) and pd.notna(r.iloc[idx]) else ""

    products = []
    for _, r in matched.iterrows():
        code = _cell(r, CONTRACT_COL_PRODUCT_CODE)
        if not code:
            continue
        products.append({
            "code": code,
            "price": _cell(r, CONTRACT_COL_PRODUCT_PRICE),
            "cycle": _cell(r, CONTRACT_COL_PRODUCT_CYCLE),
            "week_a": _cell(r, CONTRACT_WEEK_COLS[0]),
            "week_b": _cell(r, CONTRACT_WEEK_COLS[1]),
            "week_c": _cell(r, CONTRACT_WEEK_COLS[2]),
            "week_d": _cell(r, CONTRACT_WEEK_COLS[3]),
        })
    return products


def _cc_product_labels(products):
    """商品一覧（get_contract_productsの戻り値）から、プルダウン表示用のラベルを作る。
    同じ商品記号が複数行ある場合、記号だけだとプルダウン上で見分けがつかず
    （見た目が同じ選択肢が2つあると正しく選び分けられない）、
    単価・周期・A〜D週の内訳をカッコ書きで添えて区別できるようにする
    （商品記号が1件しかない場合は記号だけを表示する）"""
    code_counts = {}
    for p in products:
        code_counts[p["code"]] = code_counts.get(p["code"], 0) + 1

    labels = []
    for p in products:
        if code_counts[p["code"]] > 1:
            detail = (
                f"単価{p['price'] or '-'}"
                f"/周期{p['cycle'] or '-'}"
                f"/A{p['week_a'] or '-'}B{p['week_b'] or '-'}C{p['week_c'] or '-'}D{p['week_d'] or '-'}"
            )
            labels.append(f"{p['code']}（{detail}）")
        else:
            labels.append(p["code"])
    return labels




def _cc_format_yen(amount):
    """増減金額を表示用に整形する。マイナスの場合は「－」を付け、「1,234円」の形式にする
    （数値に変換できない場合は元の値をそのまま返す）"""
    if amount is None or str(amount).strip() == "":
        return ""
    try:
        val = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    sign = "-" if val < 0 else ""
    return f"{sign}{abs(val):,.0f}円"


def _cc_hide_zero(val):
    """数値が0（または0扱いの文字列）なら空文字にする。それ以外はそのまま返す（契約内容変更・変更前欄の自動表示用）"""
    if val is None:
        return ""
    s = str(val).strip()
    if s == "":
        return ""
    try:
        if float(s) == 0:
            return ""
    except ValueError:
        pass
    return s


def _cc_to_float(val):
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return 0.0


def _cc_nonzero_qty(week_a, week_b, week_c, week_d):
    """A〜D週の納品数のうち、0以外の納品数を「契約数」として採用する
    （A〜D週の合計ではなく、0以外に入っている納品数そのものを使う。
    同じ数量が複数曜日に入っている場合はその数量を、異なる数量が混在する場合はそれらを合計する）"""
    vals = [_cc_to_float(v) for v in (week_a, week_b, week_c, week_d)]
    nonzero = [v for v in vals if v != 0]
    if not nonzero:
        return 0.0
    return nonzero[0] if len(set(nonzero)) == 1 else sum(nonzero)


def calc_cc_amount(price, cycle, week_a, week_b, week_c, week_d):
    """契約数（A〜D週のうち0以外の納品数）×（4 ÷ 交換周期）× 商品単価 を計算する。
    交換周期が0または未入力の場合は0を返す（ゼロ除算回避）"""
    cycle_f = _cc_to_float(cycle)
    if cycle_f == 0:
        return 0.0
    qty = _cc_nonzero_qty(week_a, week_b, week_c, week_d)
    return qty * (4.0 / cycle_f) * _cc_to_float(price)


def _cc_sum4(week_a, week_b, week_c, week_d):
    """A〜D週のうち0以外の納品数を「契約数」として文字列で返す（整数ならそのまま、それ以外は元の値を保持）"""
    total = _cc_nonzero_qty(week_a, week_b, week_c, week_d)
    if total == 0:
        return ""
    return str(int(total)) if total == int(total) else str(total)


def cc_extract_items(row):
    """行データから、5商品分（商品①〜⑤）の変更前・変更後フィールドを辞書のリストとして取り出す"""
    items = []
    for n in range(CC_ITEM_COUNT):
        d = {}
        for f in CC_ITEM_FIELDS:
            idx = cc_item_col(n, f)
            d[f] = str(row.iloc[idx]) if len(row) > idx and pd.notna(row.iloc[idx]) else ""
        items.append(d)
    return items


def cc_items_display_df(items):
    """5商品分のitems（cc_extract_itemsの戻り値）から、表示用のDataFrameを作る。
    変更前・変更後どちらの商品記号も空の行（未入力スロット）は表示しない"""
    rows = []
    for n, d in enumerate(items):
        if not d["before_code"].strip() and not d["after_code"].strip():
            continue
        rows.append({
            "商品": f"{n + 1}",
            "変更前商品記号": d["before_code"], "変更前単価": d["before_price"], "変更前周期": d["before_cycle"],
            "変更前A週": d["before_a"], "変更前B週": d["before_b"], "変更前C週": d["before_c"], "変更前D週": d["before_d"],
            "変更後商品記号": d["after_code"], "変更後単価": d["after_price"], "変更後周期": d["after_cycle"],
            "変更後A週": d["after_a"], "変更後B週": d["after_b"], "変更後C週": d["after_c"], "変更後D週": d["after_d"],
        })
    return pd.DataFrame(rows)


def _cc_cycle_disp(val):
    """周期の表示用文字列。値があれば末尾に「W」を付ける（例: "2" → "2W"）。
    ※ 計算・保存用の値には使わず、あくまで画面表示専用"""
    s = str(val).strip() if val is not None else ""
    if not s:
        return ""
    return f"{s}W"


def cc_render_items_readonly(items, key_prefix):
    """5商品分のitems（cc_extract_itemsの戻り値）を、TAB1の新規申請フォームと同じ
    「🔵 変更前」「🟢 変更後」カード形式（読み取り専用）で表示する（TAB2〜4の確認画面用）。
    変更前・変更後どちらの商品記号も空の行（未入力スロット）は表示しない"""
    any_shown = False
    for n, d in enumerate(items):
        if not d["before_code"].strip() and not d["after_code"].strip():
            continue
        any_shown = True
        st.markdown(f"**商品 {n + 1}**")

        st.markdown("🔵 変更前")
        b_row1 = st.columns(4)
        b_row2 = st.columns(4)
        b_row1[0].text_input("商品記号", value=d["before_code"], disabled=True, key=f"{key_prefix}_b_code_{n}")
        before_count = _cc_sum4(d["before_a"], d["before_b"], d["before_c"], d["before_d"])
        b_row1[1].text_input("契約数", value=before_count, disabled=True, key=f"{key_prefix}_b_count_{n}")
        b_row1[2].text_input("単価", value=d["before_price"], disabled=True, key=f"{key_prefix}_b_price_{n}")
        b_row1[3].text_input("周期", value=_cc_cycle_disp(d["before_cycle"]), disabled=True, key=f"{key_prefix}_b_cycle_{n}")
        b_row2[0].text_input("A", value=d["before_a"], disabled=True, key=f"{key_prefix}_b_a_{n}")
        b_row2[1].text_input("B", value=d["before_b"], disabled=True, key=f"{key_prefix}_b_b_{n}")
        b_row2[2].text_input("C", value=d["before_c"], disabled=True, key=f"{key_prefix}_b_c_{n}")
        b_row2[3].text_input("D", value=d["before_d"], disabled=True, key=f"{key_prefix}_b_d_{n}")

        st.markdown("🟢 変更後")
        a_row1 = st.columns(4)
        a_row2 = st.columns(4)
        a_row1[0].text_input("商品記号", value=d["after_code"], disabled=True, key=f"{key_prefix}_a_code_{n}")
        after_count = _cc_sum4(d["after_a"], d["after_b"], d["after_c"], d["after_d"])
        a_row1[1].text_input("契約数", value=after_count, disabled=True, key=f"{key_prefix}_a_count_{n}")
        a_row1[2].text_input("単価", value=d["after_price"], disabled=True, key=f"{key_prefix}_a_price_{n}")
        a_row1[3].text_input("周期", value=_cc_cycle_disp(d["after_cycle"]), disabled=True, key=f"{key_prefix}_a_cycle_{n}")
        a_row2[0].text_input("A", value=d["after_a"], disabled=True, key=f"{key_prefix}_a_a_{n}")
        a_row2[1].text_input("B", value=d["after_b"], disabled=True, key=f"{key_prefix}_a_b_{n}")
        a_row2[2].text_input("C", value=d["after_c"], disabled=True, key=f"{key_prefix}_a_c_{n}")
        a_row2[3].text_input("D", value=d["after_d"], disabled=True, key=f"{key_prefix}_a_d_{n}")

        st.write("---")
    if not any_shown:
        st.caption("商品情報が入力されていません。")


def render_contract_change_tabs():
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
        div[data-testid="stWidgetLabel"], div[data-testid="stWidgetLabel"] p {
            opacity: 1 !important;
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

    st.header("📋 契約内容変更申請・承認・業務処理システム")

    if "user_name" not in st.session_state:
        st.session_state["user_name"] = "眞田 隆司"

    if "cc_form_clear_key" not in st.session_state:
        st.session_state["cc_form_clear_key"] = 0

    rclear = f"_{st.session_state['cc_form_clear_key']}"

    for _key, _default in [
        (f"cc_ccode{rclear}", ""), (f"cc_cname{rclear}", ""),
        (f"cc_scode{rclear}", ""), (f"cc_sname{rclear}", ""),
        (f"cc_products{rclear}", []),
    ]:
        if _key not in st.session_state:
            st.session_state[_key] = _default

    for _n in range(CC_ITEM_COUNT):
        for _suf in ["code", "price", "cycle", "a", "b", "c", "d"]:
            for _side in ["before", "after"]:
                _key = f"cc_{_side}_{_suf}_{_n}{rclear}"
                if _key not in st.session_state:
                    st.session_state[_key] = ""
        _pick_key = f"cc_after_pick_{_n}{rclear}"
        if _pick_key not in st.session_state:
            st.session_state[_pick_key] = ""

    if "cc_searched_ccode" not in st.session_state:
        st.session_state["cc_searched_ccode"] = ""

    c_tab1, c_tab2, c_tab3, c_tab4, c_tab5 = st.tabs([
        "📝 メンテナンス / 差戻し修正",
        "🔍 管理職チェック",
        "🚚 業務担当メンテナンス処理",
        "✅ メンテナンスチェック画面",
        "🖨️ 印刷プレビュー",
    ])

    # ==========================================
    # TAB 1: 申請・差戻し対応
    # ==========================================
    with c_tab1:
        st.subheader("📝 メンテナンス / 差戻し修正")
        with st.expander("➕ 新規申請フォームを開く", expanded=True):

            col_search_input, col_search_btn = st.columns([4, 1])
            cust_code_input = col_search_input.text_input(
                "🔍 顧客コード入力",
                value=st.session_state["cc_searched_ccode"],
                key=f"cc_cust_code_search{rclear}"
            )
            btn_search = col_search_btn.button("🔍 検索", use_container_width=True, type="secondary", key=f"cc_search_btn{rclear}")

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
                            st.session_state["cc_searched_ccode"] = str(cust_code_input)
                            st.session_state[f"cc_ccode{rclear}"] = str(cust_code_input)
                            st.session_state[f"cc_sname{rclear}"] = str(last_row.iloc[0]) if pd.notna(last_row.iloc[0]) else ""
                            st.session_state[f"cc_cname{rclear}"] = str(last_row.iloc[2]) if pd.notna(last_row.iloc[2]) else ""
                            st.session_state[f"cc_scode{rclear}"] = str(last_row.iloc[4]) if pd.notna(last_row.iloc[4]) else ""
                            st.session_state[f"cc_products{rclear}"] = get_contract_products(cust_code_input)

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
            customer_code = row1_col1.text_input("顧客コード", key=f"cc_ccode{rclear}")
            customer_name = row1_col2.text_input("顧客名", key=f"cc_cname{rclear}")
            store_name = row1_col3.text_input("加盟店名", key=f"cc_sname{rclear}")

            row1b_col1, row1b_col2 = st.columns(2)
            store_code = row1b_col1.text_input("加盟店コード", key=f"cc_scode{rclear}")
            applicant = row1b_col2.text_input("担当者", value=st.session_state["user_name"], key=f"cc_app{rclear}")

            products = st.session_state[f"cc_products{rclear}"]
            product_labels = _cc_product_labels(products)

            st.write("---")

            items_data = []
            total_before = 0.0
            total_after = 0.0

            for n in range(CC_ITEM_COUNT):
                st.markdown(f"**商品 {n + 1}**")

                def _make_before_cb(_n=n, _rclear=rclear):
                    def _cb():
                        _products = st.session_state.get(f"cc_products{_rclear}", [])
                        _idx = st.session_state.get(f"cc_before_code_{_n}{_rclear}")
                        _match = _products[_idx] if isinstance(_idx, int) and 0 <= _idx < len(_products) else None
                        if _match:
                            st.session_state[f"cc_before_price_{_n}{_rclear}"] = _cc_hide_zero(_match["price"])
                            st.session_state[f"cc_before_cycle_{_n}{_rclear}"] = _cc_hide_zero(_match["cycle"])
                            st.session_state[f"cc_before_a_{_n}{_rclear}"] = _cc_hide_zero(_match["week_a"])
                            st.session_state[f"cc_before_b_{_n}{_rclear}"] = _cc_hide_zero(_match["week_b"])
                            st.session_state[f"cc_before_c_{_n}{_rclear}"] = _cc_hide_zero(_match["week_c"])
                            st.session_state[f"cc_before_d_{_n}{_rclear}"] = _cc_hide_zero(_match["week_d"])
                        else:
                            for _suf in ["price", "cycle", "a", "b", "c", "d"]:
                                st.session_state[f"cc_before_{_suf}_{_n}{_rclear}"] = ""
                    return _cb

                # ---- 変更前・変更後をそれぞれ「商品記号/契約数/単価/周期」の行と「A/B/C/D」の行の
                # 2段（最大4列）に分けて表示。半分幅の画面でも文字がつぶれないようにするため。 ----
                st.markdown("🔵 変更前")
                b_row1 = st.columns(4)
                b_row2 = st.columns(4)

                before_idx = b_row1[0].selectbox(
                    "商品記号", [None] + list(range(len(products))),
                    format_func=lambda i: "" if i is None else product_labels[i],
                    key=f"cc_before_code_{n}{rclear}", on_change=_make_before_cb(),
                )
                before_code = products[before_idx]["code"] if isinstance(before_idx, int) else ""
                before_price = b_row1[2].text_input("単価", key=f"cc_before_price_{n}{rclear}", disabled=True)
                before_cycle = b_row1[3].text_input("周期", key=f"cc_before_cycle_{n}{rclear}", disabled=True)
                before_a = b_row2[0].text_input("A", key=f"cc_before_a_{n}{rclear}", disabled=True)
                before_b = b_row2[1].text_input("B", key=f"cc_before_b_{n}{rclear}", disabled=True)
                before_c = b_row2[2].text_input("C", key=f"cc_before_c_{n}{rclear}", disabled=True)
                before_d = b_row2[3].text_input("D", key=f"cc_before_d_{n}{rclear}", disabled=True)

                before_count = _cc_sum4(before_a, before_b, before_c, before_d)
                st.session_state[f"cc_before_count_{n}{rclear}"] = before_count
                b_row1[1].text_input("契約数", key=f"cc_before_count_{n}{rclear}", disabled=True)

                st.markdown("🟢 変更後")
                a_row1 = st.columns(4)
                a_row2 = st.columns(4)

                after_pick = a_row1[0].selectbox(
                    "商品記号",
                    list(range(len(products))),
                    index=None,
                    accept_new_options=True,
                    format_func=lambda i: product_labels[i] if isinstance(i, int) else str(i),
                    placeholder="選択 or 入力",
                    key=f"cc_after_code_{n}{rclear}",
                )
                after_code = products[after_pick]["code"] if isinstance(after_pick, int) else (after_pick or "")
                after_price = a_row1[2].text_input("単価", key=f"cc_after_price_{n}{rclear}")
                after_cycle = a_row1[3].text_input("周期", key=f"cc_after_cycle_{n}{rclear}")
                after_a = a_row2[0].text_input("A", key=f"cc_after_a_{n}{rclear}")
                after_b = a_row2[1].text_input("B", key=f"cc_after_b_{n}{rclear}")
                after_c = a_row2[2].text_input("C", key=f"cc_after_c_{n}{rclear}")
                after_d = a_row2[3].text_input("D", key=f"cc_after_d_{n}{rclear}")

                after_count = _cc_sum4(after_a, after_b, after_c, after_d)
                st.session_state[f"cc_after_count_{n}{rclear}"] = after_count
                a_row1[1].text_input("契約数", key=f"cc_after_count_{n}{rclear}", disabled=True)

                items_data.append({
                    "before_code": before_code, "before_price": before_price, "before_cycle": before_cycle,
                    "before_a": before_a, "before_b": before_b, "before_c": before_c, "before_d": before_d,
                    "after_code": after_code, "after_price": after_price, "after_cycle": after_cycle,
                    "after_a": after_a, "after_b": after_b, "after_c": after_c, "after_d": after_d,
                })

                total_before += calc_cc_amount(before_price, before_cycle, before_a, before_b, before_c, before_d)
                total_after += calc_cc_amount(after_price, after_cycle, after_a, after_b, after_c, after_d)

                st.write("---")

            amount_diff = total_after - total_before
            m1, m2, m3 = st.columns(3)
            m1.metric("変更前 合計金額", f"{total_before:,.0f}")
            m2.metric("変更後 合計金額", f"{total_after:,.0f}")
            m3.metric("増減金額（変更後－変更前）", _cc_format_yen(amount_diff))

            with st.form("cc_submit_form"):
                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                cc_reason = st.text_input("理由", key=f"cc_reason{rclear}")
                cc_contact = st.text_input("連絡担当者様", key=f"cc_contact{rclear}")
                cc_comment = st.text_area("特記事項", key=f"cc_comment{rclear}")
                cc_nvisit_val = st.date_input("次回訪問日", value=None, key=f"cc_nvisit{rclear}")
                cc_nvisit = cc_nvisit_val.strftime("%Y/%m/%d") if cc_nvisit_val else ""

                btn_submit = st.form_submit_button("新規申請を送信", type="primary")

                if btn_submit:
                    if not customer_code.strip():
                        st.error("⚠️ 「顧客コード」は必須項目です。入力してください。")
                    else:
                        now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                        full_row = [now_str, applicant, customer_code, customer_name, store_name, store_code]
                        for item in items_data:
                            for f in CC_ITEM_FIELDS:
                                full_row.append(item[f])
                        full_row += [cc_reason, cc_contact, cc_comment, f"{amount_diff:.0f}", cc_nvisit, "申請中", "", ""]

                        payload = {
                            "action": "SUBMIT_CONTRACT_CHANGE",
                            "target_sheet_url": CC_TARGET_SHEET_URL,
                            "full_row": full_row
                        }
                        res = post_to_gas(payload)
                        if res.get("status") == "success":
                            st.toast("新規申請を送信しました！", icon="🎉")
                            st.session_state["cc_searched_ccode"] = ""
                            st.session_state["cc_form_clear_key"] += 1
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"送信失敗: {res.get('message')}")

        st.write("---")
        st.subheader("⚠️ 差戻し・再修正が必要なデータ")
        try:
            st.cache_data.clear()
            df = pd.read_csv(CC_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > CC_COL["status_sign"]:
                rejected_df = df[df.iloc[:, CC_COL["status_sign"]].astype(str).str.strip() == "差戻し"]
                if rejected_df.empty:
                    st.info("現在、差戻しデータはありません。")
                else:
                    for idx, row in rejected_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = CC_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        rej_comment = _v("approval_comment")
                        items = cc_extract_items(row)

                        with st.expander(f"🔴 【差戻し】{_v('cust_name')} (行: {row_id}) | 理由: {rej_comment}"):
                            st.write("**現在の内容**")
                            df_items = cc_items_display_df(items)
                            if not df_items.empty:
                                st.dataframe(df_items, use_container_width=True, hide_index=True)

                            with st.form(key=f"cc_resubmit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報修正**")

                                r1_1, r1_2, r1_3 = st.columns(3)
                                edit_cust_code = r1_1.text_input("顧客コード", value=_v("cust_code"), key=f"cc_re_ccode_{row_id}")
                                edit_cust_name = r1_2.text_input("顧客名", value=_v("cust_name"), key=f"cc_re_cname_{row_id}")
                                edit_store_code = r1_3.text_input("加盟店コード", value=_v("store_code"), key=f"cc_re_scode_{row_id}")

                                r2_1, r2_2 = st.columns(2)
                                edit_store_name = r2_1.text_input("加盟店", value=_v("store_name"), key=f"cc_re_sname_{row_id}")
                                edit_applicant = r2_2.text_input("担当者", value=_v("applicant"), key=f"cc_re_app_{row_id}")

                                st.caption("商品内容（変更前・変更後）は上の表の内容がそのまま再申請されます。商品自体を修正したい場合は新規申請からやり直してください。")

                                edit_reason = st.text_input("変更理由", value=_v("reason"), key=f"cc_re_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"cc_re_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"cc_re_comment_{row_id}")
                                edit_nvisit = st.text_input("次回訪問日", value=_v("next_visit"), key=f"cc_re_nvisit_{row_id}")

                                btn_resubmit = st.form_submit_button("🔄 修正して再申請", type="primary")

                                if btn_resubmit:
                                    if not edit_cust_code.strip():
                                        st.error("⚠️ 「顧客コード」は必須項目です。")
                                    else:
                                        item_values = []
                                        for item in items:
                                            for f in CC_ITEM_FIELDS:
                                                item_values.append(item[f])

                                        updated_row = [
                                            _v("timestamp"), edit_applicant, edit_cust_code, edit_cust_name,
                                            edit_store_name, edit_store_code
                                        ] + item_values + [
                                            edit_reason, edit_contact, edit_comment, _v("amount_diff"), edit_nvisit, "申請中", "", ""
                                        ]

                                        payload = {
                                            "action": "RESUBMIT_CONTRACT_CHANGE",
                                            "target_sheet_url": CC_TARGET_SHEET_URL,
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
    with c_tab2:
        st.subheader("🔍 管理職チェック")
        try:
            st.cache_data.clear()
            df = pd.read_csv(CC_TARGET_SHEET_CSV, dtype=str)
            if not df.empty and len(df.columns) > CC_COL["status_sign"]:
                pending_df = df[df.iloc[:, CC_COL["status_sign"]].astype(str).str.strip() == "申請中"]
                if pending_df.empty:
                    st.info("現在、未承認の申請はありません。")
                else:
                    st.warning(f"承認待ちデータ: **{len(pending_df)} 件**")
                    for idx, row in pending_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = CC_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        items = cc_extract_items(row)

                        with st.expander(f"⏳ 【承認待ち】{_v('cust_name')}（{_v('cust_code')}） | 行: {row_id}"):
                            cc_render_items_readonly(items, key_prefix=f"cc_m_view_{row_id}")
                            st.caption(f"増減金額: {_cc_format_yen(_v('amount_diff'))}")

                            with st.form(key=f"cc_mgr_edit_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                st.write("**📋 入力情報（修正可能）**")

                                m1_1, m1_2, m1_3 = st.columns(3)
                                edit_ccode = m1_1.text_input("顧客コード", value=_v("cust_code"), key=f"cc_m_ccode_{row_id}")
                                edit_cname = m1_2.text_input("顧客名", value=_v("cust_name"), key=f"cc_m_cname_{row_id}")
                                edit_scode = m1_3.text_input("加盟店コード", value=_v("store_code"), key=f"cc_m_scode_{row_id}")

                                m2_1, m2_2 = st.columns(2)
                                edit_sname = m2_1.text_input("加盟店", value=_v("store_name"), key=f"cc_m_sname_{row_id}")
                                edit_app = m2_2.text_input("担当者", value=_v("applicant"), key=f"cc_m_app_{row_id}")

                                edit_reason = st.text_input("変更理由", value=_v("reason"), key=f"cc_m_reason_{row_id}")
                                edit_contact = st.text_input("連絡担当者様", value=_v("contact_person"), key=f"cc_m_contact_{row_id}")
                                edit_comment = st.text_area("特記事項", value=_v("comment"), key=f"cc_m_comment_{row_id}")
                                edit_nvisit = st.text_input("次回訪問日", value=_v("next_visit"), key=f"cc_m_nvisit_{row_id}")
                                mgr_comment = st.text_input("管理職コメント / 差戻し理由", key=f"cc_mgr_com_{row_id}")

                                col_app, col_rej, col_del = st.columns(3)
                                btn_approve = col_app.form_submit_button("✅ 承認（変更内容を反映）", type="primary", use_container_width=True)
                                btn_reject = col_rej.form_submit_button("↩️ 差戻し", use_container_width=True)
                                btn_delete = col_del.form_submit_button("🗑️ 削除", use_container_width=True)

                                mgr_name = st.session_state["user_name"]
                                now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

                                if btn_approve or btn_reject or btn_delete:
                                    item_values = []
                                    for item in items:
                                        for f in CC_ITEM_FIELDS:
                                            item_values.append(item[f])

                                    updated_row = [
                                        _v("timestamp"), edit_app, edit_ccode, edit_cname,
                                        edit_sname, edit_scode
                                    ] + item_values + [edit_reason, edit_contact, edit_comment, _v("amount_diff"), edit_nvisit]

                                    action_type = ""
                                    if btn_approve:
                                        action_type = "APPROVE_CONTRACT_CHANGE"
                                        updated_row.extend([mgr_name, now_str, mgr_comment])
                                    elif btn_reject:
                                        action_type = "REJECT_CONTRACT_CHANGE"
                                        updated_row.extend(["差戻し", now_str, mgr_comment])
                                    elif btn_delete:
                                        action_type = "DELETE_CONTRACT_CHANGE"
                                        updated_row.extend(["削除", now_str, mgr_comment])

                                    payload = {
                                        "action": action_type,
                                        "target_sheet_url": CC_TARGET_SHEET_URL,
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
    with c_tab3:
        st.subheader("🚚 業務担当メンテナンス処理")
        try:
            st.cache_data.clear()
            df = pd.read_csv(CC_TARGET_SHEET_CSV, dtype=str)

            if df.empty or len(df.columns) <= CC_COL["status_sign"]:
                st.info("現在、処理可能なデータはありません。")
            else:
                status_series = df.iloc[:, CC_COL["status_sign"]].astype(str).str.strip()
                approved_df = df[
                    (~df.iloc[:, CC_COL["status_sign"]].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                ]

                if approved_df.empty:
                    st.info("現在、業務引き継ぎ待ちの承認済みデータはありません。")
                else:
                    st.success(f"📋 転記可能な承認済みデータ: **{len(approved_df)} 件**")

                    for idx, row in approved_df.iloc[::-1].iterrows():
                        row_id = idx + 2

                        def _v(col_key, r=row):
                            i = CC_COL[col_key]
                            return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                        mgr_name = _v("status_sign")
                        items = cc_extract_items(row)

                        with st.expander(f"🟢【{_v('cust_name')}（{_v('cust_code')}）】 承認者: {mgr_name}"):
                            st.write("**📋 申請内容**")

                            o1_c1, o1_c2, o1_c3 = st.columns(3)
                            o1_c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"cc_v_ccode_{row_id}")
                            o1_c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"cc_v_cname_{row_id}")
                            o1_c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"cc_v_scode_{row_id}")

                            o2_c1, o2_c2 = st.columns(2)
                            o2_c1.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"cc_v_sname_{row_id}")
                            o2_c2.text_input("担当者", value=_v("applicant"), disabled=True, key=f"cc_v_app_{row_id}")

                            cc_render_items_readonly(items, key_prefix=f"cc_v_view_{row_id}")

                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            nvisit_val = _v("next_visit")
                            if reason_val.strip() or contact_val.strip() or comment_val.strip() or nvisit_val.strip():
                                if reason_val.strip():
                                    st.text_input("変更理由", value=reason_val, disabled=True, key=f"cc_v_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"cc_v_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"cc_v_comment_{row_id}")
                                if nvisit_val.strip():
                                    st.text_input("次回訪問日", value=nvisit_val, disabled=True, key=f"cc_v_nvisit_{row_id}")
                            st.caption(f"増減金額: {_cc_format_yen(_v('amount_diff'))}")

                            st.write("---")
                            with st.form(key=f"cc_transfer_form_{row_id}"):
                                st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                                op_reject_reason = st.text_input("⚠️ 差戻し理由（※業務側で不備がある場合のみ入力）", key=f"cc_op_rej_reason_{row_id}")

                                col_trans, col_rej = st.columns(2)
                                btn_transfer = col_trans.form_submit_button("📋 別シートへ出力・転記", type="primary", use_container_width=True)
                                btn_op_reject = col_rej.form_submit_button("↩️ 申請者へ差戻し", use_container_width=True)

                                action_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                op_user = st.session_state["user_name"]

                                if btn_transfer:
                                    clean_base_row = [
                                        "" if pd.isna(row.iloc[i]) else str(row.iloc[i])
                                        for i in range(CC_COL["status_sign"] + 3)
                                    ]
                                    transfer_row = clean_base_row + [action_time, op_user]

                                    payload = {
                                        "action": "TRANSFER_CONTRACT_CHANGE_TO_OPERATOR",
                                        "target_sheet_url": CC_TARGET_SHEET_URL,
                                        "dest_sheet_url": CC_DEST_SHEET_URL,
                                        "row_index": row_id,
                                        "transfer_row": transfer_row,
                                        "status_col": CC_COL["status_sign"] + 1,
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
                                            for i in range(CC_COL["status_sign"])
                                        ]
                                        final_reject_row = base_data + ["差戻し", action_time, op_reject_reason]

                                        payload = {
                                            "action": "REJECT_CONTRACT_CHANGE",
                                            "target_sheet_url": CC_TARGET_SHEET_URL,
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
    with c_tab4:
        st.subheader("✅ メンテナンスチェック画面")

        try:
            st.cache_data.clear()
            df_dest = pd.read_csv(CC_DEST_SHEET_CSV, dtype=str)

            if df_dest.empty:
                st.info("現在、チェック対象のデータ（転記済みデータ）はありません。")
            else:
                show_checked = st.checkbox("✅ チェック済みのデータも表示する", value=False, key="cc_chk_show_checked")

                if not show_checked and len(df_dest.columns) > CC_COL["check_time"]:
                    unchecked_mask = df_dest.iloc[:, CC_COL["check_time"]].fillna("").astype(str).str.strip() == ""
                    df_dest = df_dest[unchecked_mask]

                if df_dest.empty:
                    st.info("チェック待ちのデータはありません（すべてチェック済みです）。上のチェックボックスでチェック済みも表示できます。")
                else:
                    st.success(f"📋 チェック対象データ: **{len(df_dest)} 件**")

                for idx, row in df_dest.iterrows():
                    row_id = idx + 2

                    def _v(col_key, r=row):
                        i = CC_COL[col_key]
                        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

                    mgr_name_val = _v("status_sign") or "不明"
                    op_user_val = _v("process_user") or "不明"
                    checked_time_val = _v("check_time")
                    checked_user_val = _v("check_user")
                    items = cc_extract_items(row)

                    expander_label = f"📌 {_v('cust_name')}（{_v('cust_code')}） | 加盟店: {_v('store_name') or '未設定'}"
                    if checked_time_val:
                        expander_label += " ✅【チェック済み】"

                    with st.expander(expander_label):
                        with st.form(key=f"cc_check_form_{row_id}"):
                            st.form_submit_button("（Enterキー無効化用）", disabled=True, use_container_width=True)

                            st.write("**📋 登録内容詳細**")
                            c1, c2, c3 = st.columns(3)
                            c1.text_input("顧客コード", value=_v("cust_code"), disabled=True, key=f"cc_chk_ccode_{row_id}")
                            c2.text_input("顧客名", value=_v("cust_name"), disabled=True, key=f"cc_chk_cname_{row_id}")
                            c3.text_input("加盟店コード", value=_v("store_code"), disabled=True, key=f"cc_chk_scode_{row_id}")

                            c4, c5 = st.columns(2)
                            c4.text_input("加盟店", value=_v("store_name"), disabled=True, key=f"cc_chk_sname_{row_id}")
                            c5.text_input("担当者", value=_v("applicant"), disabled=True, key=f"cc_chk_app_{row_id}")

                            cc_render_items_readonly(items, key_prefix=f"cc_chk_view_{row_id}")

                            c6, c7 = st.columns(2)
                            c6.text_input("処理者", value=op_user_val, disabled=True, key=f"cc_chk_op_{row_id}")
                            c7.text_input("承認者", value=mgr_name_val, disabled=True, key=f"cc_chk_mgr_{row_id}")

                            st.caption(f"増減金額: {_cc_format_yen(_v('amount_diff'))}")

                            if checked_time_val:
                                st.info(f"✅ 直近のチェック日時: {checked_time_val} （チェック者: {checked_user_val}）")

                            reason_val = _v("reason")
                            contact_val = _v("contact_person")
                            comment_val = _v("comment")
                            nvisit_val = _v("next_visit")
                            if reason_val.strip() or contact_val.strip() or comment_val.strip() or nvisit_val.strip():
                                st.write("---")
                                if reason_val.strip():
                                    st.text_input("変更理由", value=reason_val, disabled=True, key=f"cc_chk_reason_{row_id}")
                                if contact_val.strip():
                                    st.text_input("連絡担当者様", value=contact_val, disabled=True, key=f"cc_chk_contact_{row_id}")
                                if comment_val.strip():
                                    st.text_area("特記事項", value=comment_val, disabled=True, key=f"cc_chk_comment_{row_id}")
                                if nvisit_val.strip():
                                    st.text_input("次回訪問日", value=nvisit_val, disabled=True, key=f"cc_chk_nvisit_{row_id}")

                            st.write("---")
                            st.write("⚠️ **差戻しを行う場合の設定**")
                            r_col1, r_col2 = st.columns(2)
                            reject_target = r_col1.selectbox("差戻し先を選択", ["業務担当", "申請者"], key=f"cc_chk_rej_target_{row_id}")
                            reject_reason = r_col2.text_input("差戻し理由", key=f"cc_chk_rej_reason_{row_id}")

                            col_ok, col_ng = st.columns(2)
                            btn_checked_ok = col_ok.form_submit_button("✅ チェック完了（確認済み）", type="primary", use_container_width=True)
                            btn_checked_reject = col_ng.form_submit_button("↩️ 指定先へ差戻し", use_container_width=True)

                            if btn_checked_ok:
                                check_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                checker_name = st.session_state["user_name"]

                                clean_base_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
                                while len(clean_base_row) < CC_COL["check_user"] + 1:
                                    clean_base_row.append("")

                                clean_base_row[CC_COL["check_time"]] = check_time
                                clean_base_row[CC_COL["check_user"]] = checker_name
                                # ※ print_time列（印刷済）はここでは触らない。既存の値を保持する。

                                payload = {
                                    "action": "UPDATE_CONTRACT_CHANGE_CHECK",
                                    "target_sheet_url": CC_DEST_SHEET_URL,
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
    # TAB 5: 加盟店別 印刷プレビュー画面
    # ==========================================
    with c_tab5:
        st.subheader("🖨️ 加盟店別 印刷プレビュー（スプレッドシート貼り付け・PDF印刷用）")

        try:
            st.cache_data.clear()
            df_print = pd.read_csv(CC_DEST_SHEET_CSV, dtype=str)

            if df_print.empty:
                st.info("現在、印刷対象のデータはありません。")
            else:
                # TAB4で「✅ チェック完了」になったデータだけを対象にする
                if len(df_print.columns) > CC_COL["check_time"]:
                    checked_mask = df_print.iloc[:, CC_COL["check_time"]].fillna("").astype(str).str.strip() != ""
                    df_print = df_print[checked_mask]

                # すでに印刷済み（印刷日時が入っている行）は印刷画面に出さない
                if len(df_print.columns) > CC_COL["print_time"]:
                    not_printed_mask = df_print.iloc[:, CC_COL["print_time"]].fillna("").astype(str).str.strip() == ""
                    df_print = df_print[not_printed_mask]

                if df_print.empty:
                    st.info("印刷対象のデータがありません（TAB4でチェック未完了、またはすでに印刷済みです）。")
                else:
                    store_col_idx = CC_COL["store_name"]
                    df_print["_store_name"] = df_print.iloc[:, store_col_idx].fillna("未設定の加盟店")
                    stores = sorted(df_print["_store_name"].unique())

                    selected_store = st.selectbox("🖨️ 印刷する加盟店を選択してください", stores, key="cc_print_store_select")

                    if selected_store:
                        store_df = df_print[df_print["_store_name"] == selected_store]
                        total_records = len(store_df)

                        st.info(f"🏪 加盟店: **{selected_store}** （未印刷のチェック完了済みデータ: {total_records} 件）※1ページに最大{len(CC_PRINT_BASE_ROWS)}件まで配置されます。")

                        def build_cc_record(r_row):
                            """行データを、印刷フォーマットのラベルに沿って取り出す"""
                            def _f(col_key):
                                i = CC_COL[col_key]
                                return str(r_row.iloc[i]) if len(r_row) > i and pd.notna(r_row.iloc[i]) else ""

                            manager = _f("status_sign") or "未確認"
                            operator = _f("process_user") or st.session_state["user_name"]
                            contact = _f("contact_person")
                            contact_disp = f"{contact} 様" if contact.strip() else ""
                            raw_cname = _f("cust_name")
                            cust_name_disp = f"{raw_cname} 様" if raw_cname.strip() else ""

                            items = cc_extract_items(r_row)
                            print_items = []
                            for it in items:
                                print_items.append({
                                    "before_code": it["before_code"],
                                    "before_count": _cc_sum4(it["before_a"], it["before_b"], it["before_c"], it["before_d"]),
                                    "before_price": it["before_price"], "before_cycle": it["before_cycle"],
                                    "before_a": it["before_a"], "before_b": it["before_b"],
                                    "before_c": it["before_c"], "before_d": it["before_d"],
                                    "after_code": it["after_code"],
                                    "after_count": _cc_sum4(it["after_a"], it["after_b"], it["after_c"], it["after_d"]),
                                    "after_price": it["after_price"], "after_cycle": it["after_cycle"],
                                    "after_a": it["after_a"], "after_b": it["after_b"],
                                    "after_c": it["after_c"], "after_d": it["after_d"],
                                })

                            return {
                                "store_code": _f("store_code"), "cust_name": cust_name_disp,
                                "cust_code": _f("cust_code"), "staff_name": _f("applicant"),
                                "manager": manager, "operator": operator,
                                "reason": _f("reason"), "contact_disp": contact_disp,
                                "comment": _f("comment") or "特記事項なし",
                                "next_visit": _f("next_visit"),
                                "amount_diff": _cc_format_yen(_f("amount_diff")),
                                "items": print_items,
                            }

                        _cc_empty_print_item = {
                            "before_code": "", "before_count": "", "before_price": "", "before_cycle": "",
                            "before_a": "", "before_b": "", "before_c": "", "before_d": "",
                            "after_code": "", "after_count": "", "after_price": "", "after_cycle": "",
                            "after_a": "", "after_b": "", "after_c": "", "after_d": "",
                        }

                        def cc_cells_for_record(rec):
                            """1件分のデータを、base_row行目を起点にした「行オフセット・列・値」のリストに変換する。
                            指定されていないセル（行・列）はテンプレート側の固定内容として一切触らない。
                            A/C/H/J/L/O(+0)=加盟店コード/顧客名/シャトルコード(顧客コード)/担当者名/責任者名/処理者,
                            商品①〜⑤はA〜H列(+3〜+7)=変更前(記号/契約数/単価/周期/A/B/C/D)、I〜P列=変更後(同順),
                            A/I/L(+9)=理由/連絡担当者様/増減金額, A/L(+11)=特記事項/次回訪問日"""
                            if not rec:
                                rec = {
                                    "store_code": "", "cust_name": "", "cust_code": "", "staff_name": "",
                                    "manager": "", "operator": "", "reason": "", "contact_disp": "",
                                    "comment": "", "next_visit": "", "amount_diff": "",
                                    "items": [dict(_cc_empty_print_item) for _ in range(CC_ITEM_COUNT)],
                                }

                            cells = [
                                {"offset": 0, "col": 1, "value": rec["store_code"]},
                                {"offset": 0, "col": 3, "value": rec["cust_name"]},
                                {"offset": 0, "col": 8, "value": rec["cust_code"]},
                                # 💡 担当者/責任者サイン/処理者は「変更前/変更後」の見出し行(offset 1)ではなく、
                                #    加盟店コード等と同じ行(offset 0)にある。offset 1のcol10/12/15は
                                #    「変更後」の結合セル(I:P)の内側に埋もれて見た目に反映されなかったため修正。
                                {"offset": 0, "col": 10, "value": rec["staff_name"]},
                                {"offset": 0, "col": 12, "value": rec["manager"]},
                                {"offset": 0, "col": 15, "value": rec["operator"]},
                            ]

                            item_col_order = [
                                "before_code", "before_count", "before_price", "before_cycle",
                                "before_a", "before_b", "before_c", "before_d",
                                "after_code", "after_count", "after_price", "after_cycle",
                                "after_a", "after_b", "after_c", "after_d",
                            ]
                            items = rec.get("items") or [_cc_empty_print_item] * CC_ITEM_COUNT
                            for n in range(CC_ITEM_COUNT):
                                it = items[n] if n < len(items) else _cc_empty_print_item
                                for col_i, field in enumerate(item_col_order, start=1):
                                    val = it.get(field, "")
                                    if field in ("before_cycle", "after_cycle"):
                                        val = _cc_cycle_disp(val)
                                    cells.append({"offset": 3 + n, "col": col_i, "value": val})

                            cells += [
                                {"offset": 9, "col": 1, "value": rec["reason"]},
                                {"offset": 9, "col": 9, "value": rec["contact_disp"]},
                                {"offset": 9, "col": 12, "value": rec["amount_diff"]},
                                {"offset": 11, "col": 1, "value": rec["comment"]},
                                {"offset": 11, "col": 12, "value": rec["next_visit"]},
                            ]
                            return cells

                        chunk_size = len(CC_PRINT_BASE_ROWS)
                        chunks = [store_df.iloc[i:i + chunk_size] for i in range(0, total_records, chunk_size)]

                        for page_idx, chunk in enumerate(chunks):
                            st.markdown(f"#### 📄 ページ {page_idx + 1} / {len(chunks)}")

                            header_value = f"{selected_store} 様"
                            blocks = []
                            preview_records = []
                            page_row_ids = [int(idx) + 2 for idx in chunk.index]

                            for slot, base_row in enumerate(CC_PRINT_BASE_ROWS):
                                rec = build_cc_record(chunk.iloc[slot]) if slot < len(chunk) else None
                                if rec:
                                    preview_records.append(rec)
                                blocks.append({"start_row": base_row, "cells": cc_cells_for_record(rec)})

                            with st.expander(f"プレビューを見る（{len(preview_records)} 件）"):
                                for r_i, rec in enumerate(preview_records):
                                    st.write(f"**[{r_i + 1}件目] 加盟店コード: {rec['store_code']} ／ 顧客名: {rec['cust_name']} ／ シャトルコード: {rec['cust_code']}**")
                                    st.caption(f"担当者名: {rec['staff_name']} ｜ 責任者: {rec['manager']} ｜ 処理者: {rec['operator']}")
                                    df_items = cc_items_display_df(rec["items"])
                                    if not df_items.empty:
                                        st.dataframe(df_items, use_container_width=True, hide_index=True)
                                    st.caption(f"理由: {rec['reason']} ｜ 連絡担当者: {rec['contact_disp']} ｜ 増減金額: {rec['amount_diff']}")
                                    st.caption(f"特記事項: {rec['comment']} ｜ 次回訪問日: {rec['next_visit']}")

                            if st.button("📥 反映してPDFを作成する", key=f"cc_print_sync_btn_{page_idx}", type="primary"):
                                payload = {
                                    "action": "SYNC_PRINT_STORE_DATA",
                                    "print_sheet_url": CC_PRINT_SHEET_URL,
                                    "store_name": selected_store,
                                    "header_cells": [{"cell": "I1", "value": header_value}],
                                    "blocks": blocks,
                                }
                                with st.spinner("印刷用スプレッドシートへ反映しています..."):
                                    res = post_to_gas(payload)

                                if res.get("status") == "success":
                                    print_time = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
                                    mark_payload = {
                                        "action": "MARK_PRINTED",
                                        "target_sheet_url": CC_DEST_SHEET_URL,
                                        "row_indices": page_row_ids,
                                        "print_time": print_time,
                                        "print_col": CC_COL["print_time"] + 1,
                                    }
                                    mark_res = post_to_gas(mark_payload)
                                    if mark_res.get("status") != "success":
                                        st.warning(f"印刷済みマークの更新に失敗しました（反映自体は完了しています）: {mark_res.get('message')}")

                                    st.toast("🎉 反映が完了しました。PDFを作成しています…", icon="✅")
                                    try:
                                        pdf_row_end = CC_PRINT_BASE_ROWS[len(chunk) - 1] + 12 if len(chunk) > 0 else 16
                                        with st.spinner("PDFを作成しています..."):
                                            pdf_res = requests.get(
                                                build_print_pdf_url(row_end=pdf_row_end, col_end=16, gid=CC_PRINT_SHEET_GID),
                                                timeout=30
                                            )
                                        content_type = pdf_res.headers.get("Content-Type", "")
                                        if pdf_res.status_code == 200 and "pdf" in content_type.lower():
                                            st.success("✅ PDFが作成できました。下のボタンからダウンロードしてください。")
                                            st.download_button(
                                                "📄 PDFをダウンロード",
                                                data=pdf_res.content,
                                                file_name=f"{selected_store}_contract_change_p{page_idx + 1}.pdf",
                                                mime="application/pdf",
                                                key=f"cc_pdf_dl_{page_idx}",
                                            )
                                        else:
                                            st.warning(
                                                "スプレッドシートへの反映は完了しましたが、アプリ上でのPDF取得に失敗しました"
                                                "（共有設定などが原因の可能性があります）。"
                                                f"[印刷用スプレッドシートを開く]({CC_PRINT_SHEET_URL}) から印刷（PDF保存）してください。"
                                            )
                                    except Exception as pdf_e:
                                        st.warning(f"PDF作成中にエラーが発生しました: {pdf_e}")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(f"反映に失敗しました: {res.get('message')}")

        except Exception as e:
            st.error(f"データ読み込みエラー: {e}")
