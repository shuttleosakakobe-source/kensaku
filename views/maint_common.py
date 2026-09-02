"""メンテナンス業務（商品発注／ルート変更／契約内容変更）で共通して使う定数・ヘルパー関数。
route_view.py / contract_view.py / order_view.py から読み込まれる。"""
import streamlit as st
import pandas as pd
import requests
import json
from datetime import timezone, timedelta


GAS_URL = "https://script.google.com/macros/s/AKfycbxi6ZG-8F6bq0T9k-yD5g6DVRY4hPdDB5spzwISOGUpZckvktjN-ISkWmZd3EdPXNx-qQ/exec"
CUSTOMER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=127347205"

# ご契約データ（顧客コードごとの契約週・曜日・担当者コードからルートコードを計算するための参照シート）
CONTRACT_DATA_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=2011677989"

# ご契約データシートの列（0始まり）：顧客コード(A)=0、担当者コード(E)=4、担当者名(F)=5、曜日(G)=6、契約週M/N/O/P=12/13/14/15
CONTRACT_COL_CUST_CODE = 0
CONTRACT_WEEK_COLS = [12, 13, 14, 15]  # M, N, O, P → 週1, 週2, 週3, 週4

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


def _load_contract_df():
    """ご契約データシートをキャッシュせず毎回読み込む（軽量な参照専用ヘルパー）"""
    try:
        df_contract = pd.read_csv(CONTRACT_DATA_CSV, dtype=str, storage_options={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return None
    if df_contract.empty:
        return None
    return df_contract
