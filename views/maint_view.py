import streamlit as st
import requests

# GASのウェブアプリURL（ご自身のURLに置き換えてください）
GAS_URL = "https://script.google.com/macros/s/AKfycbzFqoLxnt4nwS7bSLK-nFrO4qzpTGD9cVTDWOiSvylmglHDCXuDvxG0XHBnE54pZC8O/exec"

st.title("顧客マスタ検索機能付きフォーム")

# セッション状態の初期化
if "sname" not in st.session_state:
    st.session_state["sname"] = ""
if "cname" not in st.session_state:
    st.session_state["cname"] = ""
if "scode" not in st.session_state:
    st.session_state["scode"] = ""

# 1. 顧客コード入力欄＆検索ボタン
col1, col2 = st.columns([3, 1])
with col1:
    customer_code_input = st.text_input("顧客コードを入力", key="input_cust_code")
with col2:
    st.write(" ")  # 位置調整用の余白
    search_btn = st.button("マスタ検索")

# 検索ボタンが押された時の処理
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
                        # 検索成功時：各入力フィールドのセッション状態を更新
                        st.session_state["sname"] = data.get("sname", "")
                        st.session_state["cname"] = data.get("cname", "")
                        st.session_state["scode"] = data.get("scode", "")
                        st.success("顧客データを取得しました！")
                    else:
                        st.error("該当する顧客コードは見つかりませんでした。")
                else:
                    st.error(f"エラーが発生しました: {res_json.get('message')}")

            except Exception as e:
                st.error(f"通信エラーが発生しました: {e}")

# 2. 自動反映されるフォーム項目
st.subheader("取得された顧客情報")

# セッション状態を初期値 (value) として設定
sname = st.text_input("顧客担当者名", value=st.session_state["sname"])
cname = st.text_input("顧客名", value=st.session_state["cname"])
scode = st.text_input("納品書印字顧客コード", value=st.session_state["scode"])
