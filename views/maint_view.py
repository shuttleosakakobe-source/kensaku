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

    def _set_maint_mode(mode):
        st.session_state["maint_mode"] = mode

    # 💡 ボタンのクリックはそれ自体で自動的に再実行(rerun)がかかるため、
    #    ここでさらに st.rerun() を呼ぶと「再実行の中でもう一度再実行」が発生し、
    #    画面切り替え時にまれにブラウザ側でDOM操作エラー(NotFoundError: removeChild)が
    #    起きることがあった。on_clickコールバックで状態更新を「再実行が始まる前」に
    #    済ませることで、st.rerun()を使わずに1回の再実行だけで済むようにした。
    b_order, b_route, b_cc = st.columns(3)
    b_order.button("📦 商品発注", use_container_width=True,
                   type="primary" if st.session_state["maint_mode"] == "order" else "secondary",
                   on_click=_set_maint_mode, args=("order",))
    b_route.button("🗺️ ルート変更", use_container_width=True,
                   type="primary" if st.session_state["maint_mode"] == "route" else "secondary",
                   on_click=_set_maint_mode, args=("route",))
    b_cc.button("📋 契約内容変更", use_container_width=True,
                type="primary" if st.session_state["maint_mode"] == "cc" else "secondary",
                on_click=_set_maint_mode, args=("cc",))

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
