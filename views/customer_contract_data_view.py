"""権限3（および全権限=0）専用：顧客マスター・ご契約データを、Excel/CSVファイルの
アップロードで一括更新するための画面。

既存の9モード（商品発注／ルート変更／契約内容変更…）とは別の、独立した1画面として提供する。
アップロードした表データで、対象シート（顧客マスター or ご契約データ）の中身を「まるごと置き換える」
（既存データへの部分マージではなく、シート全体の棚卸し・一括更新を想定した仕様）。
"""
import pandas as pd
import streamlit as st

from views.maint_common import (
    post_to_gas, get_current_role,
    CUSTOMER_MASTER_SHEET_URL, CONTRACT_DATA_SHEET_URL,
)


def _read_uploaded_table(uploaded_file):
    """アップロードされたExcel/CSVファイルを2次元配列（リストのリスト）に変換する。
    1行目の見出し行も含め、ファイルの中身をそのままシートの行として扱う（header=None）。"""
    if uploaded_file.name.lower().endswith(".csv"):
        df = pd.read_csv(uploaded_file, header=None, dtype=str, keep_default_na=False)
    else:
        df = pd.read_excel(uploaded_file, header=None, dtype=str, keep_default_na=False)
    return df.fillna("").values.tolist()


def _render_replace_section(label, action_name, target_sheet_url, state_key):
    """1シート分（顧客マスター or ご契約データ）のアップロード→確認→反映UIを描画する。"""
    st.subheader(label)
    st.caption(
        "Excelなどで作成したファイル（.xlsx / .csv）をそのままアップロードしてください"
        "（見出し行も含めて、シートに入れたい内容をそのままアップロードします）。"
    )

    uploaded_file = st.file_uploader(
        f"{label}のファイルを選択",
        type=["xlsx", "csv"],
        key=f"{state_key}_file",
    )

    if uploaded_file is None:
        return

    try:
        rows = _read_uploaded_table(uploaded_file)
    except Exception as e:
        st.error(f"ファイルの読み込みに失敗しました: {e}")
        return

    if not rows:
        st.warning("ファイルにデータがありません。")
        return

    max_cols = max((len(r) for r in rows), default=0)
    st.write(f"📋 ファイル内容: {len(rows)} 行 × {max_cols} 列")

    with st.expander("ファイル内容のプレビュー（先頭10行）", expanded=True):
        st.dataframe(rows[:10], use_container_width=True, hide_index=True)

    st.error(
        f"⚠️ 反映すると、現在の「{label}」シートの内容は**すべて削除され、"
        "アップロードした内容だけに置き換わります**。元に戻すことはできません。"
        "内容をよく確認してから反映してください。"
    )
    confirm = st.checkbox(
        f"内容を確認しました。「{label}」シートをこのファイルの内容で置き換えます。",
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
            st.session_state[f"{state_key}_confirm"] = False
            st.cache_data.clear()
            st.rerun()
        else:
            st.error(f"❌ 反映に失敗しました（データは変更されていません）: {res.get('message')}")


def customer_contract_data_screen():
    """権限3（および権限0＝全権限）専用：顧客データ・契約データの一括アップロード更新画面。"""
    role = get_current_role()
    if role not in ("0", "3"):
        st.error("🔒 この機能は現在の権限では表示できません。")
        st.stop()

    st.markdown("#### 🗂️ 顧客データ・契約データ 一括更新")
    st.caption("Excel/CSVファイルをアップロードするだけで、顧客マスター／ご契約データシートを一括更新できます。")
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
