"""メンテナンス業務（商品発注／ルート変更／契約内容変更）で共通して使う定数・ヘルパー関数。
route_view.py / contract_view.py / order_view.py から読み込まれる。"""
import streamlit as st
import pandas as pd
import requests
import json
import os
import re
import concurrent.futures
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

# 業務担当コメント通知用シート（TAB3「業務担当」で、差戻しとは別に申請者への連絡コメントを
# 残せるようにするための共有シート。列（0始まり）：
# 0=タイムスタンプ, 1=モード名, 2=顧客コード, 3=顧客名, 4=申請者（通知先）,
# 5=コメント本文, 6=記入した業務担当者, 7=確認済みフラグ, 8=確認日時）
STAFF_COMMENT_SHEET_URL = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/edit?gid=876912853#gid=876912853"
STAFF_COMMENT_CSV = "https://docs.google.com/spreadsheets/d/1iiiCnlP0_wLgIJ092qiorb-Dj4O1GwNt_J9z92VXQNI/gviz/tq?tqx=out:csv&gid=876912853"

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


@st.cache_data(ttl=1800, show_spinner=False)
def ai_check_order_anomaly(cust_code, cust_name, items, past_items_list):
    """商品発注の申請内容をAIでチェックし、異常（数量・単価の急激な変化や桁間違いなど）が
    無いかを判定する。
    items: 今回の申請の商品リスト [{"code":..., "qty":..., "price":...}, ...]
    past_items_list: 同じ顧客の過去の発注履歴（新しい順、最大5件）のリスト
    戻り値: {"checked": bool, "has_anomaly": bool, "reason": str}
    - checked=False（APIキー未設定など）の場合は has_anomaly=False とし、
      これまで通り人がチェックする（AI機能が無効なだけで、動作は変わらない）。
    - APIは呼べたが失敗した場合は、安全側に倒して has_anomaly=True とし、
      必ず人の目を通す（＝エラー時に誤って自動承認しない）。
    st.cache_data で引数の内容（＝申請内容そのもの）ごとに結果をキャッシュする。
    これにより、以前はブラウザを再読み込みするたびに全件AI問い合わせをやり直して
    いたのが、同じ内容なら（TTL 30分の間は）アプリ全体で使い回されるようになり、
    管理職チェック画面を開くたびに数十秒待たされる、という遅さの主因を解消する。"""
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


def send_staff_comment(mode_name, cust_code, cust_name, applicant, comment, staff_name):
    """業務担当（TAB3）から、差戻しとは別に申請者への連絡コメントを送る。
    差戻しと違って申請のステータスは一切変更せず、共有のSTAFF_COMMENT_SHEETに
    1行追加するだけ（申請者側はメイン画面の通知バッジで気付いて確認する）。"""
    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    full_row = [now_str, mode_name, cust_code, cust_name, applicant, comment, staff_name, "", ""]
    return post_to_gas({
        "action": "SEND_STAFF_COMMENT",
        "target_sheet_url": STAFF_COMMENT_SHEET_URL,
        "full_row": full_row,
    })


def get_unconfirmed_staff_comments(user_name):
    """ログイン中のユーザーが申請者になっている、業務担当からの未確認コメントを
    新しい順に返す。戻り値: [{"row_index":..., "timestamp":..., "mode_name":...,
    "cust_code":..., "cust_name":..., "comment":..., "staff_name":...}, ...]"""
    if not user_name or not str(user_name).strip():
        return []
    try:
        df = read_csv_cached(STAFF_COMMENT_CSV, header=None)
    except Exception:
        return []
    if df.empty or len(df) < 2:
        return []

    results = []
    for row_idx in range(1, len(df)):
        row = df.iloc[row_idx]
        if len(row) < 8:
            continue
        row_applicant = str(row.iloc[4]).strip() if pd.notna(row.iloc[4]) else ""
        confirmed = str(row.iloc[7]).strip() if pd.notna(row.iloc[7]) else ""
        if confirmed or row_applicant != str(user_name).strip():
            continue
        results.append({
            "row_index": row_idx + 1,  # header行を含めたシート上の実際の行番号（1始まり）
            "timestamp": str(row.iloc[0]) if pd.notna(row.iloc[0]) else "",
            "mode_name": str(row.iloc[1]) if pd.notna(row.iloc[1]) else "",
            "cust_code": str(row.iloc[2]) if pd.notna(row.iloc[2]) else "",
            "cust_name": str(row.iloc[3]) if pd.notna(row.iloc[3]) else "",
            "comment": str(row.iloc[5]) if pd.notna(row.iloc[5]) else "",
            "staff_name": str(row.iloc[6]) if pd.notna(row.iloc[6]) else "",
        })
    results.reverse()
    return results


