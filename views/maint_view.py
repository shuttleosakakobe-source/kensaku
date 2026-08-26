import pandas as pd
import streamlit as st

# =====================================================================
# タブ4: メンテナンスチェック画面
# =====================================================================
st.subheader("📋 メンテナンスチェック画面")

# 1. タブ3・4・5共通のスプレッドシート（gid=0）からデータを読み込み
# （※タブ3と同じデータソース・形式を維持）
target_sheet_url_tab4 = (
    "https://script.google.com/macros/s/AKfycbxi6ZG-8F6bq0T9k-yD5g6DVRY4hPdDB5spzwISOGUpZckvktjN-ISkWmZd3EdPXNx-qQ/exec"
)

try:
  # CSVとしてデータを取得
  df_tab4 = pd.read_csv(target_sheet_url_tab4)

  if not df_tab4.empty:
    # 2. 並べ替え機能のUI（E列 ＝ インデックス4 を加盟店名として確実に指定）
    if len(df_tab4.columns) >= 5:
      store_col_name = df_tab4.columns[4]  .strip()  # E列の列名を取得

      st.markdown("### 🎛️ 表示・並び替え設定")
      col_s1, col_s2 = st.columns([1, 1])
      with col_s1:
        enable_sort = st.checkbox(
            "加盟店別（E列）で並び替える", value=True, key="tab4_store_sort_check"
        )
      with col_s2:
        sort_order = st.selectbox(
            "並び順",
            ["昇順 (あ〜わ)", "降順 (わ〜あ)"],
            key="tab4_store_sort_order",
        )

      # 3. 指定されたE列（加盟店）に基づいて並べ替えを実行
      if enable_sort:
        is_ascending = True if "昇順" in sort_order else False
        # 空欄（NaN）が含まれていてもエラーにならないよう文字列に変換してソート
        df_tab4[store_col_name] = df_tab4[store_col_name].fillna("").astype(str)
        df_tab4 = df_tab4.sort_values(
            by=store_col_name, ascending=is_ascending
        )

    # 4. タブ3と同じ形式でデータフレームを表示
    st.markdown("### 📄 メンテナンスチェック一覧")
    st.dataframe(df_tab4, use_container_width=True)

    # 5. チェック内容の保存・更新処理（GASへの送信）
    # ※必要に応じて既存の更新ボタンやイベント処理に接続してください
    if "update_gas_url" in locals() or "GAS_URL" in globals():
      gas_endpoint = GAS_URL if "GAS_URL" in globals() else update_gas_url

      if st.button(
          "💾 チェック内容を保存する", key="btn_save_maintenance_check"
      ):
        # ここにGAS（UPDATE_MAINTENANCE_CHECK）へのリクエスト処理を記述します
        st.success("チェック内容の保存処理を実行できます。")

  else:
    st.info(
        "表示するデータがありません。業務転記（タブ3）からデータが転記される"
        "とここに表示されます。"
    )

except Exception as e:
  st.error(
      f"データの読み込みまたは表示中にエラーが発生しました: {e}\nURLやシートの権限をご確認ください。"
  )
