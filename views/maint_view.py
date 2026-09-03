"""メンテナンス業務画面の入口。商品発注／ルート変更／契約内容変更をボタンで切り替える。"""
import streamlit as st

from views.route_view import render_route_change_tabs, ROUTE_COL, ROUTE_TARGET_SHEET_CSV, ROUTE_DEST_SHEET_CSV
from views.contract_view import render_contract_change_tabs, CC_COL, CC_TARGET_SHEET_CSV, CC_DEST_SHEET_CSV
from views.order_view import (
    render_product_order_tabs, TARGET_SHEET_CSV as ORDER_TARGET_SHEET_CSV,
    DEST_SHEET_CSV as ORDER_DEST_SHEET_CSV,
    CHECK_TIME_COL_IDX as ORDER_CHECK_TIME_COL_IDX, PRINT_TIME_COL_IDX as ORDER_PRINT_TIME_COL_IDX,
)
from views.spot_route_view import render_spot_route_change_tabs, SR_COL, SR_TARGET_SHEET_CSV, SR_DEST_SHEET_CSV
from views.delivery_qty_view import render_delivery_qty_change_tabs, DQ_COL, DQ_TARGET_SHEET_CSV, DQ_DEST_SHEET_CSV
from views.customer_balance_view import (
    render_customer_balance_correction_tabs, KZ_COL, KZ_TARGET_SHEET_CSV, KZ_DEST_SHEET_CSV,
)
from views.period_stop_view import render_period_stop_tabs, PS_COL, PS_TARGET_SHEET_CSV, PS_DEST_SHEET_CSV
from views.other_view import render_other_maintenance_tabs, OT_COL, OT_TARGET_SHEET_CSV, OT_DEST_SHEET_CSV
from views.cancel_view import render_cancel_tabs, CX_COL, CX_TARGET_SHEET_CSV, CX_DEST_SHEET_CSV
from views.maint_common import mode_has_pending_work

# 商品発注は他モードと違い列インデックスの辞書（*_COL）を持たないため、生のインデックス
# （TARGET_SHEET側のステータス列は30列目固定）をここで直接指定する
ORDER_STATUS_COL_IDX = 30

