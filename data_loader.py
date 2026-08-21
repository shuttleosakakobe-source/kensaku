import pandas as pd
import requests

def load_sheet_data(gid="0"):
    """GoogleスプレッドシートのデータをCSV経由で取得して二次元配列で返す"""
    csv_url = f"https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid={gid}"
    try:
        df = pd.read_csv(csv_url)
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
            csv_url = f"https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid={url_or_gid}"
        
        df = pd.read_csv(csv_url)
        return df
    except Exception as e:
        print(f"Navi data loading error: {e}")
        return pd.DataFrame()
