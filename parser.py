from __future__ import annotations

import base64
import json
import logging
import math
import os
import time
from typing import Any, Callable
import io
import concurrent.futures

import pypdfium2 as pdfium
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold

from models import Example, Meaning, ParsedChunk, Word, parse_meaning_raw

# ──── 로그 설정 (파일과 콘솔 모두 기록) ────
DEBUG_LOG_FILE = "parsing_debug.log"
logger = logging.getLogger(__name__)

# 파일 핸들러 추가 (심층 분석용)
if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    file_handler = logging.FileHandler(DEBUG_LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

# ──────────────────────────────────────────────
# 설정 상수
# ──────────────────────────────────────────────
CHUNK_SIZE_PAGES = 5
DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_IMAGE_SCALE = 2.0  # 고속 병렬 처리 최적화를 위해 2.0 해상도 적용

# ── 안전 필터 설정 (오탐 방지용 비활성화) ──
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ──────────────────────────────────────────────
# 1. PDF 특정 페이지 범위를 이미지(Base64)로 추출
# ──────────────────────────────────────────────
def extract_images_from_pdf_range(
    pdf_path: str,
    page_indices: list[int],
    scale: float = DEFAULT_IMAGE_SCALE
) -> list[str]:
    """
    지정된 페이지 번호 리스트에 해당하는 페이지들을 고해상도 PNG 이미지로 변환한다.
    """
    base64_images: list[str] = []
    try:
        with pdfium.PdfDocument(pdf_path) as pdf:
            for i in page_indices:
                if i >= len(pdf): continue
                page = pdf[i]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                
                img_byte_arr = io.BytesIO()
                pil_image.save(img_byte_arr, format='PNG')
                img_bytes = img_byte_arr.getvalue()
                
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                base64_images.append(b64)
    except Exception as e:
        logger.error(f"페이지 범위 {page_indices} 이미지 추출 중 오류: {e}")
        raise
    return base64_images


# ──────────────────────────────────────────────
# 2. 청킹 (페이지 번호 기준)
# ──────────────────────────────────────────────
def chunk_page_indices(total_pages: int, chunk_size: int = CHUNK_SIZE_PAGES) -> list[list[int]]:
    """페이지 번호를 청크 단위로 나눈다."""
    chunks: list[list[int]] = []
    for i in range(0, total_pages, chunk_size):
        end = min(i + chunk_size, total_pages)
        chunks.append(list(range(i, end)))
    return chunks


# ──────────────────────────────────────────────
# 3. LLM 시스템 프롬프트
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """Extract vocabulary data from provided textbook images into a strict JSON structure.
Rules:
1. Target word in `english_sentence` must be in braces {word}.
2. Separate multiple definitions in `meaning_parsed` with semicolons (;).
3. Part-of-speech tags must be in `meaning_raw`.
4. Output valid JSON according to schema.
"""

# ──────────────────────────────────────────────
# 4. LLM 체인 구성 및 파싱
# ──────────────────────────────────────────────
def build_llm(
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    api_key: str | None = None,
):
    llm_kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "max_output_tokens": 8192,
        "safety_settings": SAFETY_SETTINGS,
    }
    if api_key:
        llm_kwargs["google_api_key"] = api_key

    llm = ChatGoogleGenerativeAI(**llm_kwargs)
    return llm.with_structured_output(ParsedChunk, method="json_schema")


