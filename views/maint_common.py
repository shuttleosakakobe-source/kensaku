"""メンテナンス業務（商品発注／ルート変更／契約内容変更）で共通して使う定数・ヘルパー関数。
route_view.py / contract_view.py / order_view.py から読み込まれる。"""
import streamlit as st
import pandas as pd
import requests
import json
import os
import re
from datetime import timezone, timedelta, datetime, date


GAS_URL = "https://script.google.com/macros/s/AKfycbwvdmyHj_VgN_Q8azYypr82zyOk8p-j2wObG1rtvGTbpkeMWtMPAmkKqmfb11xDM09Rtg/exec"
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"
CUSTOMER_MASTER_SHEET_URL = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/edit?gid=127347205#gid=127347205"

# ご契約データ（顧客コードごとの契約週・曜日・担当者コードからルートコードを計算するための参照シート）
CONTRACT_DATA_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=2011677989"
CONTRACT_DATA_SHEET_URL = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/edit?gid=2011677989#gid=2011677989"

# ご契約データシートの列（0始まり）：顧客コード(A)=0、担当者コード(E)=4、担当者名(F)=5、曜日(G)=6、契約週M/N/O/P=12/13/14/15
CONTRACT_COL_CUST_CODE = 0
CONTRACT_WEEK_COLS = [12, 13, 14, 15]  # M, N, O, P → 週1, 週2, 週3, 週4

# ルート担当表（日付 × 担当者のマトリクス。A列=日付、B列=曜日、C列=基本ルート、
# D列以降＝担当者ごとの列で、見出しがその人の氏名、セルの値がその日その人が担当する
# 実際のルートコード）。管理職チェックで、申請のルートコード・納品日・担当者が
# この表と一致しているかを確認するために使う。
ROUTE_ROSTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=1244262789"
ROUTE_ROSTER_STAFF_COL_START = 3  # D列（0始まり）から担当者ごとの列が始まる

# TAB5用：加盟店別 印刷フォーマットのスプレッドシート（DEST_SHEET_URLとは別シート／gidが違う点に注意）
PRINT_SHEET_ID = "1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI"


def build_print_pdf_url(row_end=46, col_end=5, gid=None):
    """印刷フォーマットシートのA1〜(row_end, col_end)の範囲をPDFとして書き出すURLを作る
    （row_end/col_endは0始まりの終端。col_end=5はA〜E列を含む。
    gidは呼び出し側（商品発注はPRINT_SHEET_GID、ルート変更はROUTE_PRINT_SHEET_GID、
    契約内容変更はCC_PRINT_SHEET_GID）が明示的に渡す）"""
    params = {
        "format": "pdf",
        "gid": gid,
        "size": "A4",
        "portrait": "true",
        "fitw": "true",
        "top_margin": "0.4",
        "bottom_margin": "0.4",
        "left_margin": "0.4",
        "right_margin": "0.4",
        "sheetnames": "false",
        "printtitle": "false",
        "pagenumbers": "false",
        "gridlines": "false",
        "fzr": "false",
        "horizontal_alignment": "CENTER",
        "vertical_alignment": "TOP",
        "r1": "0",
        "c1": "0",
        "r2": str(row_end),
        "c2": str(col_end),
    }
    query = "&".join(f"{k}={v}" for k, v in params.items())
    return f"https://docs.google.com/spreadsheets/d/{PRINT_SHEET_ID}/export?{query}"

# 日本時間（JST = UTC+9）のタイムゾーン定義
JST = timezone(timedelta(hours=+9), 'JST')


def post_to_gas(payload):
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(GAS_URL, data=json.dumps(payload), headers=headers, timeout=30)
        return response.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@st.cache_data(ttl=15)