def confirm_staff_comment(row_index):
    """業務担当からの連絡コメントを「確認済み」にする。"""
    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")
    return post_to_gas({
        "action": "CONFIRM_STAFF_COMMENT",
        "target_sheet_url": STAFF_COMMENT_SHEET_URL,
        "row_index": row_index,
        "confirmed_time": now_str,
    })


def _fetch_csv_or_none(csv_url):
    """mode_has_pending_work / get_pending_modes 用のCSV読み込み。
    💡 read_csv_cached と同じキャッシュ（同じ関数・同じ引数）を使うことで、承認・
    チェック・印刷などの操作後に read_csv_cached.clear() が呼ばれれば、この関数の
    結果も自動的に最新化されるようにしている。
    以前はこの関数専用に別のキャッシュ（60秒）を持っていたため、TAB4でチェックを
    完了した直後でも、メインメニューの「未チェックあり」の赤枠が最大60秒古いままの
    データを見て表示され続けてしまう不具合があった。
    読み込みエラー時はNoneを返す（呼び出し側は「そちら側は判定不能＝処理待ちなし扱い」にする）。"""
    try:
        return read_csv_cached(csv_url)
    except Exception:
        return None


def _pending_reasons_from_dfs(df_t, df_d, status_col, check_col, print_col, applicant_col=1, *, user_role="", user_name=""):
    """あるモード（商品発注／ルート変更／単発ルート変更／納品数量変更／客中残訂正／契約内容変更）に、
    ログイン中のユーザー自身が対応すべき「対応待ち」のデータが残っているかどうかを、既に
    読み込み済みのDataFrameから判定する（メンテナンス業務トップのボタンの赤枠表示用）。
    💡 以前は会社全体のデータを見て、誰の・どの担当範囲の対応待ちでも無条件に赤枠にしていた
    （自分の管轄外の対応待ちでも赤枠が点いてしまっていた）。これを、対応待ちの種類ごとに
    「本来それに対応すべき人」にだけ赤枠が見えるよう絞り込む：
    - 差戻し（要再修正・再申請）：その申請の担当者（申請者）本人のみ
    - 申請中（要承認）：管理職（権限0・1）のみ
    - 承認済みだが未転記（要業務転記）／チェック未完了（要チェック）／
      チェック済みだが未印刷（要印刷）：業務担当（権限0・3）のみ
    権限0（全権限）は、どの種類の対応待ちでも対象として見る。
    💡 「ボタンが赤いのに、見ているTABには何も残っていない」という混乱が繰り返し起きたため、
    単純なTrue/Falseではなく、どの種類が・何件該当したかのリストを返すようにしている
    （例: ["差戻し1件", "未チェック2件"]）。空リスト＝対応待ちなし。
    読み込みエラー（df=None）時は「処理待ちなし」扱いとする（ボタン表示のためだけにトップ画面全体が
    落ちないようにするため）。"""
    role = str(user_role).strip()
    if role.endswith(".0"):
        role = role[:-2]
    is_all = role == "0"
    is_manager = role in {"0", "1"}
    is_operator = role in {"0", "3"}
    my_name = str(user_name).strip()

    reasons = []

    try:
        if df_t is not None and not df_t.empty and len(df_t.columns) > status_col:
            status_series = df_t.iloc[:, status_col].astype(str).str.strip()

            if is_all:
                cnt = int((status_series == "差戻し").sum())
                if cnt:
                    reasons.append(f"差戻し{cnt}件")
            elif my_name and len(df_t.columns) > applicant_col:
                applicant_series = df_t.iloc[:, applicant_col].astype(str).str.strip()
                my_rejected = (status_series == "差戻し") & (applicant_series == my_name)
                cnt = int(my_rejected.sum())
                if cnt:
                    reasons.append(f"差戻し{cnt}件")

            if is_manager:
                cnt = int((status_series == "申請中").sum())
                if cnt:
                    reasons.append(f"承認待ち{cnt}件")

            if is_operator:
                pending_transfer = (
                    (~df_t.iloc[:, status_col].isna()) &
                    (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
                )
                cnt = int(pending_transfer.sum())
                if cnt:
                    reasons.append(f"転記待ち{cnt}件")
    except Exception:
        pass

    try:
        if is_operator and df_d is not None and not df_d.empty:
            if len(df_d.columns) > check_col:
                unchecked = df_d.iloc[:, check_col].fillna("").astype(str).str.strip() == ""
                cnt = int(unchecked.sum())
                if cnt:
                    reasons.append(f"未チェック{cnt}件")
            if len(df_d.columns) > print_col and len(df_d.columns) > check_col:
                checked = df_d.iloc[:, check_col].fillna("").astype(str).str.strip() != ""
                not_printed = df_d.iloc[:, print_col].fillna("").astype(str).str.strip() == ""
                cnt = int((checked & not_printed).sum())
                if cnt:
                    reasons.append(f"未印刷{cnt}件")
    except Exception:
        pass

    return reasons


def _pending_flag_from_dfs(df_t, df_d, status_col, check_col, print_col, applicant_col=1, *, user_role="", user_name=""):
    """_pending_reasons_from_dfsの真偽値版（理由の内訳までは不要な呼び出し元用）。"""
    return bool(_pending_reasons_from_dfs(
        df_t, df_d, status_col, check_col, print_col, applicant_col,
        user_role=user_role, user_name=user_name,
    ))


# 理由の文言（_pending_reasons_from_dfsが返す文字列の先頭）と、タブ見出しの色分け
# （render_tab_header_pending_css）を揃えた対応表。差戻し（TAB1）だけは色の指定が
# 無いため、既存の赤をそのまま使う。
PENDING_REASON_COLORS = [
    ("差戻し", "#e53935"),
    ("承認待ち", "#f1c40f"),
    ("転記待ち", "#22c55e"),
    ("未チェック", "#e53935"),
    ("未印刷", "#ec4899"),
]


def pending_reason_color(reasons):
    """get_pending_modes()が返す理由リスト（例: ["差戻し1件", "未チェック2件"]）のうち、
    最も優先度の高い種類（差戻し＞承認待ち＞転記待ち＞未チェック＞未印刷の順。
    ワークフロー上、上流の未処理ほど先に解消すべきものとして優先している）の色を返す。
    メインメニューのモードボタンは1色しか枠を付けられないため、どれか1つに決める必要が
    あり、タブ見出しの色分け（render_tab_header_pending_css）と対応させている。
    reasonsが空、または知らない文言の場合は無難に既存の赤を返す。"""
    for reason in reasons:
        for prefix, color in PENDING_REASON_COLORS:
            if reason.startswith(prefix):
                return color
    return "#e53935"


def mode_has_pending_work(target_csv, dest_csv, status_col, check_col, print_col, applicant_col=1):
    """1モード分だけ対応待み判定が欲しい場合の単体版（内部は_fetch_csv_or_none/
    _pending_flag_from_dfsと共通）。9モードまとめて判定する場合はget_pending_modes()を使うこと。
    ログイン中のユーザー（st.session_state の user_role / user_name）を基準に絞り込む。"""
    df_t = _fetch_csv_or_none(target_csv)
    df_d = _fetch_csv_or_none(dest_csv)
    return _pending_flag_from_dfs(
        df_t, df_d, status_col, check_col, print_col, applicant_col,
        user_role=st.session_state.get("user_role", ""),
        user_name=st.session_state.get("user_name", ""),
    )


def render_section_pending_banner(label, count):
    """業務担当・全権限（権限0・3）向け：今開いているセクション（メンテナンス処理／
    メンテナンスチェック／印刷のいずれか）自身に未処理が残っている場合だけ、その場に
    赤枠で件数を表示する。
    💡 以前はメンテナンス業務トップ画面に3セクション分をまとめて表示していたが、
    「このセクションを開いているのに関係ない他のセクションの赤枠まで出る」のが
    分かりにくいという要望を受け、各セクション（TAB3・4・5）自身の中で、
    そのセクション自身の未処理件数だけを表示する方式に変更した。
    TAB3・4・5は元々tab_visible()で権限0・3にしか表示されないため、ここでは
    追加の権限チェックは行わない。呼び出し側がそのタブの本体から、既に読み込み・
    フィルタ済みのデータの件数を渡すだけでよい。"""
    if count <= 0:
        return
    st.markdown(
        f"<div style='border:3px solid #e53935;border-radius:10px;padding:8px 14px;"
        f"background:#fff5f5;margin-bottom:12px;color:#b91c1c;font-weight:600;'>"
        f"🔴 {label}で未処理が{count}件あります</div>",
        unsafe_allow_html=True,
    )


def handle_tab4_reject(
    row, row_id, reject_target, reject_reason, checker_name,
    col, target_sheet_csv, target_sheet_url, dest_sheet_url,
    reopen_action, applicant_reject_action, update_check_action,
):
    """TAB4（メンテナンスチェック画面）の「↩️ 指定先へ差戻し」共通処理。
    以前はボタンを押してもトーストが出るだけで実際には何も更新されず、
    差戻しが機能していなかった（データが一切書き込まれていなかった）ため追加。

    reject_target が「業務担当」の場合：TARGET_SHEET側の元の申請行を探し、
    ステータスを転記前の承認済み状態に戻す（status_sign列に元の承認者名を
    書き戻す）ことで、TAB3（業務担当メンテナンス処理）に再び表示されるように
    する。差戻し理由はTAB3でも見える「コメント」欄に追記する。

    reject_target が「申請者」の場合：TAB2の差戻しと同じ要領で、TARGET_SHEET側を
    status_sign="差戻し"・rejector_name・reject_date付きで更新し、TAB1（差戻し
    一覧）に表示されるようにする。

    いずれの場合もDEST_SHEET側の該当行はチェック済み扱い（check_time/check_user）
    にして、TAB4の未チェック一覧から外す。

    col: cust_code/timestamp/comment/status_sign/approval_time/approval_comment/
         rejector_name/reject_date/check_time/check_userの各列番号を持つdict。

    戻り値: (success: bool, message: str)
    """
    now_str = datetime.now(JST).strftime("%Y/%m/%d %H:%M:%S")

    def _v(col_key, r=row):
        i = col[col_key]
        return str(r.iloc[i]) if len(r) > i and pd.notna(r.iloc[i]) else ""

    cust_code = _v("cust_code")
    timestamp = _v("timestamp")

    df_target = read_csv_cached(target_sheet_csv)
    if df_target.empty or len(df_target.columns) <= col["status_sign"]:
        return False, "元データ（スタッフ用シート）が見つかりませんでした。"

    match_mask = (
        (df_target.iloc[:, col["cust_code"]].astype(str).str.strip() == cust_code) &
        (df_target.iloc[:, col["timestamp"]].astype(str).str.strip() == timestamp) &
        (df_target.iloc[:, col["status_sign"]].astype(str).str.strip() == "業務転記済")
    )
    matched = df_target[match_mask]
    if matched.empty:
        return False, "差戻し先の元データ（スタッフ用シート側の申請行）が見つかりませんでした。別の担当者が既に処理した可能性があります。"

    target_idx = matched.index[0]
    target_row_id = target_idx + 2
    target_row = matched.iloc[0]

    base_width = col["reject_date"] + 1
    base_row = [
        "" if pd.isna(target_row.iloc[i]) else str(target_row.iloc[i])
        for i in range(min(base_width, len(target_row)))
    ]
    while len(base_row) < base_width:
        base_row.append("")

    note = f"⚠️ メンテナンスチェックからの差戻し理由: {reject_reason}"

    if reject_target == "業務担当":
        # 💡 TARGET_SHEET側のstatus_signは転記時に既に「業務転記済」へ上書きされているため、
        #    元の承認者名はDEST_SHEET側（＝この関数に渡されたrow）のstatus_signから取る。
        mgr_name_val = _v("status_sign")
        orig_comment = base_row[col["comment"]] if col["comment"] < len(base_row) else ""
        base_row[col["comment"]] = f"{orig_comment}\n{note}" if orig_comment.strip() else note
        base_row[col["status_sign"]] = mgr_name_val
        action = reopen_action
    else:
        base_row[col["status_sign"]] = "差戻し"
        base_row[col["approval_time"]] = now_str
        base_row[col["approval_comment"]] = reject_reason
        base_row[col["rejector_name"]] = checker_name
        base_row[col["reject_date"]] = now_str
        action = applicant_reject_action

    payload = {
        "action": action,
        "target_sheet_url": target_sheet_url,
        "row_index": target_row_id,
        "updated_row": base_row,
    }
    res = post_to_gas(payload)
    if res.get("status") != "success":
        return False, f"差戻し失敗（元データの更新）: {res.get('message')}"

    check_row = ["" if pd.isna(row.iloc[i]) else str(row.iloc[i]) for i in range(len(row))]
    while len(check_row) < col["check_user"] + 1:
        check_row.append("")
    check_row[col["check_time"]] = now_str
    check_row[col["check_user"]] = f"↩️ 差戻し（{reject_target}）: {reject_reason}"

    check_payload = {
        "action": update_check_action,
        "target_sheet_url": dest_sheet_url,
        "row_index": row_id,
        "updated_row": check_row,
    }
    check_res = post_to_gas(check_payload)
    if check_res.get("status") != "success":
        return False, f"差戻し失敗（チェック画面側の更新）: {check_res.get('message')}"

    return True, f"【{reject_target}】へ差戻しを行いました（理由: {reject_reason}）"


def render_tab_header_pending_css(target_csv, dest_csv, status_col, check_col, print_col, tab_visible_nums):
    """TAB2（管理職チェック/承認待ち）=黄、TAB3（業務担当メンテナンス処理/転記待ち）=緑、
    TAB4（メンテナンスチェック/未チェック）=赤、TAB5（加盟店別印刷/未印刷）=ピンクで、
    それぞれ未処理がある場合だけ、そのタブの見出し（st.tabsのタブボタン自体）に
    色付きの枠をつける。render_section_pending_bannerはタブの中身に出す文言、
    こちらはタブを開く前から見出し自体の色でひと目でわかるようにするためのもの。
    💡 st.tabsの各タブは個別のkeyを持てずCSSで直接狙えないため、実際に表示されている
    タブ番号の並び順（tab_visible_nums＝tab_visible()でフィルタ済みのもの）から、
    何番目のタブボタンか（nth-child）を逆算して当てる。権限によって表示されるタブの
    数・順番が変わるため、呼び出し側は必ずそのモードで実際に使っているtab_visible_nums
    をそのまま渡すこと。st.tabs()を呼ぶ「前」に呼び出す必要がある
    （タブの見出しが描画される前にスタイルを注入しておくため）。"""
    df_t = _fetch_csv_or_none(target_csv)
    df_d = _fetch_csv_or_none(dest_csv)

    pending = {2: False, 3: False, 4: False, 5: False}
    try:
        if df_t is not None and not df_t.empty and len(df_t.columns) > status_col:
            status_series = df_t.iloc[:, status_col].astype(str).str.strip()
            pending[2] = bool((status_series == "申請中").any())
            pending_transfer = (
                (~df_t.iloc[:, status_col].isna()) &
                (~status_series.isin(["", "申請中", "差戻し", "削除", "業務転記済", "nan"]))
            )
            pending[3] = bool(pending_transfer.any())
    except Exception:
        pass

    try:
        if df_d is not None and not df_d.empty:
            if len(df_d.columns) > check_col:
                pending[4] = bool((df_d.iloc[:, check_col].fillna("").astype(str).str.strip() == "").any())
            if len(df_d.columns) > print_col and len(df_d.columns) > check_col:
                checked = df_d.iloc[:, check_col].fillna("").astype(str).str.strip() != ""
                not_printed = df_d.iloc[:, print_col].fillna("").astype(str).str.strip() == ""
                pending[5] = bool((checked & not_printed).any())
    except Exception:
        pass

    colors = {2: "#f1c40f", 3: "#22c55e", 4: "#e53935", 5: "#ec4899"}
    css_parts = []
    for tab_no, color in colors.items():
        if not pending[tab_no] or tab_no not in tab_visible_nums:
            continue
        position = tab_visible_nums.index(tab_no) + 1
        # 💡 :nth-child ではなく :nth-of-type を使う。st.tabsのタブ一覧
        # （div[data-baseweb="tab-list"]）には、選択中タブの下線などを描画する
        # button以外の要素が混ざることがあり、:nth-childだと数がずれて
        # 別のタブに色が付いてしまう不具合があった。:nth-of-typeなら
        # button要素だけを数えるため、このズレが起きない。
        css_parts.append(
            f'div[data-baseweb="tab-list"] button[data-baseweb="tab"]:nth-of-type({position}) {{'
            f' border: 3px solid {color} !important;'
            f' border-radius: 6px !important;'
            f' box-shadow: 0 0 0 1px {color} !important; }}'
        )
    if css_parts:
        st.markdown(f"<style>{''.join(css_parts)}</style>", unsafe_allow_html=True)


def get_pending_modes(mode_defs):
    """メンテナンス業務トップの全モード分の「対応待ちデータあり」判定をまとめて行う。
    mode_defs: [(mode_key, label, target_csv, dest_csv, status_col, check_col, print_col), ...]
    （申請者/担当者の列は全モード共通でB列＝index1のため、mode_defsには含めていない）
    9モード分（最大18件）のシート読み込みを1件ずつ順番に行うと、キャッシュが切れた
    タイミング（60秒ごと）でボタン行の表示が毎回数秒〜十数秒待たされてしまうため、
    ThreadPoolExecutorで並列に読み込むことで待ち時間を大きく縮める
    （各読み込み自体はキャッシュ付きの_fetch_csv_or_noneなので、2回目以降はほぼ一瞬で返る）。
    ログイン中のユーザー（st.session_state の user_role / user_name）を基準に絞り込む
    （差戻しは申請者本人、承認待ちは管理職、転記・チェック・印刷待ちは業務担当のみに見える）。
    戻り値: {mode_key: ["差戻し1件", "未チェック2件", ...]} の辞書（対応待ちがあるモードのみ）。
    setとして使っていた既存の呼び出し元（`if pending_modes:` や `for m in pending_modes`）は
    辞書でもそのまま動く（キーがmode_keyのため）。理由の内訳はボタンが赤い根拠を画面上で
    確認できるようにするためのもの。"""
    urls = []
    for _mode_key, _label, target_csv, dest_csv, *_rest in mode_defs:
        urls.append(target_csv)
        urls.append(dest_csv)
    unique_urls = list(dict.fromkeys(urls))

    fetched = {}
    if unique_urls:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(unique_urls))) as executor:
            future_to_url = {executor.submit(_fetch_csv_or_none, u): u for u in unique_urls}
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    fetched[url] = future.result()
                except Exception:
                    fetched[url] = None

    user_role = st.session_state.get("user_role", "")
    user_name = st.session_state.get("user_name", "")

    pending_modes = {}
    for mode_key, _label, target_csv, dest_csv, status_col, check_col, print_col in mode_defs:
        try:
            reasons = _pending_reasons_from_dfs(
                fetched.get(target_csv), fetched.get(dest_csv), status_col, check_col, print_col,
                user_role=user_role, user_name=user_name,
            )
            if reasons:
                pending_modes[mode_key] = reasons
        except Exception:
            pass
    return pending_modes



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
