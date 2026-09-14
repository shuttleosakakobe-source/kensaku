import streamlit as st
import pandas as pd
import requests

# 新しいユーザーマスターのURL
USER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=0"

def load_sheet_data(gid="0"):
    """ユーザーマスターのスプレッドシートからデータを取得
    （dtype=strで読み込むことで、権限列（F列）などの数字だけの列がpandasに
    よって数値型に変換され、"2"が"2.0"のような文字列になってしまうのを防ぐ）
    短時間キャッシュ（15秒）により、ログイン試行のたびにGoogle Sheetsへ
    問い合わせが飛ぶのを防ぐ。"""
    try:
        df = _read_csv_cached_str(USER_MASTER_CSV)
        if df.empty:
            return None
        headers = df.columns.tolist()
        data = df.fillna("").values.tolist()
        return [headers] + data
    except Exception as e:
        print(f"Data loading error: {e}")
        return None

def load_navi_data_from_url(url_or_gid="0"):
    """ナビゲーション用のデータをURLまたはgidから読み込む（短時間キャッシュ付き）"""
    try:
        if str(url_or_gid).startswith("http"):
            csv_url = url_or_gid
        else:
            csv_url = f"https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid={url_or_gid}"

        return _read_csv_cached(csv_url)
    except Exception as e:
        print(f"Navi data loading error: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=15)
def _read_csv_cached(url):
    return pd.read_csv(url)


@st.cache_data(ttl=15)
def _read_csv_cached_str(url):
    return pd.read_csv(url, dtype=str)
