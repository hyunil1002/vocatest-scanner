"""
VocaTest Pipeline - 메인 실행 파이프라인

파싱된 데이터를 Pydantic으로 최종 검증하고,
어드민 API로 전송하는 엔드투엔드 파이프라인.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from models import MeaningPayload, Word, WordPayload
from parser import parse_pdf

# .env 파일 로드
load_dotenv()

# ──────────────────────────────────────────────
# 로깅 설정
# ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(name)-18s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vocatest.main")


# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
@dataclass
class PipelineConfig:
    """파이프라인 실행 설정."""

    pdf_path: str = ""
    api_base_url: str = "http://localhost:8000"
    api_token: str = ""
    google_api_key: str = ""
    model_name: str = "gemini-flash-latest"
    temperature: float = 0.0
    chunk_size: int = 5
    dry_run: bool = False  # True면 API 전송 없이 JSON만 출력
    output_json_path: str = ""  # 파싱 결과를 JSON 파일로 저장할 경로
    retry_count: int = 3
    retry_delay: float = 2.0


# ──────────────────────────────────────────────
# API 클라이언트
# ──────────────────────────────────────────────
class AdminAPIClient:
    """어드민 API 통신 클라이언트."""

    def __init__(self, base_url: str, token: str = "", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def close(self):
        self.client.close()

    # ─── 중복 검사 ───
    def check_word_exists(self, word_name: str) -> dict[str, Any] | None:
        """
        GET /api/words?search={word_name} 으로 DB에 해당 단어가 존재하는지 조회한다.

        Returns:
            존재하면 단어 데이터 dict, 없으면 None
        """
        try:
            resp = self.client.get("/api/words", params={"search": word_name})
            resp.raise_for_status()
            data = resp.json()

            # API 응답 구조: {"results": [...]} 또는 리스트
            results = data if isinstance(data, list) else data.get("results", [])

            for item in results:
                if item.get("word_name", "").lower() == word_name.lower():
                    logger.info("중복 감지: '%s' 이미 DB에 존재", word_name)
                    return item

            return None

        except httpx.HTTPStatusError as e:
            logger.warning("단어 조회 API 오류 (word=%s): %s", word_name, e)
            return None
        except httpx.RequestError as e:
            logger.error("단어 조회 API 연결 실패 (word=%s): %s", word_name, e)
            return None

    # ─── 새 단어 생성 ───
    def create_word(self, payload: WordPayload) -> dict[str, Any] | None:
        """
        POST /api/words 로 새 단어를 생성한다.
        모든 데이터 페이로드에 status=DRAFT가 포함된다.
        """
        body = payload.model_dump(mode="json")
        try:
            resp = self.client.post("/api/words", json=body)
            resp.raise_for_status()
            logger.info("단어 생성 성공: '%s'", payload.word.word_name)
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "단어 생성 실패 '%s': %s (응답: %s)",
                payload.word.word_name, e, e.response.text,
            )
            return None
        except httpx.RequestError as e:
            logger.error("단어 생성 API 연결 실패 '%s': %s", payload.word.word_name, e)
            return None

    # ─── 기존 단어에 뜻/예문 추가 ───
    def add_meanings(self, payload: MeaningPayload) -> dict[str, Any] | None:
        """
        POST /api/words/{word_name}/meanings 로 기존 단어에 뜻과 예문을 추가한다.
        """
        body = payload.model_dump(mode="json")
        endpoint = f"/api/words/{payload.word_name}/meanings"
        try:
            resp = self.client.post(endpoint, json=body)
            resp.raise_for_status()
            logger.info(
                "뜻 추가 성공: '%s' (%d개 뜻)",
                payload.word_name, len(payload.meanings),
            )
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(
                "뜻 추가 실패 '%s': %s (응답: %s)",
                payload.word_name, e, e.response.text,
            )
            return None
        except httpx.RequestError as e:
            logger.error("뜻 추가 API 연결 실패 '%s': %s", payload.word_name, e)
            return None


# ──────────────────────────────────────────────
# 실행 통계 추적
# ──────────────────────────────────────────────
@dataclass
class PipelineStats:
    """파이프라인 실행 통계."""

    total_words: int = 0
    created: int = 0
    skipped_existing: int = 0
    meanings_added: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=======================================",
            "       VocaTest Pipeline 실행 결과      ",
            "=======================================",
            f"  총 파싱 단어 수  : {self.total_words}",
            f"  신규 생성        : {self.created}",
            f"  기존 단어 (뜻 추가): {self.skipped_existing}",
            f"  뜻 추가 건수     : {self.meanings_added}",
            f"  실패             : {self.failed}",
            "=======================================",
        ]
        if self.errors:
            lines.append("  에러 목록:")
            for err in self.errors:
                lines.append(f"    • {err}")
            lines.append("=======================================")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# 메인 파이프라인
# ──────────────────────────────────────────────
def run_pipeline(config: PipelineConfig) -> PipelineStats:
    """
    엔드투엔드 파이프라인을 실행한다.

    1. PDF에서 텍스트 추출 및 LLM 파싱
    2. Pydantic 검증 (parse_pdf 내부에서 수행)
    3. 중복 검사 후 어드민 API 전송

    Args:
        config: 파이프라인 설정

    Returns:
        실행 통계
    """
    stats = PipelineStats()

    # ── Step 1: PDF 파싱 ──
    logger.info("━━━ Step 1: PDF 파싱 시작 ━━━")
    logger.info("PDF 경로: %s", config.pdf_path)

    words = parse_pdf(
        pdf_path=config.pdf_path,
        model_name=config.model_name,
        temperature=config.temperature,
        api_key=config.google_api_key,
        chunk_size=config.chunk_size,
    )

    stats.total_words = len(words)
    logger.info("파싱된 총 단어 수: %d", stats.total_words)

    if not words:
        logger.warning("파싱된 단어가 없습니다. 파이프라인을 종료합니다.")
        return stats

    # ── Step 1.5: JSON 파일 저장 (선택) ──
    if config.output_json_path:
        _save_parsed_json(words, config.output_json_path)

    # ── Step 2: Dry Run 모드 ──
    if config.dry_run:
        logger.info("━━━ Dry Run 모드: API 전송을 건너뜁니다 ━━━")
        _print_parsed_words(words)
        return stats

    # ── Step 3: API 전송 ──
    logger.info("━━━ Step 2: 어드민 API 전송 시작 ━━━")
    logger.info("API 서버: %s", config.api_base_url)

    client = AdminAPIClient(base_url=config.api_base_url, token=config.api_token)

    try:
        for word in words:
            _process_single_word(client, word, stats, config)
    finally:
        client.close()

    return stats


def _process_single_word(
    client: AdminAPIClient,
    word: Word,
    stats: PipelineStats,
    config: PipelineConfig,
):
    """
    단일 단어를 처리한다: 중복 검사 → 생성 또는 뜻 추가.
    """
    logger.info("처리 중: '%s' (type=%d)", word.word_name, word.word_type)

    # ── 중복 검사 ──
    existing = client.check_word_exists(word.word_name)

    if existing is not None:
        # 기존 단어 → 뜻 + 예문만 추가
        logger.info("기존 단어 '%s' → 뜻/예문만 추가", word.word_name)
        payload = MeaningPayload(
            word_name=word.word_name,
            meanings=word.meanings,
            status="DRAFT",
        )
        result = _retry(
            lambda: client.add_meanings(payload),
            retries=config.retry_count,
            delay=config.retry_delay,
        )
        if result is not None:
            stats.skipped_existing += 1
            stats.meanings_added += len(word.meanings)
        else:
            stats.failed += 1
            stats.errors.append(f"뜻 추가 실패: {word.word_name}")
    else:
        # 새 단어 생성
        payload = WordPayload(word=word, status="DRAFT")
        result = _retry(
            lambda: client.create_word(payload),
            retries=config.retry_count,
            delay=config.retry_delay,
        )
        if result is not None:
            stats.created += 1
        else:
            stats.failed += 1
            stats.errors.append(f"단어 생성 실패: {word.word_name}")


def _retry(func, retries: int = 3, delay: float = 2.0):
    """간단한 재시도 래퍼."""
    for attempt in range(1, retries + 1):
        result = func()
        if result is not None:
            return result
        if attempt < retries:
            logger.warning("재시도 %d/%d (%.1f초 대기)", attempt, retries, delay)
            time.sleep(delay)
    return None


# ──────────────────────────────────────────────
# 유틸 함수
# ──────────────────────────────────────────────
def _save_parsed_json(words: list[Word], output_path: str):
    """파싱 결과를 JSON 파일로 저장한다."""
    data = [w.model_dump(mode="json") for w in words]
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info("파싱 결과 저장 완료: %s (%d개 단어)", output_path, len(words))


def _print_parsed_words(words: list[Word]):
    """파싱 결과를 콘솔에 출력한다."""
    print("\n" + "=" * 65)
    print("  VOCATEST - Parsing Result (Dry Run)")
    print("=" * 65)
    for i, word in enumerate(words, 1):
        print(f"\n  [{i}] {word.word_name}")
        print(f"      type={word.word_type} | class={word.word_class}")
        if word.etymology:
            print(f"      [Etymology]    {word.etymology}")
        if word.roots:
            print(f"      [Roots]        {', '.join(word.roots)}")
        if word.derivatives:
            print(f"      [Derivatives]  {', '.join(word.derivatives)}")
        if word.synonyms:
            print(f"      [Synonyms]     {', '.join(word.synonyms)}")
        if word.antonyms:
            print(f"      [Antonyms]     {', '.join(word.antonyms)}")
        for m in word.meanings:
            print(f"      --- Meaning {m.meaning_order}: {m.meaning_parsed}")
            print(f"          (raw: {m.meaning_raw})")
            for ex in m.examples:
                print(f"          Ex) {ex.english_sentence}")
                print(f"              {ex.korean_translation}")
    print("\n" + "=" * 65)


# ──────────────────────────────────────────────
# CLI 진입점
# ──────────────────────────────────────────────
def parse_args() -> PipelineConfig:
    """커맨드라인 인자를 파싱한다."""
    parser = argparse.ArgumentParser(
        description="VocaTest AI 자동화 파이프라인 - PDF 영단어 교재 파싱 및 어드민 API 전송",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # Dry Run (API 전송 없이 파싱 결과만 확인)
  python main.py --pdf vocab_book.pdf --dry-run

  # JSON 파일로 저장
  python main.py --pdf vocab_book.pdf --dry-run --output result.json

  # 어드민 API로 전송
  python main.py --pdf vocab_book.pdf --api-url http://admin.vocatest.com --api-token YOUR_TOKEN
        """,
    )
    parser.add_argument(
        "--pdf", required=True,
        help="파싱할 영단어 교재 PDF 파일 경로",
    )
    parser.add_argument(
        "--api-url", default="http://localhost:8000",
        help="어드민 API 기본 URL (기본값: http://localhost:8000)",
    )
    parser.add_argument(
        "--api-token", default="",
        help="어드민 API 인증 토큰 (Bearer)",
    )
    parser.add_argument(
        "--model", default="gemini-flash-latest",
        help="사용할 LLM 모델명 (기본값: gemini-flash-latest)",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="LLM 생성 온도 (기본값: 0.0)",
    )
    parser.add_argument(
        "--chunk-size", type=int, default=5,
        help="한 번에 LLM에 보낼 페이지 수 (기본값: 5)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="API 전송 없이 파싱 결과만 출력",
    )
    parser.add_argument(
        "--output", default="",
        help="파싱 결과를 저장할 JSON 파일 경로",
    )
    parser.add_argument(
        "--retry-count", type=int, default=3,
        help="API 전송 실패 시 재시도 횟수 (기본값: 3)",
    )

    args = parser.parse_args()

    return PipelineConfig(
        pdf_path=args.pdf,
        api_base_url=args.api_url,
        api_token=args.api_token,
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        model_name=args.model,
        temperature=args.temperature,
        chunk_size=args.chunk_size,
        dry_run=args.dry_run,
        output_json_path=args.output,
        retry_count=args.retry_count,
    )


def main():
    """메인 진입점."""
    config = parse_args()

    # 필수 환경 검증
    if not config.google_api_key:
        logger.error("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    if not os.path.isfile(config.pdf_path):
        logger.error("PDF 파일을 찾을 수 없습니다: %s", config.pdf_path)
        sys.exit(1)

    # 파이프라인 실행
    start_time = time.time()
    stats = run_pipeline(config)
    elapsed = time.time() - start_time

    # 결과 출력
    print(stats.summary())
    print(f"\n  소요 시간: {elapsed:.1f}초\n")

    if stats.failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
