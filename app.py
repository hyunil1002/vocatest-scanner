import os
import streamlit as st
import tempfile
import requests
import pandas as pd
import time
import io
import importlib
import subprocess
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
# 0. Session State 초기화
# ==============================================================
if "is_parsed" not in st.session_state:
    st.session_state.is_parsed = False
if "df" not in st.session_state:
    st.session_state.df = pd.DataFrame()
if "parsed_words" not in st.session_state:
    st.session_state.parsed_words = []
if "log_messages" not in st.session_state:
    st.session_state.log_messages = []

def reset_state():
    st.session_state.is_parsed = False
    st.session_state.df = pd.DataFrame()
    st.session_state.parsed_words = []
    st.session_state.log_messages = []

def add_log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{timestamp}] {msg}")

def run_deploy():
    """deploy.bat 파일을 실행하고 결과를 반환한다."""
    try:
        # shell=True는 Windows에서 .bat 실행 시 필요
        process = subprocess.run(["deploy.bat"], capture_output=True, text=True, shell=True)
        return process.stdout, process.stderr, process.returncode
    except Exception as e:
        return "", str(e), 1

st.set_page_config(page_title="보카테스트 AI 스캐너", layout="centered", initial_sidebar_state="expanded")

# ──────────────────────────────────────────────
# Sidebar: Deployment & Settings
# ──────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🚀 시스템 관리")
    st.info("Gemini 3 Flash 엔진 최적화 모드 활성화됨")
    
    if st.button("🌐 GitHub에 즉시 업데이트", use_container_width=True):
        with st.spinner("배포 중..."):
            out, err, code = run_deploy()
            if code == 0:
                st.success("배포 성공!")
                with st.expander("배포 로그 확인"):
                    st.code(out)
            else:
                st.error("배포 실패")
                st.code(err)
    
    st.divider()
    st.caption("v2.5.0-flash-optimized")

# ──────────────────────────────────────────────
# Perfect Toss Clone & Animated Progress UI 7.0
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

/* Layout max width */
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

/* Typography */
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
}

/* File Uploader */
[data-testid="stFileUploaderDropzone"] {
    background-color: #f2f4f6 !important;
    border: 2px dashed #e5e8eb !important;
    border-radius: 20px !important;
    padding: 3rem 1rem !important;
}

