from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable
import concurrent.futures
import base64
import io as _io

import pypdfium2 as pdfium
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI, HarmCategory, HarmBlockThreshold

from models import ParsedChunk, Word, parse_meaning_raw

# ──── 로그 설정 ────
DEBUG_LOG_FILE = "parsing_debug.log"
logger = logging.getLogger(__name__)

if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    file_handler = logging.FileHandler(DEBUG_LOG_FILE, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)

# ──────────────────────────────────────────────
# 모델 폴백 체인 (성능 좋은 순서)
# 일일 쿼터 소진 시 자동으로 다음 모델로 강등
# ──────────────────────────────────────────────
MODEL_FALLBACK_CHAIN = [
    "gemini-flash-latest",      # gemini-3-flash (최신, 최고 성능)
    "gemini-2.5-flash-preview-04-17",  # gemini-2.5-flash
    "gemini-2.0-flash",         # gemini-2.0-flash
    "gemini-1.5-flash",         # gemini-1.5-flash (구버전, 쿼터 여유)
]

# 전역 모델 풀 상태 (스레드 안전)
_model_lock = threading.Lock()
_exhausted_models: set[str] = set()   # 일일 쿼터 소진된 모델들
_current_model_idx: int = 0           # 현재 사용 중인 모델 인덱스

def get_active_model() -> str | None:
    """현재 사용 가능한 가장 좋은 모델을 반환한다. 모두 소진 시 None 반환."""
    with _model_lock:
        for i in range(_current_model_idx, len(MODEL_FALLBACK_CHAIN)):
            model = MODEL_FALLBACK_CHAIN[i]
            if model not in _exhausted_models:
                return model
        return None

def mark_model_exhausted(model_name: str) -> str | None:
    """모델을 소진 처리하고 다음 사용 가능한 모델을 반환한다."""
    global _current_model_idx
    with _model_lock:
        if model_name not in _exhausted_models:
            _exhausted_models.add(model_name)
            logger.warning(f"모델 쿼터 소진 처리: {model_name} → 소진된 모델 목록: {_exhausted_models}")
        # 다음 사용 가능한 모델 탐색
        for i in range(len(MODEL_FALLBACK_CHAIN)):
            model = MODEL_FALLBACK_CHAIN[i]
            if model not in _exhausted_models:
                _current_model_idx = i
                logger.info(f"✅ 모델 강등: {model_name} → {model}")
                return model
        return None

def is_daily_quota_error(error_str: str) -> bool:
    """일일 쿼터 초과 에러인지 구분한다 (vs 분당 속도 제한)."""
    return "PerDay" in error_str or "GenerateRequestsPerDayPerProject" in error_str

def reset_model_state():
    """파싱 세션 시작 시 모델 상태를 초기화한다."""
    global _current_model_idx, _exhausted_models
    with _model_lock:
        _exhausted_models = set()
        _current_model_idx = 0

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
CHUNK_SIZE_PAGES = 8           # 텍스트 모드: 8페이지/청크
MIN_TEXT_LENGTH_PER_PAGE = 80  # 텍스트 품질 기준 (미달 시 이미지 폴백)
MAX_AI_CONCURRENT = 5          # 동시 AI 호출 수
AI_SEMAPHORE = threading.Semaphore(MAX_AI_CONCURRENT)

SAFETY_SETTINGS = {
    HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
}

# ──────────────────────────────────────────────
# PDF 텍스트 추출
# ──────────────────────────────────────────────
def extract_text_from_pdf_range(pdf_path: str, page_indices: list[int]) -> tuple[str, bool]:
    texts = []
    total_chars = 0
    with pdfium.PdfDocument(pdf_path) as pdf:
        for i in page_indices:
            if i >= len(pdf): continue
            textpage = pdf[i].get_textpage()
            text = textpage.get_text_range()
            texts.append(f"[Page {i+1}]\n{text}")
            total_chars += len(text)
    avg = total_chars / max(len(page_indices), 1)
    return "\n\n".join(texts), avg >= MIN_TEXT_LENGTH_PER_PAGE


