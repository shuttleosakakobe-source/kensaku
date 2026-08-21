import pandas as pd
import requests

def load_sheet_data(gid="0"):
    """GoogleスプレッドシートのデータをCSV経由で取得して二次元配列で返す"""
    csv_url = f"https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/gviz/tq?tqx=out:csv&gid={gid}"
    try:
        df = pd.read_csv(csv_url)
        if df.empty:
            return None
        # ヘッダーと行データをリストに変換
        headers = df.columns.tolist()
        data = df.fillna("").values.tolist()
        return [headers] + data
    except Exception as e:
        print(f"Data loading error: {e}")
        return None
