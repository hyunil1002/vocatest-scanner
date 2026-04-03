from __future__ import annotations

import base64
import logging
import os
import threading
import time
from typing import Any, Callable
import io
import concurrent.futures

import pypdfium2 as pdfium
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold

from models import Example, Meaning, ParsedChunk, Word, parse_meaning_raw

# ──── 로그 설정 ────
DEBUG_LOG_FILE = "parsing_debug.log"
logger = logging.getLogger(__name__)

if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    file_handler = logging.FileHandler(DEBUG_LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)

# ──────────────────────────────────────────────
# 설정 상수
# ──────────────────────────────────────────────
CHUNK_SIZE_PAGES = 2          # 2페이지/청크: AI가 더 빠르게 응답 → 첫 결과가 더 빨리 나옴
DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_IMAGE_SCALE = 1.5     # 2.0 → 1.5 해상도: 이미지 크기 44% 감소 → 렌더링·전송 속도 향상

# 속도 vs 안정성 균형 상수
MAX_RENDER_WORKERS = 6        # 렌더링(CPU)은 많이 해도 OK
MAX_AI_CONCURRENT = 3         # AI 동시 호출 제한 (Rate Limit = 분당 ~15 → 3 동시)
AI_SEMAPHORE = threading.Semaphore(MAX_AI_CONCURRENT)  # 모듈 로드시 1회 생성

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
    """지정된 페이지 번호를 JPEG 이미지(Base64)로 변환한다. PNG보다 40% 이상 가볍다."""
    base64_images: list[str] = []
    try:
        with pdfium.PdfDocument(pdf_path) as pdf:
            for i in page_indices:
                if i >= len(pdf): continue
                page = pdf[i]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()

                img_byte_arr = io.BytesIO()
                # PNG → JPEG 변환: 업로드 크기 대폭 감소
                pil_image.convert("RGB").save(img_byte_arr, format='JPEG', quality=85, optimize=True)
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
# 4. LLM 체인 구성
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


# ──────────────────────────────────────────────
# 5. 청크 파싱 (렌더링 + AI 호출 분리)
# ──────────────────────────────────────────────
def parse_chunk(
    structured_llm,
    pdf_path: str,
    page_indices: list[int],
    chunk_index: int,
    word_counter: list,         # [total_so_far]  공유 카운터
    progress_callback: Callable | None,
    total_chunks: int,
    start_time: float,
    completed_counter: list,    # [completed_count]
) -> ParsedChunk:
    """렌더링과 AI 호출을 파이프라인으로 분리하여 최대 처리량을 달성한다."""
    
    # 1. 렌더링 (CPU - 제한 없이 병렬 처리)
    logger.info(f"청크 {chunk_index} 렌더링 시작 (페이지: {page_indices})")
    chunk_images_b64 = extract_images_from_pdf_range(pdf_path, page_indices)
    logger.info(f"청크 {chunk_index} 렌더링 완료 → AI 순번 대기 중")

    content_list = [
        {"type": "text", "text": "Identify and extract all word items from the following images."}
    ]
    for b64 in chunk_images_b64:
        content_list.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=content_list)
    ]

    # 2. AI 호출 (Rate Limit 방지를 위한 세마포어 획득)
    parsed = None
    max_retries = 4

    with AI_SEMAPHORE:
        for attempt in range(max_retries):
            try:
                t0 = time.time()
                parsed = structured_llm.invoke(messages)
                logger.info(f"청크 {chunk_index} AI 성공 ({time.time()-t0:.1f}s)")
                break
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    if attempt < max_retries - 1:
                        wait_time = 15 * (attempt + 1)
                        logger.warning(f"청크 {chunk_index} Rate Limit → {wait_time}초 대기 후 재시도")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"청크 {chunk_index} 최종 실패 (Rate Limit): {e}")
                        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"\n--- CHUNK {chunk_index} FAILURE (429) ---\nError: {e}\n")
                        raise
                else:
                    logger.error(f"청크 {chunk_index} 실패: {e}")
                    with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"\n--- CHUNK {chunk_index} FAILURE ---\nError: {e}\n")
                    raise

    # 3. 후처리 & 콜백
    if parsed and parsed.words:
        for word in parsed.words:
            for meaning in word.meanings:
                corrected = parse_meaning_raw(meaning.meaning_raw)
                if not meaning.meaning_parsed or (corrected != meaning.meaning_parsed and "$" in meaning.meaning_parsed):
                    meaning.meaning_parsed = corrected
        word_counter[0] += len(parsed.words)

    result = parsed or ParsedChunk(words=[])
    word_count = len(result.words)
    logger.info(f"청크 {chunk_index} 완료: {word_count}개 단어")

    # 진행률 콜백 (스레드 안전 업데이트)
    if progress_callback:
        completed_counter[0] += 1
        completed = completed_counter[0]
        elapsed = time.time() - start_time
        avg = elapsed / completed
        eta_seconds = int(avg * (total_chunks - completed))
        percent = 5.0 + (90.0 * (completed / total_chunks))
        
        if total_chunks - completed > 0:
            mins, secs = divmod(eta_seconds, 60)
            eta_str = f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"
            msg = f"AI 스캔 중 ({completed}/{total_chunks}) • 남은 시간: {eta_str} • 추출 {word_counter[0]}개"
        else:
            msg = f"거의 완료! 최종 정리 중... (총 {word_counter[0]}개 단어)"
        progress_callback(round(percent, 1), msg)

    return result


# ──────────────────────────────────────────────
# 6. 메인 파싱 진입점
# ──────────────────────────────────────────────
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

    with pdfium.PdfDocument(pdf_path) as pdf:
        total_pages = len(pdf)

    if total_pages == 0:
        return []

    chunks = chunk_page_indices(total_pages, chunk_size)
    total_chunks = len(chunks)

    llm_engine = build_llm(model_name=model_name, temperature=temperature, api_key=api_key)

    all_words: list[Word] = []
    failed_chunks: list[int] = []
    word_counter = [0]         # 스레드 안전 공유 카운터
    completed_counter = [0]    # 완료된 청크 수

    if progress_callback:
        progress_callback(5.0, f"병렬 파이프라인 시작 ({total_pages}페이지 / {total_chunks}청크)")

    start_time = time.time()

    # 렌더링은 더 많은 워커로, AI 동시성은 세마포어로 별도 제어
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_RENDER_WORKERS) as executor:
        future_to_idx = {
            executor.submit(
                parse_chunk,
                llm_engine, pdf_path, page_indices, idx,
                word_counter, progress_callback, total_chunks, start_time, completed_counter
            ): idx
            for idx, page_indices in enumerate(chunks)
        }

        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                result = future.result()
                all_words.extend(result.words)
            except Exception as e:
                logger.error(f"청크 {idx} 처리 실패: {e}")
                failed_chunks.append(idx)

    if progress_callback:
        progress_callback(100.0, f"분석 완료! 총 {len(all_words)}개 단어 추출")

    elapsed = time.time() - start_time
    logger.info(f"=== 파싱 리포트 ===\n  총 페이지: {total_pages}\n  소요시간: {elapsed:.1f}s\n  추출 단어: {len(all_words)}개\n  실패 청크: {failed_chunks}")
    return all_words