def parse_chunk(structured_llm, pdf_path: str, page_indices: list[int], chunk_index: int) -> ParsedChunk:
    logger.info(f"청크 {chunk_index} 렌더링 및 파싱 시작 (페이지: {page_indices})")
    
    # 1. 렌더링 (이 단계가 각 스레드에서 병렬로 진행됨)
    chunk_images_b64 = extract_images_from_pdf_range(pdf_path, page_indices)
    
    total_b64_size = sum(len(b) for b in chunk_images_b64)
    if total_b64_size > 20 * 1024 * 1024:
        logger.warning(f"경고: 청크 {chunk_index} 이미지 크기가 {total_b64_size/1024/1024:.1f}MB입니다.")

    content_list = [
        {"type": "text", "text": "Identify and extract all word items from the following images."}
    ]
    for b64 in chunk_images_b64:
        content_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{b64}"}
        })

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=content_list)
    ]

    start_time = time.time()
    parsed = None
    max_retries = 4
    
    for attempt in range(max_retries):
        try:
            parsed = structured_llm.invoke(messages)
            duration = time.time() - start_time
            logger.info(f"청크 {chunk_index} API 응답 성공 (소요시간: {duration:.1f}s)")
            break
        except Exception as e:
            error_str = str(e)
            if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                if attempt < max_retries - 1:
                    wait_time = 15 * (attempt + 1)
                    logger.warning(f"청크 {chunk_index} Rate Limit (429) - {wait_time}초 후 재시도 ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"청크 {chunk_index} API 호출 최종 실패 (Rate Limit): {e}")
                    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"\n--- CHUNK {chunk_index} FAILURE (429) ---\nError: {e}\n")
                    raise
            else:
                logger.error(f"청크 {chunk_index} Gemini 호출 실패: {e}")
                with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"\n--- CHUNK {chunk_index} FAILURE ---\nError: {e}\n")
                raise

    if parsed and parsed.words:
        for word in parsed.words:
            for meaning in word.meanings:
                corrected = parse_meaning_raw(meaning.meaning_raw)
                if not meaning.meaning_parsed or (corrected != meaning.meaning_parsed and "$" in meaning.meaning_parsed):
                    meaning.meaning_parsed = corrected

    logger.info(f"청크 {chunk_index} 파싱 완료: {len(parsed.words) if parsed and parsed.words else 0}개 단어 추출")
    return parsed or ParsedChunk(words=[])


def parse_pdf(
    pdf_path: str,
    model_name: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    api_key: str | None = None,
    chunk_size: int = CHUNK_SIZE_PAGES,
    progress_callback: Callable[[float, str], None] | None = None
) -> list[Word]:
    
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    # 1. 문서 정보 미리 파악
    with pdfium.PdfDocument(pdf_path) as pdf:
        total_pages = len(pdf)
    
    if total_pages == 0:
        return []

    chunks = chunk_page_indices(total_pages, chunk_size)
    total_chunks = len(chunks)
    
    llm_engine = build_llm(model_name=model_name, temperature=temperature, api_key=api_key)

    all_words: list[Word] = []
    failed_chunks: list[int] = []
    
    if progress_callback:
        progress_callback(5.0, f"초고속 병렬 준비 완료 (총 {total_pages}페이지, {total_chunks}청크)")

    start_time = time.time()
    completed = 0
    max_workers = 3  # Gemini API Rate Limit 방지를 위해 기존 15에서 3으로 하향 조정

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 렌더링과 파싱을 한 번에 submit
        future_to_idx = {
            executor.submit(parse_chunk, llm_engine, pdf_path, page_indices, idx): idx
            for idx, page_indices in enumerate(chunks)
        }
        
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            completed += 1
            
            try:
                result = future.result()
                all_words.extend(result.words)
            except Exception as e:
                logger.error(f"청크 {idx} 처리 실패: {e}")
                failed_chunks.append(idx)
            
            # ETA 및 진행률 계산
            if progress_callback:
                elapsed = time.time() - start_time
                avg_time_per_chunk = elapsed / completed
                remaining_chunks = total_chunks - completed
                eta_seconds = int(avg_time_per_chunk * remaining_chunks)
                
                percent = 5.0 + (90.0 * (completed / total_chunks))
                
                if remaining_chunks > 0:
                    mins, secs = divmod(eta_seconds, 60)
                    time_str = f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"
                    message = f"AI 스캔 중 ({completed}/{total_chunks}) • 예상 남은 시간: {time_str}"
                else:
                    message = "거의 다 마쳤습니다! 데이터 정리 중..."
                
                progress_callback(round(percent, 1), message)

    if progress_callback:
        progress_callback(100.0, "분석 완벽하게 완료!")

    logger.info(f"=== 고속 파싱 리포트 ===\n  총 길이: {total_pages}페이지\n  총 소요시간: {time.time() - start_time:.1f}초\n  추출 단어: {len(all_words)}개")
    return all_words

