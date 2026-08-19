import streamlit as st
import pandas as pd
from datetime import datetime
from utils import get_jst_today, get_img_html, process_logout, post_to_gas, h
from data_loader import load_sheet_data, get_visit_schedule_data

def main_screen():
    u_name = st.session_state.get('user_name', '担当者')
    u_code = st.session_state.get('user_code', '')
    u_url  = st.session_state.get('user_url', '')
    u_role = st.session_state.get('user_role', '2')
    
    # --- ヘッダー ---
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(f"### 👋 お疲れ様です、{u_name} さん")
    with c2:
        if st.button("ログアウト", use_container_width=True):
            process_logout()

    # --- 🚨 差戻し申請のアラート通知 ---
    try:
        maint_csv = "https://docs.google.com/spreadsheets/d/1Fwdtp6ZLvbg3_ksslQgHPcL0CENZ4JXjZ2cInvWlhXo/export?format=csv&gid=0"
        df_maint = pd.read_csv(maint_csv)
        if len(df_maint.columns) >= 29:
            # 自分の担当名かつステータスが「差戻し」のデータを抽出
            my_rejections = df_maint[(df_maint.iloc[:, 1].astype(str) == u_name) & (df_maint.iloc[:, 28] == "差戻し")]
            if not my_rejections.empty:
                st.error(f"🚨 **差戻しされた臨時納品申請が {len(my_rejections)} 件あります！内容を確認して再申請してください。**")
                for _, r in my_rejections.iterrows():
                    reason = r.iloc[29] if len(r) >= 30 and pd.notna(r.iloc[29]) else "理由の記載なし"
                    cust = r.iloc[3] if pd.notna(r.iloc[3]) else "不明"
                    st.warning(f"・【{r.iloc[0]} 申請分】 顧客: **{cust}** | 差戻し理由: **{reason}**")
    except Exception:
        pass

    # --- アラート表示（共通連絡事項） ---
    if st.session_state.get('needs_alert', False):
        st.error("⚠️ 本日の連絡事項または確認未完了項目があります。")

    # --- 機能ナビゲーションボタン ---
    st.markdown("#### 🚀 メニュー")
    b1, b2 = st.columns(2)
    with b1:
        if st.button("🗺️ ルートナビゲーション", use_container_width=True, type="primary"):
            st.session_state.current_page = "navi"
            st.rerun()
    with b2:
        if st.button("📦 臨時納品・メンテナンス管理", use_container_width=True):
            st.session_state.current_page = "maint_admin"
            st.rerun()

    st.write("---")

    # --- 本日の周期・訪問スケジュール情報 ---
    st.markdown("#### 📅 本日の周期情報")
    if u_code:
        schedules, today_sched = get_visit_schedule_data(u_code)
        st.info(f"**本日の周期:** {today_sched}")
        
        sc1, sc2, sc3, sc4 = st.columns(4)
        sc1.metric("1W後", schedules.get("1W", {}).get("display", "--"))
        sc2.metric("2W後", schedules.get("2W", {}).get("display", "--"))
        sc3.metric("4W後", schedules.get("4W", {}).get("display", "--"))
        sc4.metric("8W後", schedules.get("8W", {}).get("display", "--"))

    st.write("---")

    # --- タイムカード機能 ---
    st.markdown("#### ⏱️ タイムカード")
    t1, t2 = st.columns(2)
    with t1:
        if st.button("☀️ 出勤登録", use_container_width=True):
            res = post_to_gas({
                "status": "TIMECARD",
                "user_code": u_code,
                "user_name": u_name,
                "type": "出勤",
                "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            })
            if res.get("status") == "success":
                st.success("出勤を記録しました。")
            else:
                st.error(f"打刻失敗: {res.get('message')}")
    with t2:
        if st.button("🌙 退勤登録", use_container_width=True):
            res = post_to_gas({
                "status": "TIMECARD",
                "user_code": u_code,
                "user_name": u_name,
                "type": "退勤",
                "timestamp": datetime.now().strftime("%Y/%m/%d %H:%M:%S")
            })
            if res.get("status") == "success":
                st.success("退勤を記録しました。")
            else:
                st.error(f"打刻失敗: {res.get('message')}")
