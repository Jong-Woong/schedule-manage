"""공정 관리 앱 진입점. 실행: streamlit run app.py"""

import streamlit as st

st.set_page_config(page_title="공정 관리", page_icon="🏗️", layout="wide")

pages = [
    st.Page("views/dashboard.py", title="대시보드", icon=":material/dashboard:", default=True),
    st.Page("views/upload.py", title="공정표 업로드", icon=":material/upload_file:", url_path="upload"),
]

# 페이지가 2개뿐이라 사이드바 대신 상단 메뉴로 두어 좁은 화면에서도 본문 폭을 확보한다
st.navigation(pages, position="top").run()