/* --- Animated Shimmer Progress Bar --- */
.shimmer-progress-container {
    width: 100%;
    height: 12px;
    background-color: #f2f4f6;
    border-radius: 999px;
    overflow: hidden;
    position: relative;
    margin-top: 0.5rem;
    margin-bottom: 2rem;
}
.shimmer-progress-bar {
    height: 100%;
    background: linear-gradient(90deg, #3182f6, #4facfe);
    border-radius: 999px;
    transition: width 0.4s ease-out;
    position: relative;
    overflow: hidden;
}
.shimmer-progress-bar::after {
    content: '';
    position: absolute;
    top: 0; left: -100%;
    width: 60%; height: 100%;
    background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.5), transparent);
    animation: tossShimmer 1.5s infinite ease-in-out;
}
@keyframes tossShimmer {
    0% { left: -100%; }
    100% { left: 200%; }
}
.shimmer-text {
    font-size: 1.1rem;
    color: #191f28;
    margin-bottom: 0.8rem;
    font-weight: 700;
    display: flex;
    justify-content: space-between;
}
.eta-text {
    font-size: 0.9rem;
    color: #8b95a1;
    font-weight: 500;
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
# UI Logic
# ──────────────────────────────────────────────
if not st.session_state.is_parsed:
    st.markdown('<h1 class="hero-title">보카테스트 스캐너</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">최첨단 AI가 대량의 단어장도<br>순식간에 분석해 드립니다</p>', unsafe_allow_html=True)

    st.markdown('<div class="toss-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header">📄 분석할 PDF 업로드</div>', unsafe_allow_html=True)
    
    uploaded_file = st.file_uploader("", type=["pdf"], label_visibility="collapsed")
    st.markdown("<br>", unsafe_allow_html=True)
    
    btn_col1, btn_col2, btn_col3 = st.columns([1, 2, 1])
    with btn_col2:
        if st.button("분석 시작하기", disabled=not uploaded_file, type="primary", use_container_width=True):
            api_key_to_use = os.environ.get("GOOGLE_API_KEY")
            if not api_key_to_use:
                st.error("API 키가 설정되지 않았습니다.")
            else:
                reset_state()
                progress_container = st.empty()
                log_container = st.expander("🏗️ 처리 상세 정보 보기", expanded=True)
                
                def update_progress(percent: float, message: str):
                    # 로그 추가
                    add_log(message)
                    with log_container:
                        st.write(st.session_state.log_messages[-1])
                    
                    # UI 업데이트
                    html = f"""
                    <div>
                        <div class="shimmer-text">
                            <span>{message}</span>
                            <span style="color:#3182f6;">{percent}%</span>
                        </div>
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
                    
                    add_log("전략적 병렬 스캔 엔진 가동 중...")
                    words = parse_pdf(pdf_path=tmp_pdf_path, api_key=api_key_to_use, progress_callback=update_progress)
                
                    if not words:
                        st.warning("데이터를 추출하지 못했습니다.")
                    else:
                        st.session_state.parsed_words = words
                        st.session_state.df = flatten_document(words)
                        st.session_state.is_parsed = True
                        st.rerun()
                except Exception as e:
                    st.error(f"오류: {e}")
                finally:
                    if tmp_pdf_path and os.path.exists(tmp_pdf_path):
                        try: os.remove(tmp_pdf_path)
                        except: pass
    st.markdown('</div>', unsafe_allow_html=True)

else:
    st.markdown('<div class="toss-card">', unsafe_allow_html=True)
    col_header1, col_header2 = st.columns([1, 1])
    with col_header1:
        st.markdown('<div class="card-header">🔍 데이터 최종 검수</div>', unsafe_allow_html=True)
    with col_header2:
        if st.button("처음으로 돌아가기", type="secondary"):
            reset_state()
            st.rerun()
            
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True
    )
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    send_col, excel_col = st.columns([1.5, 1])
    with send_col:
        if st.button("📤 어드민 전송 및 배포", type="primary"):
            progress_bar = st.progress(0, text="데이터 전송 중...")
            final_words = unflatten_document(edited_df)
            total = len(final_words)
            success_count = 0
            
            for i, word in enumerate(final_words):
                try:
                    # 간단한 전송 로직 (중복 체크 생략/간소화 - 사용자 요청에 따라)
                    from models import WordPayload
                    payload = WordPayload(word=word, status="DRAFT").model_dump(mode="json")
                    resp = requests.post(API_URL, json=payload)
                    if resp.status_code in (200, 201):
                        success_count += 1
                except: pass
                progress_bar.progress((i + 1) / total, text=f"전송 중 ({i+1}/{total})")
            
            st.success(f"성공: {success_count}건 전송 완료!")
            
            # --- 자동 배포 트리거 ---
            with st.status("🚀 변경사항 GitHub 자동 배포 중...", expanded=True) as status:
                st.write("Git 작업 시작...")
                out, err, code = run_deploy()
                if code == 0:
                    status.update(label="✅ 배포가 완벽하게 완료되었습니다!", state="complete")
                    st.balloons()
                    time.sleep(3)
                    reset_state()
                    st.rerun()
                else:
                    status.update(label="❌ 배포 중 오류가 발생했습니다.", state="error")
                    st.error(err)

    with excel_col:
        excel_data = convert_df_to_excel(edited_df)
        st.download_button(
            label="💾 엑셀 다운로드",
            data=excel_data,
            file_name="voca_data.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    st.markdown('</div>', unsafe_allow_html=True)

