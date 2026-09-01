"""メンテナンス業務画面の入口。商品発注／ルート変更／契約内容変更をボタンで切り替える。"""
import streamlit as st

from views.route_view import render_route_change_tabs
from views.contract_view import render_contract_change_tabs
from views.order_view import render_product_order_tabs
from views.spot_route_view import render_spot_route_change_tabs
from views.delivery_qty_view import render_delivery_qty_change_tabs

def maintenance_admin_screen():
    """メンテナンス画面の入口。商品発注／ルート変更／契約内容変更をボタンで切り替えて、それぞれのタブ一式を表示する"""
    # 💡 【文字サイズ調整】メンテナンス業務画面全体（商品発注／ルート変更／単発ルート変更／
    #    納品数量変更／契約内容変更の全モード共通）の文字を大きくする。
    #    ここ（画面の一番最初）で読み込むことで、以降どのモードに切り替えても効き続ける。
    st.markdown("""
        <style>
        html, body, [class*="css"] {
            font-size: 18px !important;
        }
        div[data-testid="stMarkdownContainer"] p,
        div[data-testid="stMarkdownContainer"] li,
        div[data-testid="stMarkdownContainer"] span,
        div[data-testid="stWidgetLabel"] p,
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea,
        div[data-testid="stNumberInput"] input,
        div[data-testid="stDateInput"] input,
        div[data-testid="stSelectbox"] div[data-baseweb="select"] *,
        div[data-testid="stCaptionContainer"] p,
        div[data-testid="stExpander"] summary p,
        div[data-testid="stExpander"] summary span,
        button p,
        div[data-testid="stTabs"] button p,
        div[data-testid="stAlert"] p,
        div[data-testid="stMetricValue"],
        div[data-testid="stMetricLabel"],
        div[data-testid="stDataFrame"] {
            font-size: 1.15rem !important;
        }
        h1 { font-size: 2rem !important; }
        h2 { font-size: 1.6rem !important; }
        h3, h4 { font-size: 1.3rem !important; }
        </style>
    """, unsafe_allow_html=True)

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
    b_order, b_route, b_sroute, b_dq, b_cc = st.columns(5)
    b_order.button("📦 商品発注", use_container_width=True,
                   type="primary" if st.session_state["maint_mode"] == "order" else "secondary",
                   on_click=_set_maint_mode, args=("order",))
    b_route.button("🗺️ ルート変更", use_container_width=True,
                   type="primary" if st.session_state["maint_mode"] == "route" else "secondary",
                   on_click=_set_maint_mode, args=("route",))
    b_sroute.button("🔄 単発ルート変更", use_container_width=True,
                     type="primary" if st.session_state["maint_mode"] == "sroute" else "secondary",
                     on_click=_set_maint_mode, args=("sroute",))
    b_dq.button("🔢 納品数量変更", use_container_width=True,
                type="primary" if st.session_state["maint_mode"] == "dq" else "secondary",
                on_click=_set_maint_mode, args=("dq",))
    b_cc.button("📋 契約内容変更", use_container_width=True,
                type="primary" if st.session_state["maint_mode"] == "cc" else "secondary",
                on_click=_set_maint_mode, args=("cc",))

    st.write("---")

    if st.session_state["maint_mode"] == "order":
        render_product_order_tabs()
    elif st.session_state["maint_mode"] == "route":
        render_route_change_tabs()
    elif st.session_state["maint_mode"] == "sroute":
        render_spot_route_change_tabs()
    elif st.session_state["maint_mode"] == "dq":
        render_delivery_qty_change_tabs()
    else:
        render_contract_change_tabs()

# アプリ実行
if __name__ == "__main__":
    st.set_page_config(page_title="メンテナンス申請管理システム", layout="wide")
    maintenance_admin_screen()
