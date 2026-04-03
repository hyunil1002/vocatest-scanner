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
if "file_data" not in st.session_state:
    # { filename: [Word, ...] } 형태의 데이터 저장
    st.session_state.file_data = {}
if "log_messages" not in st.session_state:
    st.session_state.log_messages = []

def reset_state():
    st.session_state.is_parsed = False
    st.session_state.df = pd.DataFrame()
    st.session_state.file_data = {}
    st.session_state.log_messages = []

def add_log(msg: str):
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.log_messages.append(f"[{timestamp}] {msg}")

def run_deploy():
    """deploy.bat 파일을 실행하고 결과를 반환한다."""
    try:
        process = subprocess.run(["deploy.bat"], capture_output=True, text=True, shell=True)
        return process.stdout, process.stderr, process.returncode
    except Exception as e:
        return "", str(e), 1

st.set_page_config(page_title="보카테스트 AI 스캐너", layout="centered", initial_sidebar_state="collapsed")

# ──────────────────────────────────────────────
# Perfect Toss UI 8.0 (No Sidebar)
# ──────────────────────────────────────────────
st.markdown("""
<style>
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css");
html, body, [class*="css"] { font-family: 'Pretendard', sans-serif !important; background-color: #f9fafb !important; }
header, footer, #MainMenu {visibility: hidden;}
.block-container { padding: 3rem 1rem !important; max-width: 760px !important; margin: 0 auto !important; }
.toss-card { background: #ffffff !important; border-radius: 24px !important; padding: 2.5rem !important; box-shadow: 0 10px 40px -10px rgba(0, 0, 0, 0.04) !important; margin-bottom: 2rem; }
.hero-title { font-size: 2.6rem !important; font-weight: 800 !important; color: #191f28 !important; text-align: center; margin-bottom: 0.8rem !important; }
.hero-subtitle { font-size: 1.1rem !important; color: #4e5968 !important; text-align: center; margin-bottom: 3.5rem !important; }
.card-header { font-size: 1.25rem; font-weight: 700; color: #333d4b; margin-bottom: 1.5rem; }
div.stButton > button[kind="primary"] { background-color: #3182f6 !important; color: white !important; border-radius: 18px !important; height: 3.8rem !important; font-size: 1.15rem !important; font-weight: 700 !important; width: 100%; border: none !important; }
div.stButton > button[kind="secondary"] { background-color: transparent !important; color: #8b95a1 !important; border: none !important; font-size: 1rem !important; text-decoration: underline !important; height: 3.8rem !important; width: 100%; }
[data-testid="stFileUploaderDropzone"] { background-color: #f2f4f6 !important; border: 2px dashed #e5e8eb !important; border-radius: 20px !important; padding: 2.5rem 1rem !important; }
.shimmer-progress-container { width: 100%; height: 12px; background-color: #f2f4f6; border-radius: 999px; overflow: hidden; margin-bottom: 2rem; }
.shimmer-progress-bar { height: 100%; background: linear-gradient(90deg, #3182f6, #4facfe); border-radius: 999px; transition: width 0.4s ease-out; position: relative; overflow: hidden; }
.shimmer-progress-bar::after { content: ''; position: absolute; top:0; left:-100%; width:60%; height:100%; background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent); animation: tossAnimation 1.5s infinite; }
@keyframes tossAnimation { 0% { left: -100%; } 100% { left: 200%; } }
.shimmer-text { font-size: 1.1rem; color: #191f28; font-weight: 700; display: flex; justify-content: space-between; margin-bottom: 0.8rem; }
</style>
""", unsafe_allow_html=True)

