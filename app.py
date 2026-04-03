import os
import streamlit as st
import tempfile
import requests
import pandas as pd
import time
import io
import importlib
from dotenv import load_dotenv

import parser
import models

# Streamlit 환경에서 모듈 변경 사항이 실시간으로 반영되지 않는 문제(캐싱)를 강제로 해결
importlib.reload(models)
importlib.reload(parser)

from parser import parse_pdf
from models import flatten_document, unflatten_document, Word, Meaning, Example

# .env 파일 로드
load_dotenv()

API_URL = "http://localhost:8000/api/words"

# ==============================================================
# 0. Session State 초기화 (최상단 배치)
# ==============================================================
if "is_parsed" not in st.session_state:
    st.session_state.is_parsed = False
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()
if "parsed_words" not in st.session_state:
    st.session_state.parsed_words = []

def reset_state():
    st.session_state.is_parsed = False
    st.session_state.df = pd.DataFrame()
    st.session_state.parsed_words = []

st.set_page_config(page_title="보카테스트 AI 스캐너", layout="centered", initial_sidebar_state="collapsed")

# ──────────────────────────────────────────────
# Perfect Toss Clone & Animated Progress UI 6.0
# ──────────────────────────────────────────────

st.markdown("""
<style>
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css");

/* Base Reset */
html, body, [class*="css"] {
    font-family: 'Pretendard', -apple-system, sans-serif !important;
    background-color: #f9fafb !important;
}

/* Hide Streamlit Bloat */
header, footer, #MainMenu {visibility: hidden;}

/* Layout max width for 시원한 centered view */
.block-container {
    padding-top: 3rem !important;
    padding-bottom: 5rem !important;
    max-width: 760px !important;
    margin: 0 auto !important;
}

/* Toss Card Style */
.toss-card {
    background: #ffffff !important;
    border-radius: 24px !important;
    padding: 2.5rem !important;
    box-shadow: 0 10px 40px -10px rgba(0, 0, 0, 0.04) !important;
    margin-bottom: 2rem;
}

/* Typography Toss Style */
.hero-title {
    font-size: 2.8rem !important;
    font-weight: 800 !important;
    color: #191f28 !important;
    letter-spacing: -0.03em !important;
    margin-bottom: 0.8rem !important;
    text-align: center;
}
.hero-subtitle {
    font-size: 1.15rem !important;
    color: #4e5968 !important;
    text-align: center;
    margin-bottom: 3.5rem !important;
    font-weight: 500;
}

/* Header Text in Card */
.card-header {
    font-size: 1.3rem;
    font-weight: 700;
    color: #333d4b;
    margin-bottom: 1.5rem;
    display: flex;
    align-items: center;
    gap: 8px;
}

/* Toss Style Buttons */
div.stButton > button[kind="primary"] {
    background-color: #3182f6 !important;
    color: white !important;
    border-radius: 18px !important;
    height: 3.8rem !important;
    font-size: 1.2rem !important;
    font-weight: 700 !important;
    border: none !important;
    transition: all 0.2s ease !important;
}
div.stButton > button[kind="primary"]:hover {
    background-color: #2673e5 !important;
    transform: scale(0.985);
}

div.stButton > button[kind="secondary"] {
    background-color: transparent !important;
    color: #8b95a1 !important;
    border: none !important;
    border-radius: 18px !important;
    font-size: 1rem !important;
    font-weight: 600 !important;
    text-decoration: underline !important;
    height: 3.8rem !important;
    width: 100% !important;
    margin-top: 0 !important;
}
div.stButton > button[kind="secondary"]:hover {
    color: #333d4b !important;
}

/* File Uploader Toss Box */
[data-testid="stFileUploaderDropzone"] {
    background-color: #f2f4f6 !important;
    border: 2px dashed #e5e8eb !important;
    border-radius: 20px !important;
    padding: 3rem 1rem !important;
    transition: all 0.2s ease;
}
[data-testid="stFileUploaderDropzone"]:hover {
    background-color: #f2f4f6 !important;
    border-color: #3182f6 !important;
}

/* Data Editor */
div[data-testid="stDataEditor"] {
    border-radius: 16px !important;
    border: 1px solid #f2f4f6 !important;
    overflow: hidden !important;
}

/* --- Animated Shimmer Progress Bar --- */
.shimmer-progress-container {
    width: 100%;
    height: 10px;
    background-color: #f2f4f6;
    border-radius: 999px;
    overflow: hidden;
    position: relative;
    margin-top: 0.5rem;
    margin-bottom: 2rem;
}
.shimmer-progress-bar {
    height: 100%;
    background-color: #3182f6;
    border-radius: 999px;
    transition: width 0.5s cubic-bezier(0.4, 0, 0.2, 1);
    position: relative;
    overflow: hidden;
}
/* Soft light band shimmer animation */
.shimmer-progress-bar::after {
    content: '';
    position: absolute;
    top: 0;
    left: -100%;
    width: 60%;
    height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.4), transparent);
    animation: tossShimmer 1.5s infinite ease-in-out;
}
@keyframes tossShimmer {
    0% { left: -100%; }
    100% { left: 200%; }
}
.shimmer-text {
    font-size: 1rem;
    color: #4e5968;
    margin-bottom: 0.8rem;
    font-weight: 600;
}
</style>
""", unsafe_allow_html=True)