# ──────────────────────────────────────────────
# PDF 이미지 추출 (폴백용)
# ──────────────────────────────────────────────
def extract_images_from_pdf_range(pdf_path: str, page_indices: list[int]) -> list[str]:
    images = []
    with pdfium.PdfDocument(pdf_path) as pdf:
        for i in page_indices:
            if i >= len(pdf): continue
            bitmap = pdf[i].render(scale=1.5)
            buf = _io.BytesIO()
            bitmap.to_pil().convert("RGB").save(buf, format='JPEG', quality=85)
            images.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
    return images


# ──────────────────────────────────────────────
# 청킹
# ──────────────────────────────────────────────
def chunk_page_indices(total_pages: int, chunk_size: int = CHUNK_SIZE_PAGES) -> list[list[int]]:
    return [list(range(i, min(i + chunk_size, total_pages))) for i in range(0, total_pages, chunk_size)]


# ──────────────────────────────────────────────
# 프롬프트
# ──────────────────────────────────────────────
SYSTEM_PROMPT_TEXT = """You are an expert vocabulary extractor. Extract ALL vocabulary words from the provided textbook text.
For each word, provide: word_name, meanings (with meaning_raw using $pos$ tags, meaning_parsed in Korean with semicolons, meaning_order), and examples (english_sentence with {target} in braces, korean_translation).
Output strict JSON. Extract EVERY word you find, including phrasal verbs and idioms."""

SYSTEM_PROMPT_IMAGE = """Extract ALL vocabulary words from the provided textbook images.
Rules: 1. {braces} around target word in english_sentence. 2. $pos$ tags in meaning_raw. 3. meaning_parsed = Korean only, semicolons. 4. Valid JSON."""


# ──────────────────────────────────────────────
# LLM 빌더 (동적 모델 지원)
# ──────────────────────────────────────────────
def build_llm(model_name: str, temperature: float = 0.0, api_key: str | None = None):
    kwargs: dict[str, Any] = {
        "model": model_name,
        "temperature": temperature,
        "max_output_tokens": 8192,
        "safety_settings": SAFETY_SETTINGS,
    }
    if api_key:
        kwargs["google_api_key"] = api_key
    return ChatGoogleGenerativeAI(**kwargs).with_structured_output(ParsedChunk, method="json_schema")


