"""メンテナンス業務画面の入口。商品発注／ルート変更／契約内容変更をボタンで切り替える。"""
import streamlit as st
import time

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
from views.maint_common import (
    get_pending_modes, get_current_role,
    get_unconfirmed_staff_comments, confirm_staff_comment,
    read_csv_cached,
)
import pandas as pd
from views.navi_view import route_navigation_screen
from views.customer_contract_data_view import customer_contract_data_screen

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


def render_rejection_overview():
    """管理職・業務担当向け：9モード全てをまとめて見られる「差戻し一覧」。
    各モードのTARGET_SHEETから、差戻し（未処理）・差戻し後に再申請された（再送）・
    差戻し後に取り下げられた（削除）データを横断的に集めて1つの表に表示する。
    💡 「再送」「削除」の判定には、差し戻した管理職名を記録する列（status_col+3）が必要。
    現時点でこの列を使っているのは商品発注（order_view.py）のみなので、他モードは
    「未処理」（差戻しのまま）しか区別できない（再申請・取り下げ後は一覧から消える）。
    その列を持つモードが増えれば、このままで「再送」「削除」も自動的に区別されるようになる。"""
    st.markdown("#### 📋 差戻し一覧（全モード）")
    st.caption(
        "管理職チェックで差戻しとなった申請を、9モードまとめて確認できます。"
        "「再送」「削除」の区別は、現時点では商品発注のみ対応しています（他モードは差戻し中のもののみ表示されます）。"
    )

    status_filter = st.multiselect(
        "状況で絞り込み", ["未処理", "削除", "再送"],
        default=["未処理", "削除", "再送"], key="reject_overview_status_filter",
    )
    mode_labels = [label for _k, label, *_r in MODE_DEFS]
    mode_filter = st.multiselect(
        "モードで絞り込み", mode_labels, default=mode_labels, key="reject_overview_mode_filter",
    )

    records = []
    for mode_key, label, target_csv, _dest_csv, status_col, _check_col, _print_col in MODE_DEFS:
        if label not in mode_filter:
            continue
        try:
            df = read_csv_cached(target_csv)
        except Exception:
            continue
        if df is None or df.empty or len(df.columns) <= status_col:
            continue

        rejector_col = status_col + 3
        reject_date_col = status_col + 4
        approval_time_col = status_col + 1

        status_series = df.iloc[:, status_col].fillna("").astype(str).str.strip()
        if len(df.columns) > rejector_col:
            col_rejector = df.iloc[:, rejector_col].fillna("").astype(str).str.strip()
        else:
            col_rejector = pd.Series([""] * len(df), index=df.index)
        if len(df.columns) > reject_date_col:
            col_reject_date = df.iloc[:, reject_date_col].fillna("").astype(str).str.strip()
        else:
            col_reject_date = pd.Series([""] * len(df), index=df.index)

        is_unprocessed = status_series == "差戻し"
        is_resent = (status_series == "申請中") & (col_rejector != "")
        is_withdrawn = (status_series == "削除") & (col_rejector != "")
        target_df = df[is_unprocessed | is_resent | is_withdrawn]
        if target_df.empty:
            continue

        for idx, row in target_df.iterrows():
            st_val = status_series.loc[idx]
            if st_val == "差戻し":
                status_label = "未処理"
            elif st_val == "削除":
                status_label = "削除"
            else:
                status_label = "再送"
            if status_label not in status_filter:
                continue

            reject_date = col_reject_date.loc[idx]
            if not reject_date and st_val == "差戻し" and len(row) > approval_time_col and pd.notna(row.iloc[approval_time_col]):
                reject_date = str(row.iloc[approval_time_col])

            records.append({
                "差戻し日": reject_date,
                "担当者名": str(row.iloc[1]) if len(row) > 1 and pd.notna(row.iloc[1]) else "",
                "顧客名": str(row.iloc[3]) if len(row) > 3 and pd.notna(row.iloc[3]) else "",
                "メンテナンス種別": label,
                "差し戻した管理職": col_rejector.loc[idx],
                "現在の状況": status_label,
            })

    if not records:
        st.info("現在、差戻しデータはありません。")
        return

    result_df = pd.DataFrame(records)
    result_df["_sort"] = pd.to_datetime(result_df["差戻し日"], errors="coerce")
    result_df = result_df.sort_values(by="_sort", ascending=False, na_position="last").drop(columns="_sort")
    st.dataframe(result_df, use_container_width=True, hide_index=True)


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

    # 💡 業務担当（TAB3）からの連絡コメント通知：ログイン中のユーザーが申請者になっている
    #    未確認コメントがあれば、バッジを出して一覧・確認ボタンを表示する。
    unconfirmed_comments = get_unconfirmed_staff_comments(st.session_state.get("user_name", ""))
    if unconfirmed_comments:
        if "show_staff_comments" not in st.session_state:
            st.session_state["show_staff_comments"] = False

        def _toggle_staff_comments():
            st.session_state["show_staff_comments"] = not st.session_state["show_staff_comments"]

        st.button(
            f"🔔 業務担当からの未確認コメントが{len(unconfirmed_comments)}件あります（クリックで表示）",
            on_click=_toggle_staff_comments,
            use_container_width=True,
            type="primary",
            key="staff_comment_badge_btn",
        )

        if st.session_state["show_staff_comments"]:
            for _c in unconfirmed_comments:
                with st.container(border=True):
                    st.write(f"**{_c['mode_name']}** ｜ {_c['cust_name']}（{_c['cust_code']}） ｜ {_c['timestamp']}")
                    st.caption(f"記入者: {_c['staff_name']}")
                    st.write(_c["comment"])
                    if st.button("✅ 確認しました", key=f"confirm_staff_comment_{_c['row_index']}"):
                        _confirm_res = confirm_staff_comment(_c["row_index"])
                        if _confirm_res.get("status") == "success":
                            st.toast("確認しました！", icon="✅")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(f"確認処理に失敗しました: {_confirm_res.get('message')}")
        st.write("---")

    if "maint_mode" not in st.session_state:
        st.session_state["maint_mode"] = "order"

    def _set_maint_mode(mode):
        st.session_state["maint_mode"] = mode

    # 💡 ボタンのクリックはそれ自体で自動的に再実行(rerun)がかかるため、
    #    ここでさらに st.rerun() を呼ぶと「再実行の中でもう一度再実行」が発生し、
    #    画面切り替え時にまれにブラウザ側でDOM操作エラー(NotFoundError: removeChild)が
    #    起きることがあった。on_clickコールバックで状態更新を「再実行が始まる前」に
    #    済ませることで、st.rerun()を使わずに1回の再実行だけで済むようにした。
    # 💡 メンテナンス業務の9モードに加えて、以前はサイドバーにあった「🗺️ ナビ画面」と
    #    （権限0・3のみ）「🗂️ 顧客・契約データ管理」も、同じボタン行に並べて
    #    このメイン画面だけで全ての操作に入れるようにする（サイドバーのメニューは廃止）。
    extra_buttons = [("navi", "🗺️ ナビ画面")]
    if get_current_role() in ("0", "3"):
        extra_buttons.append(("cust_contract", "🗂️ 顧客・契約データ管理"))
    if get_current_role() in ("0", "1", "3"):
        extra_buttons.append(("reject_list", "📋 差戻し一覧"))

    all_buttons = [(mode_key, label) for mode_key, label, *_rest in MODE_DEFS] + extra_buttons

    # 💡 各モードボタンを、アイコンを丸背景に乗せたカード風の見た目にする。
    #    アイコン色はモードごとに割り当て、st.buttonのラベルを「アイコン行」「タイトル行」の
    #    2段落（空行区切り）にすることで、Streamlitが<p>タグを2つに分けて出力するのを利用し、
    #    1つ目の<p>（アイコン）だけに丸背景を、2つ目の<p>（タイトル）だけに太字を充てている。
    _mode_icon_colors = {
        "order": "#fdba74", "route": "#93c5fd", "sroute": "#5eead4", "dq": "#c4b5fd",
        "kz": "#fcd34d", "ps": "#fca5a5", "cc": "#d1d5db", "ot": "#fda4af", "cx": "#f87171",
        "navi": "#7dd3fc", "cust_contract": "#a3e635", "reject_list": "#fb923c",
    }
    # 💡 border/box-shadowは、下の「対応待ちモードは赤枠」CSS（同じ div.st-key-modebtn_<key> button
    #    セレクタ）と詳細度を揃えるため、あえて汎用セレクタではなく1モードずつ同じ形のセレクタで
    #    出力する（詳細度が異なると、後から出すはずの赤枠CSSが先に出したこちらに負けてしまうため）。
    #    ※ p:first-of-type / p:last-of-type のスタイルも必ず div.st-key-modebtn_<key> 配下に
    #    限定すること。汎用の div[data-testid="stHorizontalBlock"] button p... にすると、
    #    アプリ内の他の（st.columns内にある）普通のボタン全部に丸アイコン用の固定幅・中央寄せが
    #    誤って適用され、文字が丸の中に収まらず欠けて見える不具合が起きる
    #    （顧客データ・契約データ一括更新画面の「👤 顧客データ」ボタン等で実際に発生した）。
    card_css_parts = []
    for _mk, _color in _mode_icon_colors.items():
        card_css_parts.append(f"""
            div.st-key-modebtn_{_mk} button {{
                min-height: 118px !important;
                border-radius: 18px !important;
                border: none !important;
                background: #f4f6fa !important;
                box-shadow: 0 2px 8px rgba(15, 23, 42, 0.08) !important;
                transition: transform 0.12s ease, box-shadow 0.12s ease;
            }}
            div.st-key-modebtn_{_mk} button:hover {{
                transform: translateY(-2px);
                box-shadow: 0 6px 14px rgba(15, 23, 42, 0.16) !important;
            }}
            div.st-key-modebtn_{_mk} button p:first-of-type {{
                display: inline-flex; align-items: center; justify-content: center;
                width: 52px; height: 52px; border-radius: 50%;
                font-size: 24px; line-height: 1; margin: 0 auto 10px auto !important;
                background: {_color} !important;
            }}
            div.st-key-modebtn_{_mk} button p:last-of-type {{
                font-weight: 700; font-size: 1rem; color: #1f2937 !important; margin: 0 !important;
            }}
            div.st-key-modebtn_{_mk} button[data-testid="stBaseButton-primary"] {{
                background: #eef2ff !important;
                box-shadow: 0 0 0 3px #2563eb inset, 0 2px 8px rgba(15,23,42,0.08) !important;
            }}
        """)
    st.markdown(f"<style>{''.join(card_css_parts)}</style>", unsafe_allow_html=True)

    # 💡 各モードに対応待ちのデータが残っているかどうかをまとめて判定
    #    （読み込みに失敗したモードは「対応待ちなし」扱いにして、赤枠が出ないだけにする）
    #    9モード分のシート読み込みをget_pending_modes()内で並列化し、キャッシュが切れた
    #    直後でもボタン行の表示が長く待たされないようにしている。
    try:
        pending_modes = get_pending_modes(MODE_DEFS)
    except Exception:
        pending_modes = set()

    # 💡 対応待ちがあるモードのボタンだけ、枠を赤くするCSSを動的に追加する
    #    （st.container(key=...)で各ボタンをラップし、そのラッパーに付くst-key-<key>クラスを
    #    ピンポイントで狙う。対応待ちが無いモードは通常のボタンの見た目のまま＝赤枠は出さない。
    #    上のカード用CSSと詳細度が同じセレクタのため、これを後から出すことで確実に上書きする）
    if pending_modes:
        pending_css = "\n".join(
            f'div.st-key-modebtn_{m} button {{ '
            f'border: 3px solid #e53935 !important; '
            f'box-shadow: 0 0 0 1px #e53935 !important; }}'
            for m in pending_modes
        )
        st.markdown(f"<style>{pending_css}</style>", unsafe_allow_html=True)

    mode_cols = st.columns(len(all_buttons))
    for (mode_key, label), col in zip(all_buttons, mode_cols):
        icon, _sep, title = label.partition(" ")
        with col.container(key=f"modebtn_{mode_key}"):
            st.button(
                f"{icon}\n\n{title}", use_container_width=True,
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
    elif st.session_state["maint_mode"] == "cc":
        render_contract_change_tabs()
    elif st.session_state["maint_mode"] == "navi":
        route_navigation_screen()
    elif st.session_state["maint_mode"] == "cust_contract":
        customer_contract_data_screen()
    elif st.session_state["maint_mode"] == "reject_list":
        render_rejection_overview()
    else:
        render_contract_change_tabs()

# アプリ実行
if __name__ == "__main__":
    st.set_page_config(page_title="メンテナンス申請管理システム", layout="wide")
    maintenance_admin_screen()