# 💡 メンテナンス業務トップの6モードボタン：各モードに「対応待ちのデータ」が残っている場合は
#    ボタンの枠を赤くして目立たせ、残っていない場合は通常の見た目（赤枠なし）に戻す。
#    「対応待ち」の判定はモードごとの一連のワークフロー（差戻し／承認待ち／業務転記待ち／
#    チェック待ち／印刷待ち）をまとめて見るmode_has_pending_work()で行う（60秒キャッシュ）。
MODE_DEFS = [
    ("order", "📦 商品発注", ORDER_TARGET_SHEET_CSV, ORDER_DEST_SHEET_CSV,
     ORDER_STATUS_COL_IDX, ORDER_CHECK_TIME_COL_IDX, ORDER_PRINT_TIME_COL_IDX),
    ("route", "🗺️ ルート変更", ROUTE_TARGET_SHEET_CSV, ROUTE_DEST_SHEET_CSV,
     ROUTE_COL["status_sign"], ROUTE_COL["check_time"], ROUTE_COL["print_time"]),
    ("sroute", "🔄 単発ルート変更", SR_TARGET_SHEET_CSV, SR_DEST_SHEET_CSV,
     SR_COL["status_sign"], SR_COL["check_time"], SR_COL["print_time"]),
    ("dq", "🔢 納品数量変更", DQ_TARGET_SHEET_CSV, DQ_DEST_SHEET_CSV,
     DQ_COL["status_sign"], DQ_COL["check_time"], DQ_COL["print_time"]),
    ("kz", "🧾 客中残訂正", KZ_TARGET_SHEET_CSV, KZ_DEST_SHEET_CSV,
     KZ_COL["status_sign"], KZ_COL["check_time"], KZ_COL["print_time"]),
    ("ps", "🛑 期間ストップ", PS_TARGET_SHEET_CSV, PS_DEST_SHEET_CSV,
     PS_COL["status_sign"], PS_COL["check_time"], PS_COL["print_time"]),
    ("cc", "📋 契約内容変更", CC_TARGET_SHEET_CSV, CC_DEST_SHEET_CSV,
     CC_COL["status_sign"], CC_COL["check_time"], CC_COL["print_time"]),
    ("ot", "📮 その他", OT_TARGET_SHEET_CSV, OT_DEST_SHEET_CSV,
     OT_COL["status_sign"], OT_COL["check_time"], OT_COL["print_time"]),
    ("cx", "🚫 解約", CX_TARGET_SHEET_CSV, CX_DEST_SHEET_CSV,
     CX_COL["status_sign"], CX_COL["check_time"], CX_COL["print_time"]),
]


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

    # 💡 各モードに対応待ちのデータが残っているかどうかをまとめて判定
    #    （読み込みに失敗したモードは「対応待ちなし」扱いにして、赤枠が出ないだけにする）
    pending_modes = set()
    for mode_key, _label, target_csv, dest_csv, status_col, check_col, print_col in MODE_DEFS:
        try:
            if mode_has_pending_work(target_csv, dest_csv, status_col, check_col, print_col):
                pending_modes.add(mode_key)
        except Exception:
            pass

    # 💡 対応待ちがあるモードのボタンだけ、枠を赤くするCSSを動的に追加する
    #    （st.container(key=...)で各ボタンをラップし、そのラッパーに付くst-key-<key>クラスを
    #    ピンポイントで狙う。対応待ちが無いモードは通常のボタンの見た目のまま＝赤枠は出さない）
    if pending_modes:
        pending_css = "\n".join(
            f'div.st-key-modebtn_{m} button {{ '
            f'border: 3px solid #e53935 !important; '
            f'box-shadow: 0 0 0 1px #e53935 !important; }}'
            for m in pending_modes
        )
        st.markdown(f"<style>{pending_css}</style>", unsafe_allow_html=True)

    # 💡 ボタンのクリックはそれ自体で自動的に再実行(rerun)がかかるため、
    #    ここでさらに st.rerun() を呼ぶと「再実行の中でもう一度再実行」が発生し、
    #    画面切り替え時にまれにブラウザ側でDOM操作エラー(NotFoundError: removeChild)が
    #    起きることがあった。on_clickコールバックで状態更新を「再実行が始まる前」に
    #    済ませることで、st.rerun()を使わずに1回の再実行だけで済むようにした。
    mode_cols = st.columns(len(MODE_DEFS))
    for (mode_key, label, *_rest), col in zip(MODE_DEFS, mode_cols):
        with col.container(key=f"modebtn_{mode_key}"):
            st.button(
                label, use_container_width=True,
                type="primary" if st.session_state["maint_mode"] == mode_key else "secondary",
                on_click=_set_maint_mode, args=(mode_key,),
                key=f"modebtn_click_{mode_key}",
            )

    st.write("---")

    if st.session_state["maint_mode"] == "order":
        render_product_order_tabs()
    elif st.session_state["maint_mode"] == "route":
        render_route_change_tabs()
    elif st.session_state["maint_mode"] == "sroute":
        render_spot_route_change_tabs()
    elif st.session_state["maint_mode"] == "dq":
        render_delivery_qty_change_tabs()
    elif st.session_state["maint_mode"] == "kz":
        render_customer_balance_correction_tabs()
    elif st.session_state["maint_mode"] == "ps":
        render_period_stop_tabs()
    elif st.session_state["maint_mode"] == "ot":
        render_other_maintenance_tabs()
    elif st.session_state["maint_mode"] == "cx":
        render_cancel_tabs()
    else:
        render_contract_change_tabs()

# アプリ実行
if __name__ == "__main__":
    st.set_page_config(page_title="メンテナンス申請管理システム", layout="wide")
    maintenance_admin_screen()
