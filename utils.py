import streamlit as st
import os
import base64
import html
import json
import urllib.request
import re
from datetime import datetime, timedelta, timezone
from streamlit_javascript import st_javascript

# ⚠️ 正しいGASウェブアプリURLに置き換えてください
GAS_WEBAPP_URL = "https://script.google.com/macros/s/AKfycbwq7IOhDNIgyUrO6Vh7gn1Ja4t73LK46RrXZZSoZN_v7Qhr59OebNIKAZg2GiDye1oifw/exec"

def get_jst_today():
    jst = timezone(timedelta(hours=9))
    return datetime.now(jst).date()

def h(value):
    return html.escape(str(value or ""), quote=True)

@st.cache_data
def _get_base64_img(file_name):
    if os.path.exists(file_name):
        with open(file_name, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return None

def get_img_html(file_name, emoji, alert=False, width="100%"):
    border = "5px solid red" if alert else "5px solid transparent"
    shadow = "box-shadow: 0 0 15px red; filter: drop-shadow(0 0 5px red);" if alert else ""
    data = _get_base64_img(file_name)
    if data:
        img_code = f'data:image/png;base64,{data}'
        return f'<img src="{img_code}" style="width:{width}; aspect-ratio:1/1; object-fit:contain; border-radius:15px; border:{border}; {shadow}; display: block; margin: 0 auto;">'
    return f'<div style="width:{width}; aspect-ratio:1/1; background:#f0f2f6; border-radius:15px; display:flex; align-items:center; justify-content:center; font-size:40px; border:{border}; {shadow}; margin: 0 auto;">{emoji}</div>'

def set_login_storage(name, url, alert, role, code):
    values = {
        "shuttle_user_name": name,
        "shuttle_user_url": url,
        "shuttle_needs_alert": alert,
        "shuttle_user_role": role,
        "shuttle_user_code": code,
    }
    script = "\n".join(
        f"sessionStorage.setItem({json.dumps(key)}, {json.dumps(str(value or ''))});"
        for key, value in values.items()
    )
    st_javascript(script)

def check_session_storage():
    local_name = st_javascript("sessionStorage.getItem('shuttle_user_name');")
    local_role = st_javascript("sessionStorage.getItem('shuttle_user_role');")
    local_code = st_javascript("sessionStorage.getItem('shuttle_user_code');")
    local_url = st_javascript("sessionStorage.getItem('shuttle_user_url');")
    
    if local_name and local_role and local_code:
        st.session_state.user_name = str(local_name)
        st.session_state.user_role = str(local_role)
        st.session_state.user_code = str(local_code)
        st.session_state.user_url = str(local_url) if local_url else ""
        st.session_state.login_status = True

def process_logout():
    st_javascript("sessionStorage.clear();")
    st_javascript("localStorage.clear();")
    st.session_state.login_status = False
    st.session_state.logout_requested = True
    st.session_state.show_timecard = False
    st.session_state.current_page = "main"
    if 'user_name' in st.session_state: del st.session_state.user_name
    if 'user_code' in st.session_state: del st.session_state.user_code
    if 'user_role' in st.session_state: del st.session_state.user_role
    st.rerun()

def inject_pwa_blocker():
    icon_data = _get_base64_img("icon.png")
    if icon_data:
        block_html = f'''
            <script>
                const links = parent.document.getElementsByTagName("link");
                for (let link of links) {{
                    if (link.rel === "manifest" || link.href.includes("manifest")) {{
                        link.href = "data:application/json;base64,e30=";
                    }}
                }}
                let appleLink = parent.document.querySelector("link[rel='apple-touch-icon']");
                if (!appleLink) {{
                    appleLink = parent.document.createElement("link");
                    appleLink.rel = "apple-touch-icon";
                    parent.document.head.appendChild(appleLink);
                }}
                appleLink.href = "data:image/png;base64,{icon_data}";

                let iconLink = parent.document.querySelector("link[sizes='192x192']");
                if (!iconLink) {{
                    iconLink = parent.document.createElement("link");
                    iconLink.rel = "icon";
                    iconLink.sizes = "192x192";
                    parent.document.head.appendChild(iconLink);
                }}
                iconLink.href = "data:image/png;base64,{icon_data}";
            </script>
        '''
        st.components.v1.html(block_html, height=0, width=0)

def post_to_gas(payload):
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        GAS_WEBAPP_URL, 
        data=data, 
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        return {"status": "error", "message": str(e)}

def extract_ss_details(url_str):
    if not url_str or "docs.google.com" not in url_str:
        return None, None
    ss_id = None
    gid = "0"
    id_match = re.search(r'/d/([a-zA-Z0-9-_]+)', url_str)
    if id_match:
        ss_id = id_match.group(1)
    gid_match = re.search(r'gid=([0-9]+)', url_str)
    if gid_match:
        gid = gid_match.group(1)
    return ss_id, gid

def parse_flexible_date(date_str):
    if not date_str:
        return None
    cleaned = str(date_str).strip().split(" ")[0]
    
    match_jp = re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})日', cleaned)
    if match_jp:
        try:
            year, month, day = map(int, match_jp.groups())
            return datetime(year, month, day).date()
        except:
            return None
            
    cleaned = cleaned.replace("-", "/")
    match_slash = re.match(r'^(\d{4})/(\d{1,2})/(\d{1,2})', cleaned)
    if match_slash:
        try:
            year, month, day = map(int, match_slash.groups())
            return datetime(year, month, day).date()
        except:
            return None
    return None
