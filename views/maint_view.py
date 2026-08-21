import streamlit as st
import requests

# ★ご自身のGASウェブアプリURLに置き換えてください★
GAS_URL = "https://script.google.com/macros/s/AKfycbwFcd8_UiYH9WqRJtnuDkrTq7mTb3ETviMnKhZmeykDnkitnlBgIbdAAonxNd_oTMCHcQ/exec"

def maintenance_admin_screen():
    st.title("メンテナンス・顧客マスタ検索")

    # セッション状態の初期化
    if "sname" not in st.session_state:
        st.session_state["sname"] = ""
    if "cname" not in st.session_state:
        st.session_state["cname"] = ""
    if "scode" not in st.session_state:
        st.session_state["scode"] = ""

    # 1. 顧客コード入力＆検索ボタン
    col1, col2 = st.columns([3, 1])
    with col1:
        customer_code_input = st.text_input("顧客コードを入力", key="input_cust_code")
    with col2:
        st.write(" ")  # 位置調整用
        search_btn = st.button("マスタ検索", key="btn_cust_search")

    # 検索処理
    if search_btn:
        if not customer_code_input:
            st.warning("顧客コードを入力してください。")
        else:
            with st.spinner("顧客マスタを検索中..."):
                try:
                    payload = {
                        "status": "GET_CUSTOMER_MASTER",
                        "customer_code": customer_code_input
                    }
                    response = requests.post(GAS_URL, json=payload, timeout=10)
                    res_json = response.json()

                    if res_json.get("status") == "success":
                        data = res_json.get("data")
                        if data:
                            st.session_state["sname"] = data.get("sname", "")
                            st.session_state["cname"] = data.get("cname", "")
                            st.session_state["scode"] = data.get("scode", "")
                            st.success("顧客データを取得しました！")
                        else:
                            st.error("該当する顧客コードは見つかりませんでした。")
                    else:
                        st.error(f"エラー: {res_json.get('message')}")

                except Exception as e:
                    st.error(f"通信エラーが発生しました: {e}")

    # 2. 結果表示（自動反映フォーム）
    st.subheader("顧客情報")
    st.text_input("顧客担当者名", value=st.session_state["sname"], key="sname_field")
    st.text_input("顧客名", value=st.session_state["cname"], key="cname_field")
    st.text_input("納品書印字顧客コード", value=st.session_state["scode"], key="scode_field")