def read_csv_cached(url, **kwargs):
    """Google SheetsのCSVをキャッシュ付きで読み込む共通ヘルパー。
    同じURLへの読み込みが短時間に何度も走らないよう、既定で15秒キャッシュする
    （各画面が毎回 st.cache_data.clear() でアプリ全体のキャッシュを巻き添えにして
    いたのを、この関数専用のキャッシュに置き換えることで解消する）。
    承認・差戻し・削除・転記など自分の操作の直後で確実に最新データが欲しい場合は、
    read_csv_cached.clear() を呼んでからこの関数を呼び出す。"""
    return pd.read_csv(url, dtype=str, **kwargs)


def get_anthropic_client():
    """Streamlit CloudのSecrets（st.secrets["ANTHROPIC_API_KEY"]）または環境変数
    ANTHROPIC_API_KEY からAPIキーを読み込み、Anthropicクライアントを返す。
    キーが設定されていない・anthropicパッケージが無い場合はNoneを返し、
    呼び出し側でAIチェック機能を静かに無効化できるようにする
    （＝キー未設定でもアプリ全体は今まで通り動く）。"""
    api_key = None
    try:
        api_key = st.secrets.get("ANTHROPIC_API_KEY")
    except Exception:
        pass
    if not api_key:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def ai_check_order_anomaly(cust_code, cust_name, items, past_items_list):
    """商品発注の申請内容をAIでチェックし、異常（数量・単価の急激な変化や桁間違いなど）が
    無いかを判定する。
    items: 今回の申請の商品リスト [{"code":..., "qty":..., "price":...}, ...]
    past_items_list: 同じ顧客の過去の発注履歴（新しい順、最大5件）のリスト
    戻り値: {"checked": bool, "has_anomaly": bool, "reason": str}
    - checked=False（APIキー未設定など）の場合は has_anomaly=False とし、
      これまで通り人がチェックする（AI機能が無効なだけで、動作は変わらない）。
    - APIは呼べたが失敗した場合は、安全側に倒して has_anomaly=True とし、
      必ず人の目を通す（＝エラー時に誤って自動承認しない）。"""
    client = get_anthropic_client()
    if client is None:
        return {"checked": False, "has_anomaly": False, "reason": ""}

    prompt = (
        "あなたは配送業務システムの商品発注申請をチェックするアシスタントです。\n"
        "以下の今回の申請内容を、同じ顧客の過去の発注履歴と比較し、"
        "数量や単価に大きな異常（急激な増減、桁の間違いと思われる値など）が無いか確認してください。\n\n"
        f"【今回の申請】\n顧客: {cust_name}（{cust_code}）\n商品: {items}\n\n"
        f"【過去の発注履歴（新しい順、最大5件）】\n{past_items_list}\n\n"
        "異常があれば has_anomaly を true にし、reason に日本語で簡潔な理由（1〜2文）を書いてください。"
        "異常が無ければ has_anomaly は false、reason は空文字にしてください。"
        "過去の履歴が無い場合は、判断材料が無いため has_anomaly は false としてください。"
        "他の説明文は一切含めず、必ず次のJSON形式のみで回答してください:\n"
        '{"has_anomaly": true または false, "reason": "..."}'
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        result = json.loads(text)
        return {
            "checked": True,
            "has_anomaly": bool(result.get("has_anomaly")),
            "reason": str(result.get("reason", "")),
        }
    except Exception as e:
        return {
            "checked": True,
            "has_anomaly": True,
            "reason": f"AIチェックでエラーが発生したため、念のため内容をご確認ください（{e}）",
        }


def check_route_roster_match(delivery_date_str, route_code, staff_name):
    """申請のルートコード・納品日・担当者が、ルート担当表（ROUTE_ROSTER_CSV）の
    内容と一致しているかを確認する。
    戻り値: (matched, detail)
    - matched=True: 担当表の記載と一致
    - matched=False: 担当表の記載と食い違っている（＝明確な異常として扱ってよい）
    - matched=None: 担当表が読み込めない／該当する日付や担当者の列が無いなど、
      判定できなかった場合。判定不能なだけなので、呼び出し側では「異常あり」には
      しない（担当表の氏名表記ゆれ等で毎回引っかかってしまうのを避けるため）。
    シートに年の記載が無い（"10/1"のような月日のみ）ため、月日だけで日付を照合する。
    """
    try:
        df = read_csv_cached(ROUTE_ROSTER_CSV, header=None)
    except Exception as e:
        return None, f"担当表の読み込みに失敗しました（{e}）"

    if df.empty or len(df) < 2:
        return None, "担当表にデータがありません"

    header = df.iloc[0]
    staff_col = None
    for col_idx in range(ROUTE_ROSTER_STAFF_COL_START, len(header)):
        name = str(header.iloc[col_idx]).strip() if pd.notna(header.iloc[col_idx]) else ""
        if name and name == str(staff_name).strip():
            staff_col = col_idx
            break
    if staff_col is None:
        return None, f"担当表に「{staff_name}」の列が見つかりません"

    parsed_target = pd.to_datetime(str(delivery_date_str), errors="coerce")
    if pd.isna(parsed_target):
        return None, "納品日の形式を解釈できませんでした"

    for row_idx in range(1, len(df)):
        parsed_row = pd.to_datetime(str(df.iloc[row_idx, 0]), errors="coerce")
        if pd.isna(parsed_row):
            continue
        if (parsed_row.month, parsed_row.day) != (parsed_target.month, parsed_target.day):
            continue

        cell = df.iloc[row_idx, staff_col] if staff_col < df.shape[1] else None
        sheet_route = str(cell).strip() if pd.notna(cell) else ""
        if not sheet_route:
            return False, f"担当表では{staff_name}さんは{delivery_date_str}の割り当てがありません"
        if sheet_route == str(route_code).strip():
            return True, ""
        return False, f"担当表では{delivery_date_str}の{staff_name}さんのルートは「{sheet_route}」です（申請は「{route_code}」）"

    return None, f"担当表に{delivery_date_str}のデータが見つかりません"


def get_route_dates_for_code(route_code):
    """ルート担当表（ROUTE_ROSTER_CSV）から、指定したルートコードが登場する日付を
    すべて探して返す。申請入力時に、ルートコードを入力したら「納品日」「次回訪問日」
    「変更後日付」をプルダウンで選べるようにするために使う。
    ルートは数週間おきに巡回するため、同じコードが複数の日付に登場することがある
    （例: 「14008」が10/1にも10/29にも出てくる）。その場合は見つかった日付を全て返す。
    担当表には月日しか書かれていないため、今日以降で一番近い月日になるよう年を
    補ってから YYYY/MM/DD 形式の文字列にする。
    戻り値: 日付文字列のリスト（古い順）。コード未入力・見つからない・読み込めない
    場合は空リスト（呼び出し側では、空ならプルダウンではなく通常の日付入力に戻す）。"""
    route_code = str(route_code).strip()
    if not route_code:
        return []
    try:
        df = read_csv_cached(ROUTE_ROSTER_CSV, header=None)
    except Exception:
        return []
    if df.empty or len(df) < 2:
        return []

    today = datetime.now(JST).date()
    found_dates = set()

    for row_idx in range(1, len(df)):
        row = df.iloc[row_idx]
        matched = any(
            pd.notna(row.iloc[col_idx]) and str(row.iloc[col_idx]).strip() == route_code
            for col_idx in range(ROUTE_ROSTER_STAFF_COL_START, len(row))
        )
        if not matched:
            continue

        parsed = pd.to_datetime(str(row.iloc[0]), errors="coerce")
        if pd.isna(parsed):
            continue

        # 年の補完：今日より前になってしまう月日は来年扱いにする
        try:
            candidate = date(today.year, parsed.month, parsed.day)
        except ValueError:
            continue
        if candidate < today:
            try:
                candidate = date(today.year + 1, parsed.month, parsed.day)
            except ValueError:
                continue
        found_dates.add(candidate)

    return [d.strftime("%Y/%m/%d") for d in sorted(found_dates)]


@st.cache_data(ttl=60)
def mode_has_pending_work(target_csv, dest_csv, status_col, check_col, print_col):
    """あるモード（商品発注／ルート変更／単発ルート変更／納品数量変更／客中残訂正／契約内容変更）に、
    誰かの対応待ちのデータが残っているかどうかを判定する（メンテナンス業務トップのボタンの
    赤枠表示用）。以下のいずれかに該当すれば「処理が残っている」とみなす：
    - TARGET側（TAB1・2用シート）：差戻し（要再修正・再申請）／申請中（要承認）／
      承認済みだが未転記（要業務転記＝TAB3の対象）
    - DEST側（TAB3・4用シート）：チェック未完了（要チェック＝TAB4の対象）／
      チェック済みだが未印刷（要印刷＝TAB5の対象）
    読み込みエラー時は「処理待ちなし」扱いとする（ボタン表示のためだけにトップ画面全体が
    落ちないようにするため）。"""
    try:
        df_t = pd.read_csv(target_csv, dtype=str)
        if not df_t.empty and len(df_t.columns) > status_col:
            status_series = df_t.iloc[:, status_col].astype(str).str.strip()
            if (status_series == "差戻し").any():
                return True
            if (status_series == "申請中").any():
                return True
            pending_transfer = (
                (~df_t.iloc[:, status_col].isna()) &
                (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
            )
            if pending_transfer.any():
                return True
    except Exception:
        pass

    try:
        df_d = pd.read_csv(dest_csv, dtype=str)
        if not df_d.empty:
            if len(df_d.columns) > check_col:
                unchecked = df_d.iloc[:, check_col].fillna("").astype(str).str.strip() == ""
                if unchecked.any():
                    return True
            if len(df_d.columns) > print_col and len(df_d.columns) > check_col:
                checked = df_d.iloc[:, check_col].fillna("").astype(str).str.strip() != ""
                not_printed = df_d.iloc[:, print_col].fillna("").astype(str).str.strip() == ""
                if (checked & not_printed).any():
                    return True
    except Exception:
        pass

    return False



# --- 権限ごとのタブ表示制御 ---
# 権限0＝全タブ表示、権限1＝TAB1・TAB2のみ、権限2＝TAB1のみ、権限3＝TAB3・4・5のみ
# TAB6（🔍 過去の申請検索）は、承認・処理が完了した過去データを検索するだけの
# 読み取り専用機能のため、権限に関わらず全ユーザーに表示する。
# 権限の値は、ログイン時（app.py）にユーザーマスターシート（F列）から取得され
# st.session_state["user_role"] にセットされているものをそのまま使う。
ROLE_TAB_ACCESS = {
    "0": {1, 2, 3, 4, 5, 6},
    "1": {1, 2, 6},
    "2": {1, 6},
    "3": {3, 4, 5, 6},
}

RESTRICTED_TAB_MSG = "🔒 この機能は現在の権限では表示できません。"


def get_current_role():
    """ログイン中のユーザーの権限（app.pyのログイン処理でユーザーマスターF列から
    取得され st.session_state["user_role"] にセットされたもの）を返す。
    未ログイン等で値が無い場合は安全側として"0"（全権限）扱いにする。
    シート側の読み込み方によっては数値列が"2.0"のような文字列になってしまう
    ことがあるため、念のため前後の空白除去と末尾".0"の除去で正規化する。"""
    role = st.session_state.get("user_role", "0")
    role = str(role).strip()
    if role.endswith(".0"):
        role = role[:-2]
    return role


def tab_visible(tab_no):
    """指定タブ番号（1〜6）が現在の権限で表示可能かどうかを返す。
    未知の権限値の場合は安全側（全タブ表示）にフォールバックする。"""
    role = str(get_current_role())
    return tab_no in ROLE_TAB_ACCESS.get(role, {1, 2, 3, 4, 5, 6})


def _load_contract_df():
    """ご契約データシートを読み込む（read_csv_cachedにより短時間キャッシュされる）"""
    try:
        df_contract = read_csv_cached(CONTRACT_DATA_CSV, storage_options={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return None
    if df_contract.empty:
        return None
    return df_contract