@st.cache_data
def convert_df_to_excel(df: pd.DataFrame):
     output = io.BytesIO()
     with pd.ExcelWriter(output, engine='openpyxl') as writer:
         df.to_excel(writer, index=False, sheet_name='VocaData')
     return output.getvalue()

# ──────────────────────────────────────────────
# Hero Layout
# ──────────────────────────────────────────────
if not st.session_state.is_parsed:
    st.markdown('<h1 class="hero-title">보카테스트 스캐너</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">PDF 단어장을 분석하여<br>정확하게 데이터로 변환해 드려요</p>', unsafe_allow_html=True)

    # ==============================================================
    # 1. 파일 업로드 및 분석
    # ==============================================================
    st.markdown('<div class="toss-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header">📄 단어장 등록하기</div>', unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("", type=["pdf"], label_visibility="collapsed")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 버튼 정렬 (중앙 배치, 약 50% 너비)
    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        if st.button("분석 시작하기", disabled=not uploaded_file, type="primary", use_container_width=True):
            api_key_to_use = os.environ.get("GOOGLE_API_KEY")
            if not api_key_to_use:
                st.error("서버에 GOOGLE_API_KEY 환경변수가 설정되지 않았습니다.")
            else:
                reset_state()
                progress_container = st.empty()
                # 로딩 UI 표시
                initial_html = f"""
                <div>
                    <div class="shimmer-text">준비 중... (0%)</div>
                    <div class="shimmer-progress-container"><div class="shimmer-progress-bar" style="width: 0%;"></div></div>
                </div>
                """
                progress_container.markdown(initial_html, unsafe_allow_html=True)
                
                def update_progress(percent: float, message: str):
                    html = f"""
                    <div>
                        <div class="shimmer-text">{message} &nbsp;<span style="color:#3182f6; font-weight:800;">{percent}%</span></div>
                        <div class="shimmer-progress-container">
                            <div class="shimmer-progress-bar" style="width: {percent}%;"></div>
                        </div>
                    </div>
                    """
                    progress_container.markdown(html, unsafe_allow_html=True)

                tmp_pdf_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(uploaded_file.getvalue())
                        tmp_file.close()
                        tmp_pdf_path = tmp_file.name
                    
                    words = parse_pdf(pdf_path=tmp_pdf_path, api_key=api_key_to_use, progress_callback=update_progress)
                
                    progress_container.empty()
                    if not words:
                        st.warning("단어를 찾지 못했어요.")
                    else:
                        st.session_state.parsed_words = words
                        st.session_state.df = flatten_document(words)
                        st.session_state.is_parsed = True
                        st.rerun()
                except Exception as e:
                    progress_container.empty()
                    st.error(f"오류가 발생했어요: {e}")
                finally:
                    if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                        try: os.remove(tmp_pdf_path)
                        except: pass
    st.markdown('</div>', unsafe_allow_html=True)

# ==============================================================
# 2. 결과 검수 및 전송
# ==============================================================
else:
    st.markdown('<div class="toss-card">', unsafe_allow_html=True)
    col_header1, col_header2 = st.columns([1, 1])
    with col_header1:
        st.markdown('<div class="card-header">🔍 꼼꼼하게 확인하기</div>', unsafe_allow_html=True)
    with col_header2:
        if st.button("새로 시작하기", type="secondary"):
            reset_state()
            st.rerun()
            
    st.markdown('<p style="color:#4e5968; margin-bottom:2rem; font-size:1.05rem;">추출된 데이터를 확인하고 필요한 부분을 수정해 주세요.</p>', unsafe_allow_html=True)
    
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    # 하단 액션 버튼 그룹
    send_col, excel_col = st.columns([1.5, 1])
    with send_col:
        if st.button("📤 어드민 서버로 전송", type="primary"):
            with st.spinner("서버로 보내는 중..."):
                final_words = unflatten_document(edited_df)
                success_count, skip_count, fail_count = 0, 0, 0
                for word in final_words:
                    try:
                        resp_get = requests.get(API_URL, params={"search": word.word_name})
                        if resp_get.status_code == 200:
                            data = resp_get.json()
                            results = data if isinstance(data, list) else data.get("results", [])
                            exists = any(item.get("word_name", "").lower() == word.word_name.lower() for item in results)
                            if exists:
                                from models import MeaningPayload
                                payload = MeaningPayload(word_name=word.word_name, meanings=word.meanings, status="DRAFT").model_dump(mode="json")
                                resp_post = requests.post(f"{API_URL}/{word.word_name}/meanings", json=payload)
                                if resp_post.status_code in (200, 201): skip_count += 1
                                else: fail_count += 1
                            else:
                                from models import WordPayload
                                payload = WordPayload(word=word, status="DRAFT").model_dump(mode="json")
                                resp_post = requests.post(API_URL, json=payload)
                                if resp_post.status_code in (200, 201): success_count += 1
                                else: fail_count += 1
                    except: fail_count += 1
                
                if fail_count > 0: st.warning(f"일부 실패: 전송 {success_count+skip_count}건, 실패 {fail_count}건")
                else:
                    st.balloons()
                    st.success("데이터 전송 완료!")
                    time.sleep(2)
                    reset_state()
                    st.rerun()

    with excel_col:
        excel_data = convert_df_to_excel(edited_df)
        st.download_button(
            label="💾 엑셀 다운로드",
            data=excel_data,
            file_name="voca_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    st.markdown('</div>', unsafe_allow_html=True)
