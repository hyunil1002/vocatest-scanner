from __future__ import annotations

import base64
import json
import logging
import math
import os
import time
from typing import Any, Callable
import io

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
CHUNK_SIZE_PAGES = 2
DEFAULT_MODEL = "gemini-flash-latest"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_IMAGE_SCALE = 3.0  # 4.0에서 3.0으로 조정 (용량 제한 및 성능 균형)

# ── 안전 필터 설정 (오탐 방지용 비활성화) ──
SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ──────────────────────────────────────────────
# 1. PDF 페이지를 이미지(Base64)로 추출
# ──────────────────────────────────────────────
def extract_images_from_pdf(
    pdf_path: str,
    scale: float = DEFAULT_IMAGE_SCALE,
    progress_callback: Callable[[int, str], None] | None = None
) -> list[str]:
    """
    PDF의 각 페이지를 고해상도 PNG 이미지로 변환한 후 Base64 문자열 리스트로 반환한다.
    """
    if not os.path.isfile(pdf_path):
        logger.error(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    base64_images: list[str] = []
    
    try:
        with pdfium.PdfDocument(pdf_path) as pdf:
            total_pages = len(pdf)
            for i in range(total_pages):
                page = pdf[i]
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                
                img_byte_arr = io.BytesIO()
                pil_image.save(img_byte_arr, format='PNG')
                img_bytes = img_byte_arr.getvalue()
                
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                base64_images.append(b64)
                
                if progress_callback:
                    # 이미지 변환 단계는 총 진행의 10% 정도 할당
                    pct = int((i + 1) / total_pages * 10)
                    progress_callback(pct, f"PDF 문서 확인 중... ({i+1}/{total_pages} 페이지)")
                    
                logger.info(f"페이지 {i+1} 이미지 추출 완료 (크기: {len(img_bytes)/1024:.1f} KB)")
    except Exception as e:
        logger.error("PDF 이미지 추출 중 오류 발생: %s", e)
        raise

    logger.info("PDF 이미지 변환 완료: %d 페이지 (Scale: %.1f)", len(base64_images), scale)
    return base64_images


# ──────────────────────────────────────────────
# 2. 이미지 청킹
# ──────────────────────────────────────────────
def chunk_images(images: list[str], chunk_size: int = CHUNK_SIZE_PAGES) -> list[list[str]]:
    """페이지 이미지 리스트를 청크 단위로 나눈다."""
    chunks: list[list[str]] = []
    total_chunks = math.ceil(len(images) / chunk_size)

    for i in range(total_chunks):
        start = i * chunk_size
        end = min(start + chunk_size, len(images))
        chunks.append(images[start:end])

    logger.info("청킹 완료: %d 페이지 -> %d 청크 (청크 크기: %d)", len(images), len(chunks), chunk_size)
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


def parse_chunk(structured_llm, chunk_images_b64: list[str], chunk_index: int) -> ParsedChunk:
    total_b64_size = sum(len(b) for b in chunk_images_b64)
    logger.info(f"청크 {chunk_index} 파싱 시작 (이미지 {len(chunk_images_b64)}개, 총 Base64 크기: {total_b64_size/1024/1024:.1f} MB)")

    if total_b64_size > 20 * 1024 * 1024:
        logger.warning(f"경고: 청크 {chunk_index}의 이미지 크기가 20MB를 초과합니다. API가 거부할 수 있습니다.")

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
    try:
        parsed: ParsedChunk = structured_llm.invoke(messages)
        duration = time.time() - start_time
        logger.info(f"청크 {chunk_index} API 응답 성공 (소요시간: {duration:.1f}s)")
    except Exception as e:
        logger.error(f"청크 {chunk_index} Gemini 호출 실패: {e}")
        # 상세 분석을 위해 로그 기록
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
    progress_callback: Callable[[int, str], None] | None = None
) -> list[Word]:
    
    images = extract_images_from_pdf(pdf_path, progress_callback=progress_callback)
    if not images:
        logger.warning("PDF에서 이미지를 추출할 수 없습니다.")
        return []

    chunks = chunk_images(images, chunk_size)
    llm_engine = build_llm(model_name=model_name, temperature=temperature, api_key=api_key)

    all_words: list[Word] = []
    failed_chunks: list[int] = []
    total_chunks = len(chunks)

    if progress_callback:
        progress_callback(10, "AI 모델 스캔 준비 완료!")

    for idx, chunk_imgs in enumerate(chunks):
        if progress_callback:
            # 총 진행 10% ~ 95% 구간을 LLM 청크 파싱에 할당
            base_percent = 10 + int(85 * (idx / total_chunks))
            progress_callback(base_percent, f"AI가 단어를 인식하고 있어요... ({idx+1}/{total_chunks}조각)")
            
        try:
            result = parse_chunk(llm_engine, chunk_imgs, idx)
            all_words.extend(result.words)
        except Exception as e:
            logger.error(f"청크 {idx} 처리 실패, 건너뜀: {e}")
            failed_chunks.append(idx)
            continue

    if progress_callback:
        progress_callback(100, "분석 완료!")

    logger.info(f"=== 파싱 최종 리포트 ===\n  총 페이지: {len(images)}\n  성공 페이지: {len(images)-len(failed_chunks)*chunk_size}\n  총 추출 단어: {len(all_words)}개")
    return all_words