def convert_to_multi_sheet_excel(file_data: dict):
    """파일별로 시트를 나누어 엑셀 파일을 생성한다."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        for filename, words in file_data.items():
            df = flatten_document(words)
            # 시트 이름은 최대 31자, 특수문자 제한
            safe_name = "".join(c for c in filename if c.isalnum() or c in (' ', '_', '-'))[:31]
            df.to_excel(writer, index=False, sheet_name=safe_name)
    return output.getvalue()

# ──────────────────────────────────────────────
# Logic: Upload & Parsing
# ──────────────────────────────────────────────
if not st.session_state.is_parsed:
    st.markdown('<h1 class="hero-title">보카테스트 스캐너</h1>', unsafe_allow_html=True)
    st.markdown('<p class="hero-subtitle">여러 권의 영단어 교재도 한 번에 분석합니다</p>', unsafe_allow_html=True)

    st.markdown('<div class="toss-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header">📄 분석할 PDF 파일들 (복수 선택 가능)</div>', unsafe_allow_html=True)
    
    uploaded_files = st.file_uploader("", type=["pdf"], accept_multiple_files=True, label_visibility="collapsed")
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("분석 시작하기", disabled=not uploaded_files, type="primary"):
        api_key_to_use = os.environ.get("GOOGLE_API_KEY")
        if not api_key_to_use:
            st.error("API 키가 설정되지 않았습니다.")
        else:
            reset_state()
            progress_container = st.empty()
            log_container = st.expander("🏗️ 처리 현황 상세 보기", expanded=True)
            
            total_files = len(uploaded_files)
            all_merged_words = []
            
            for f_idx, up_file in enumerate(uploaded_files):
                fname = up_file.name
                add_log(f"[{f_idx+1}/{total_files}] '{fname}' 분석 시작...")
                
                def update_progress(percent: float, message: str):
                    # 파일별 내부 진행도 반영
                    overall_pct = (f_idx / total_files * 100) + (percent / total_files)
                    combined_msg = f"[{f_idx+1}/{total_files}] {fname}: {message}"
                    
                    html = f"""
                    <div>
                        <div class="shimmer-text">
                            <span>{combined_msg}</span>
                            <span style="color:#3182f6;">{round(overall_pct, 1)}%</span>
                        </div>
                        <div class="shimmer-progress-container">
                            <div class="shimmer-progress-bar" style="width: {overall_pct}%;"></div>
                        </div>
                    </div>
                    """
                    progress_container.markdown(html, unsafe_allow_html=True)
                    with log_container: st.write(f"· {combined_msg} ({round(percent, 1)}%)")

                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(up_file.getvalue())
                        tmp.close()
                        tmp_path = tmp.name
                    
                    file_words = parse_pdf(pdf_path=tmp_path, api_key=api_key_to_use, progress_callback=update_progress)
                    if file_words:
                        st.session_state.file_data[fname] = file_words
                        all_merged_words.extend(file_words)
                    
                    if os.path.exists(tmp_path): os.remove(tmp_path)
                except Exception as e:
                    add_log(f"오류 발생 ({fname}): {e}")
                    st.error(f"'{fname}' 처리 중 오류: {e}")

            if all_merged_words:
                st.session_state.df = flatten_document(all_merged_words)
                st.session_state.is_parsed = True
                st.rerun()
            else:
                st.warning("분석된 단어가 없습니다.")
    st.markdown('</div>', unsafe_allow_html=True)

# ──────────────────────────────────────────────
# Logic: Review & Export
# ──────────────────────────────────────────────
else:
    st.markdown('<div class="toss-card">', unsafe_allow_html=True)
    st.markdown('<div class="card-header">🔍 통합 데이터 검수</div>', unsafe_allow_html=True)
    
    edited_df = st.data_editor(
        st.session_state.df,
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True
    )
    
    if st.button("처음으로 돌아가기", type="secondary"):
        reset_state()
        st.rerun()
        
    st.markdown("<br>", unsafe_allow_html=True)
    
    send_col, excel_col = st.columns([1.5, 1])
    with send_col:
        if st.button("📤 어드민 전송 (배포 자동 포함)", type="primary"):
            progress_bar = st.progress(0, text="데이터 전송 중...")
            final_words = unflatten_document(edited_df)
            total_w = len(final_words)
            success_c = 0
            
            for i, word in enumerate(final_words):
                try:
                    from models import WordPayload
                    payload = WordPayload(word=word, status="DRAFT").model_dump(mode="json")
                    resp = requests.post(API_URL, json=payload)
                    if resp.status_code in (200, 201): success_c += 1
                except: pass
                progress_bar.progress((i + 1) / total_w, text=f"전송 중 ({i+1}/{total_w})")
            
            st.success(f"{success_c}건 전송 완료!")
            
            # --- 자동 배포 (UI 노출 최소화) ---
            with st.status("🚀 서버 최적화 및 배포 작업 중...", expanded=False) as status:
                st.write("백그라운드 배포 프로세스 가동...")
                out, err, code = run_deploy()
                if code == 0:
                    status.update(label="✅ 시스템 업데이트가 완료되었습니다.", state="complete")
                    st.balloons()
                    time.sleep(1) # 유저가 결과를 잠깐 볼 수 있게
                    reset_state()
                    st.rerun()
                else:
                    status.update(label="⚠️ 배포 중 경고 발생", state="error")
                    st.error(err)

    with excel_col:
        excel_data = convert_to_multi_sheet_excel(st.session_state.file_data)
        st.download_button(
            label="💾 파일별 시트 포함 엑셀 다운로드",
            data=excel_data,
            file_name="voca_combined_multi_sheet.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    st.markdown('</div>', unsafe_allow_html=True)
