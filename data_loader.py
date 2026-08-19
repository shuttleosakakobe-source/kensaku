import csv
import io
import urllib.request
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st
from utils import get_jst_today, parse_flexible_date

MASTER_SPREADSHEET_ID = "1cPgQ3Ej3P7JZPaxprFQnbnDkCatQ15lEHyF9C9tMgZ4"
MASTER_GID = "1124312474"


@st.cache_data(ttl=0)
def load_sheet_data(gid="0", custom_url=None):
    if custom_url:
        target_url = custom_url
    else:
        base_url = f"https://docs.google.com/spreadsheets/d/{MASTER_SPREADSHEET_ID}/export?format=csv&gid="
        check_sheet_url = "https://docs.google.com/spreadsheets/d/1EofzMjd3dAq8sRCdQXpxw3_-T1VDWpd-aDrvxWD4fYc/export?format=csv&gid=1552856942"
        target_url = (
            check_sheet_url if gid == "1552856942" else f"{base_url}{gid}"
        )

    try:
        response = urllib.request.urlopen(target_url, timeout=10)
        content = response.read().decode("utf-8")
        f = io.StringIO(content)
        reader = csv.reader(f)
        return list(reader)
    except:
        return None


@st.cache_data(ttl=300)
def load_customer_master():
    """
    顧客マスタを取得（A列:加盟店名, B列:顧客コード, C列:顧客名, E列:加盟店コード）
    型補正およびゼロ落ち防止処理を強化
    """
    url = "https://docs.google.com/spreadsheets/d/1-1zvVWOfHsXFWdUoAZwOUnxo1BgSdKMG6GubpRTVqeM/export?format=csv&gid=127347205"
    try:
        response = urllib.request.urlopen(url, timeout=10)
        content = response.read().decode("utf-8")
        f = io.StringIO(content)
        reader = list(csv.reader(f))

        if len(reader) < 2:
            return {}

        customer_dict = {}
        for row in reader[1:]:
            if len(row) >= 5:
                store_name = str(row[0]).strip()  # A列：加盟店名
                cust_code = str(row[1]).strip()  # B列：顧客コード
                cust_name = str(row[2]).strip()  # C列：顧客名
                store_code = str(row[4]).strip()  # E列：加盟店コード

                if cust_code:
                    customer_dict[cust_code] = {
                        "store_name": store_name,
                        "cust_name": cust_name,
                        "store_code": store_code,
                    }
        return customer_dict
    except Exception:
        return {}


@st.cache_data(ttl=30)
def load_navi_data_from_url(csv_url):
    try:
        df = pd.read_csv(csv_url)
        df.columns = df.columns.str.strip()
        return df.to_dict(orient="records")
    except:
        return []


def get_visit_schedule_data(user_code):
    rows = load_sheet_data(gid="370581902")
    if not rows or len(rows) < 3:
        return {}, "データなし"

    code_row = rows[0]
    user_col_idx = -1
    target_code = str(user_code).strip().lower()

    for idx, col in enumerate(code_row):
        col_str = str(col).strip().lower()
        if (
            col_str == target_code
            or col_str.split(".")[0] == target_code.split(".")[0]
        ):
            user_col_idx = idx
            break

    if user_col_idx == -1:
        try:
            target_int = int(float(user_code))
            for idx, col in enumerate(code_row):
                try:
                    if int(float(col)) == target_int:
                        user_col_idx = idx
                        break
                except:
                    continue
        except:
            pass

    if user_col_idx == -1:
        return {}, "未登録"

    today = get_jst_today()
    today_schedule = "なし"
    all_schedules = []

    for row in rows[2:]:
        if len(row) <= user_col_idx:
            continue
        date_str = row[0]
        cell_val = row[user_col_idx].strip()
        row_date = parse_flexible_date(date_str)
        if not row_date:
            continue
        if row_date == today and cell_val:
            today_schedule = cell_val
        if cell_val:
            all_schedules.append(
                {
                    "date": row_date,
                    "val": cell_val,
                    "type": cell_val[0].upper(),
                }
            )

    all_schedules.sort(key=lambda x: x["date"])
    current_base_type = "A"
    for sched in all_schedules:
        if sched["date"] >= today:
            current_base_type = sched["type"]
            break

    cycle_order = ["A", "B", "C", "D"]
    try:
        base_idx = cycle_order.index(current_base_type)
    except:
        base_idx = 0

    w1_target = cycle_order[(base_idx + 1) % 4]
    w2_target = cycle_order[(base_idx + 2) % 4]
    w4_target = current_base_type
    w8_target = current_base_type

    visit_dates = {"1W": None, "2W": None, "4W": None, "8W": None}

    def get_disp_str(sched_obj):
        d = sched_obj["date"]
        v = sched_obj["val"]
        return (
            f"{d.strftime('%m/%d')}({v[1:]})"
            if len(v) > 1
            else f"{d.strftime('%m/%d')}"
        )

    for sched in all_schedules:
        if sched["date"] >= today and sched["type"] == w1_target:
            visit_dates["1W"] = {"display": get_disp_str(sched)}
            break

    w2_obj = None
    for sched in all_schedules:
        if sched["date"] >= today and sched["type"] == w2_target:
            w2_obj = sched
            visit_dates["2W"] = {"display": get_disp_str(sched)}
            break

    w4_obj = None
    if w2_obj:
        for sched in all_schedules:
            if sched["date"] > w2_obj["date"] and sched["type"] == w4_target:
                w4_obj = sched
                visit_dates["4W"] = {"display": get_disp_str(sched)}
                break
    else:
        for sched in all_schedules:
            if sched["date"] >= today and sched["type"] == w4_target:
                w4_obj = sched
                visit_dates["4W"] = {"display": get_disp_str(sched)}
                break

    if w4_obj:
        target_after_2w = w4_obj["date"] + timedelta(days=14)
        for sched in all_schedules:
            if sched["date"] >= target_after_2w and sched["type"] == w8_target:
                visit_dates["8W"] = {"display": get_disp_str(sched)}
                break

    for k in visit_dates:
        if visit_dates[k] is None:
            visit_dates[k] = {"display": "--/--"}

    return visit_dates, today_schedule
