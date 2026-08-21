import pandas as pd
import requests

# 新しいユーザーマスターのURL
USER_MASTER_CSV = "https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid=0"

def load_sheet_data(gid="0"):
    """ユーザーマスターのスプレッドシートからデータを取得"""
    try:
        df = pd.read_csv(USER_MASTER_CSV)
        if df.empty:
            return None
        headers = df.columns.tolist()
        data = df.fillna("").values.tolist()
        return [headers] + data
    except Exception as e:
        print(f"Data loading error: {e}")
        return None

def load_navi_data_from_url(url_or_gid="0"):
    """ナビゲーション用のデータをURLまたはgidから読み込む"""
    try:
        if str(url_or_gid).startswith("http"):
            csv_url = url_or_gid
        else:
            csv_url = f"https://docs.google.com/spreadsheets/d/1AkMb1J2m3VZAIyMCKmr3T3E8-kJB0BDDdWQJuEn7YGc/gviz/tq?tqx=out:csv&gid={url_or_gid}"
        
        df = pd.read_csv(csv_url)
        return df
    except Exception as e:
        print(f"Navi data loading error: {e}")
        return pd.DataFrame()