# ──────────────────────────────────────────────
# 청크 파싱 (텍스트 우선 + 모델 폴백)
# ──────────────────────────────────────────────
def parse_chunk(
    api_key: str | None,
    temperature: float,
    pdf_path: str,
    page_indices: list[int],
    chunk_index: int,
    word_counter: list,
    progress_callback: Callable | None,
    total_chunks: int,
    start_time: float,
    completed_counter: list,
) -> ParsedChunk:

    # 1. 텍스트 추출 시도
    text, is_text_ok = extract_text_from_pdf_range(pdf_path, page_indices)

    if is_text_ok:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT_TEXT),
            HumanMessage(content=f"Extract all vocabulary:\n\n{text}")
        ]
        mode = "TEXT"
    else:
        logger.warning(f"청크 {chunk_index}: 텍스트 부족 → 이미지 모드")
        images = extract_images_from_pdf_range(pdf_path, page_indices)
        content = [{"type": "text", "text": "Extract vocabulary from these images."}]
        for b64 in images:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        messages = [SystemMessage(content=SYSTEM_PROMPT_IMAGE), HumanMessage(content=content)]
        mode = "IMAGE"

    # 2. AI 호출 (모델 폴백 체인 + 세마포어)
    parsed = None
    max_retries = 3

    with AI_SEMAPHORE:
        while True:
            current_model = get_active_model()
            if current_model is None:
                logger.error(f"청크 {chunk_index}: 모든 모델 쿼터 소진 — 건너뜀")
                return ParsedChunk(words=[])

            llm = build_llm(current_model, temperature, api_key)

            for attempt in range(max_retries):
                try:
                    t0 = time.time()
                    parsed = llm.invoke(messages)
                    logger.info(f"청크 {chunk_index} [{mode}] [{current_model}] 성공 ({time.time()-t0:.1f}s)")
                    break  # 성공
                except Exception as e:
                    err = str(e)
                    if "429" in err or "RESOURCE_EXHAUSTED" in err:
                        if is_daily_quota_error(err):
                            # 일일 쿼터 소진 → 즉시 모델 교체
                            next_model = mark_model_exhausted(current_model)
                            logger.warning(f"청크 {chunk_index}: [{current_model}] 일일 쿼터 소진 → [{next_model}] 전환")
                            break  # inner loop 탈출 → while 로 재시도
                        else:
                            # 분당 속도 초과 → 잠깐 대기 후 재시도
                            wait = 10 * (attempt + 1)
                            logger.warning(f"청크 {chunk_index}: 분당 속도 초과 → {wait}초 대기")
                            time.sleep(wait)
                    else:
                        logger.error(f"청크 {chunk_index} [{current_model}] 오류: {e}")
                        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
                            f.write(f"\n--- CHUNK {chunk_index} FAILURE ---\nModel: {current_model}\nError: {e}\n")
                        raise

            if parsed is not None:
                break  # 성공 → while 탈출

    # 3. 후처리
    if parsed and parsed.words:
        for word in parsed.words:
            for meaning in word.meanings:
                corrected = parse_meaning_raw(meaning.meaning_raw)
                if not meaning.meaning_parsed or ("$" in meaning.meaning_parsed and corrected != meaning.meaning_parsed):
                    meaning.meaning_parsed = corrected
        word_counter[0] += len(parsed.words)

    result = parsed or ParsedChunk(words=[])
    logger.info(f"청크 {chunk_index} 완료: {len(result.words)}개")

    # 4. 진행률 콜백
    if progress_callback:
        completed_counter[0] += 1
        c = completed_counter[0]
        elapsed = time.time() - start_time
        avg = elapsed / c
        eta = int(avg * (total_chunks - c))
        percent = 5.0 + 90.0 * (c / total_chunks)

        active = get_active_model() or "없음"
        if total_chunks - c > 0:
            mins, secs = divmod(eta, 60)
            eta_str = f"{mins}분 {secs}초" if mins > 0 else f"{secs}초"
            msg = f"AI 스캔 ({c}/{total_chunks}) • 남은: {eta_str} • 추출: {word_counter[0]}개 [{active.split('-')[1] if '-' in active else active}]"
        else:
            msg = f"마무리 중... 총 {word_counter[0]}개 단어 추출"

        progress_callback(round(percent, 1), msg)

    return result


# ──────────────────────────────────────────────
# 메인 진입점
# ──────────────────────────────────────────────
def parse_pdf(
    pdf_path: str,
    model_name: str = MODEL_FALLBACK_CHAIN[0],  # 기본은 3-flash
    temperature: float = 0.0,
    api_key: str | None = None,
    chunk_size: int = CHUNK_SIZE_PAGES,
    progress_callback: Callable[[float, str], None] | None = None,
) -> list[Word]:

    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(f"PDF 파일을 찾을 수 없습니다: {pdf_path}")

    # 세션 시작 시 모델 상태 초기화
    reset_model_state()

    with pdfium.PdfDocument(pdf_path) as pdf:
        total_pages = len(pdf)

    if total_pages == 0:
        return []

    chunks = chunk_page_indices(total_pages, chunk_size)
    total_chunks = len(chunks)

    all_words: list[Word] = []
    failed_chunks: list[int] = []
    word_counter = [0]
    completed_counter = [0]

    if progress_callback:
        active = get_active_model() or MODEL_FALLBACK_CHAIN[0]
        progress_callback(5.0, f"파이프라인 시작 — {total_pages}p / {total_chunks}청크 / 모델: {active}")

    start_time = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_AI_CONCURRENT + 2) as executor:
        future_to_idx = {
            executor.submit(
                parse_chunk,
                api_key, temperature, pdf_path, page_indices, idx,
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
                logger.error(f"청크 {idx} 최종 실패: {e}")
                failed_chunks.append(idx)

    if progress_callback:
        active = get_active_model() or "exhausted"
        progress_callback(100.0, f"완료! {len(all_words)}개 단어 추출 (실패 청크: {len(failed_chunks)}개)")

    elapsed = time.time() - start_time
    logger.info(f"=== 파싱 리포트 ===\n  페이지: {total_pages} / 소요: {elapsed:.1f}s / 단어: {len(all_words)}개 / 실패: {failed_chunks}")
    return all_words
