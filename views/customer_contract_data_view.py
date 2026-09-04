"""権限3（および全権限=0）専用：顧客マスター・ご契約データを、Excelからの貼り付けで
一括更新するための画面。

既存の9モード（商品発注／ルート変更／契約内容変更…）とは別の、独立した1画面として提供する。
貼り付けた表データで、対象シート（顧客マスター or ご契約データ）の中身を「まるごと置き換える」
（既存データへの部分マージではなく、シート全体の棚卸し・一括更新を想定した仕様）。
"""
import streamlit as st

from views.maint_common import (
    post_to_gas, get_current_role,
    CUSTOMER_MASTER_SHEET_URL, CONTRACT_DATA_SHEET_URL,
)


def _parse_pasted_table(text):
    """Excel等からコピーした貼り付けテキスト（行=改行区切り、列=タブ区切り）を
    2次元配列（リストのリスト）に変換する。
    行によって列数が違う場合は、最大列数に合わせて空文字で埋める（setValuesは
    全行が同じ列数である必要があるため）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in text.split("\n") if line != ""]
    rows = [line.split("\t") for line in lines]
    if not rows:
        return []
    max_cols = max(len(r) for r in rows)
    for r in rows:
        while len(r) < max_cols:
            r.append("")
    return rows


def _render_replace_section(label, action_name, target_sheet_url, state_key):
    """1シート分（顧客マスター or ご契約データ）の貼り付け→確認→反映UIを描画する。"""
    st.subheader(label)
    st.caption(
        "Excelなどで対象の表を選択してコピーし、下の欄にそのまま貼り付けてください"
        "（見出し行も含めて、シートに入れたい内容をそのまま貼り付けます）。"
    )

    pasted = st.text_area(
        f"{label}の貼り付け欄",
        height=240,
        key=f"{state_key}_text",
        placeholder="ここにExcelの表を貼り付け（Ctrl+V）してください",
    )

    if not pasted.strip():
        return

    rows = _parse_pasted_table(pasted)
    max_cols = max((len(r) for r in rows), default=0)
    st.write(f"📋 貼り付け内容: {len(rows)} 行 × {max_cols} 列")

    with st.expander("貼り付け内容のプレビュー（先頭10行）", expanded=True):
        st.dataframe(rows[:10], use_container_width=True, hide_index=True)

    st.error(
        f"⚠️ 反映すると、現在の「{label}」シートの内容は**すべて削除され、"
        "貼り付けた内容だけに置き換わります**。元に戻すことはできません。"
        "内容をよく確認してから反映してください。"
    )
    confirm = st.checkbox(
        f"内容を確認しました。「{label}」シートを貼り付け内容で置き換えます。",
        key=f"{state_key}_confirm",
    )

    if st.button(
        f"🔁 {label}をこの内容で置き換える",
        type="primary",
        disabled=not confirm,
        key=f"{state_key}_btn",
    ):
        payload = {
            "action": action_name,
            "target_sheet_url": target_sheet_url,
            "rows": rows,
        }
        with st.spinner(f"{label}を反映しています..."):
            res = post_to_gas(payload)

        if res.get("status") == "success":
            st.success(f"✅ {label}を反映しました。")
            st.session_state[f"{state_key}_text"] = ""
            st.session_state[f"{state_key}_confirm"] = False
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(f"❌ 反映に失敗しました（データは変更されていません）: {res.get('message')}")


def customer_contract_data_screen():
    """権限3（および権限0＝全権限）専用：顧客データ・契約データの一括貼り付け更新画面。"""
    role = get_current_role()
    if role not in ("0", "3"):
        st.error("🔒 この機能は現在の権限では表示できません。")
        st.stop()

    st.markdown("#### 🗂️ 顧客データ・契約データ 一括更新")
    st.caption("Excelからコピーした表をそのまま貼り付けて、顧客マスター／ご契約データシートを一括更新できます。")
    st.write("---")

    tab_customer, tab_contract = st.tabs(["👤 顧客データ", "📄 契約データ"])

    with tab_customer:
        _render_replace_section(
            "顧客マスター", "REPLACE_CUSTOMER_MASTER", CUSTOMER_MASTER_SHEET_URL, "cust_import",
        )

    with tab_contract:
        _render_replace_section(
            "ご契約データ", "REPLACE_CONTRACT_DATA", CONTRACT_DATA_SHEET_URL, "contract_import",
        )
