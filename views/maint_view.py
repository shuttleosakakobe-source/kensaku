"""メンテナンス業務画面の入口。商品発注／ルート変更／契約内容変更をボタンで切り替える。"""
import streamlit as st

from views.route_view import render_route_change_tabs
from views.contract_view import render_contract_change_tabs
from views.order_view import render_product_order_tabs

def maintenance_admin_screen():
    """メンテナンス画面の入口。商品発注／ルート変更／契約内容変更をボタンで切り替えて、それぞれのタブ一式を表示する"""
    st.markdown("#### 📦🗺️📋 メンテナンス業務")

    if "maint_mode" not in st.session_state:
        st.session_state["maint_mode"] = "order"

    b_order, b_route, b_cc = st.columns(3)
    if b_order.button("📦 商品発注", use_container_width=True,
                       type="primary" if st.session_state["maint_mode"] == "order" else "secondary"):
        st.session_state["maint_mode"] = "order"
        st.rerun()
    if b_route.button("🗺️ ルート変更", use_container_width=True,
                       type="primary" if st.session_state["maint_mode"] == "route" else "secondary"):
        st.session_state["maint_mode"] = "route"
        st.rerun()
    if b_cc.button("📋 契約内容変更", use_container_width=True,
                    type="primary" if st.session_state["maint_mode"] == "cc" else "secondary"):
        st.session_state["maint_mode"] = "cc"
        st.rerun()

    st.write("---")

    if st.session_state["maint_mode"] == "order":
        render_product_order_tabs()
    elif st.session_state["maint_mode"] == "route":
        render_route_change_tabs()
    else:
        render_contract_change_tabs()

# アプリ実行
if __name__ == "__main__":
    st.set_page_config(page_title="メンテナンス申請管理システム", layout="wide")
    maintenance_admin_screen()
