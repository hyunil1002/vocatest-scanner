"""
VocaTest Pipeline - Pydantic 데이터 모델 정의
3단 관계형 DB 스키마: Word -> Meaning -> Example
+ 확장 필드: 단어구분, 접사/어근, 파생어, 유의어, 반의어
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ──────────────────────────────────────────────
# 1. Example (예문 테이블 - Meaning에 종속)
# ──────────────────────────────────────────────
class Example(BaseModel):
    """예문 모델 - 특정 Meaning에 매핑된다."""

    meaning_order: int = Field(..., ge=1, description="매핑되는 뜻의 순서 (1-based)")
    english_sentence: str = Field(
        ...,
        min_length=1,
        description="타겟 단어가 중괄호 {}로 감싸진 영어 예문",
    )
    korean_translation: str = Field(
        ...,
        min_length=1,
        description="예문의 한글 해석",
    )

    @field_validator("english_sentence")
    @classmethod
    def validate_braces(cls, v: str) -> str:
        """예문에 최소 하나의 중괄호 쌍이 존재하는지 확인한다. 없으면 경고 출력."""
        if "{" not in v or "}" not in v:
            import logging
            logging.getLogger(__name__).warning(f"예문에 중괄호 {{}}가 누락되었습니다: {v}")
            return v  # 에러를 던지지 않고 그대로 반환하여 파이프라인 중단 방지
            
        brace_count = len(re.findall(r"\{[^}]+\}", v))
        if brace_count > 1:
            import logging
            logging.getLogger(__name__).warning(f"예문에 중괄호가 {brace_count}개 발견되었습니다: {v}")
            
        return v


# ──────────────────────────────────────────────
# 2. Meaning (뜻 테이블 - Word에 종속)
# ──────────────────────────────────────────────
class Meaning(BaseModel):
    """뜻 모델 - 특정 Word에 매핑된다."""

    word_name: str = Field(..., min_length=1, description="매핑되는 영단어")
    meaning_raw: str = Field(
        ...,
        min_length=1,
        description="원본 뜻 (품사 태그 포함, 예: $명사$ 과목 || $동사$ 생산하다)",
    )
    meaning_parsed: str = Field(
        ...,
        min_length=1,
        description="주관식 정답용 가공 뜻 (품사 제거, 세미콜론 구분, 예: 과목;생산하다)",
    )
    meaning_order: int = Field(..., ge=1, description="뜻 순서 (1-based)")
    examples: list[Example] = Field(default_factory=list, description="이 뜻에 매핑된 예문 목록")


# ──────────────────────────────────────────────
# 3. Word (단어 테이블) — 확장 필드 포함
# ──────────────────────────────────────────────

# 단어 타입 코드 상수
WORD_TYPE_BASIC = 1           # 일반 단어 (명사, 형용사, 부사, 명사구 등)
WORD_TYPE_PHRASAL_VERB = 2    # 동사구 (예: major in, put up with)
WORD_TYPE_HYPHEN = 18         # 하이픈 포함 단어 (예: well-known)

VALID_WORD_TYPES = {WORD_TYPE_BASIC, WORD_TYPE_PHRASAL_VERB, WORD_TYPE_HYPHEN}

# 단어 구분 코드 상수
WORD_CLASS_VOCABULARY = "vocabulary"   # 일반 어휘
WORD_CLASS_IDIOM = "idiom"             # 숙어/관용구
WORD_CLASS_COLLOCATION = "collocation" # 연어
WORD_CLASS_PHRASE = "phrase"           # 구문

VALID_WORD_CLASSES = {
    WORD_CLASS_VOCABULARY,
    WORD_CLASS_IDIOM,
    WORD_CLASS_COLLOCATION,
    WORD_CLASS_PHRASE,
}


class Word(BaseModel):
    """단어 모델 - 최상위 엔티티."""

    word_name: str = Field(..., min_length=1, description="영단어 스펠링")
    word_type: int = Field(
        default=WORD_TYPE_BASIC,
        description="단어 타입 코드 (1=기본, 2=동사구, 18=하이픈)",
    )
    word_class: str = Field(
        default=WORD_CLASS_VOCABULARY,
        description="단어 구분 (vocabulary, idiom, collocation, phrase)",
    )
    etymology: Optional[str] = Field(
        default=None,
        description="어원/접사 정보 (예: pro-(앞으로) + duc-(이끌다))",
    )
    roots: list[str] = Field(
        default_factory=list,
        description="접사/어근 목록 (예: ['pro- (앞으로)', 'duc (이끌다)', '-tion (명사형)'])",
    )
    derivatives: list[str] = Field(
        default_factory=list,
        description="파생어 목록 (예: ['production', 'productive', 'producer'])",
    )
    synonyms: list[str] = Field(
        default_factory=list,
        description="유의어 목록 (예: ['manufacture', 'create', 'generate'])",
    )
    antonyms: list[str] = Field(
        default_factory=list,
        description="반의어 목록 (예: ['consume', 'destroy'])",
    )
    pronunciation_file: Optional[str] = Field(
        default=None,
        description="mp3 파일명 (보통 단어명.mp3)",
    )
    meanings: list[Meaning] = Field(
        default_factory=list,
        min_length=1,
        description="이 단어의 뜻 목록 (최소 1개)",
    )

    @field_validator("word_type")
    @classmethod
    def validate_word_type(cls, v: int) -> int:
        if v not in VALID_WORD_TYPES:
            raise ValueError(
                f"유효하지 않은 word_type: {v}. "
                f"허용값: {sorted(VALID_WORD_TYPES)}"
            )
        return v

    @field_validator("word_class")
    @classmethod
    def validate_word_class(cls, v: str) -> str:
        if v not in VALID_WORD_CLASSES:
            raise ValueError(
                f"유효하지 않은 word_class: {v}. "
                f"허용값: {sorted(VALID_WORD_CLASSES)}"
            )
        return v

    @model_validator(mode="after")
    def auto_set_pronunciation(self) -> "Word":
        if self.pronunciation_file is None:
            safe_name = re.sub(r"[\s\-]+", "_", self.word_name.lower())
            self.pronunciation_file = f"{safe_name}.mp3"
        return self

    @model_validator(mode="after")
    def auto_detect_word_type(self) -> "Word":
        if self.word_type == WORD_TYPE_BASIC:
            if "-" in self.word_name:
                self.word_type = WORD_TYPE_HYPHEN
            elif " " in self.word_name and _looks_like_phrasal_verb(self.word_name):
                self.word_type = WORD_TYPE_PHRASAL_VERB
        return self


def _looks_like_phrasal_verb(word: str) -> bool:
    particles = {
        "in", "on", "up", "out", "off", "down", "over", "away",
        "about", "around", "through", "with", "for", "to", "at",
        "into", "onto", "upon", "after", "from", "by", "along",
        "across", "back", "forward", "ahead",
    }
    parts = word.lower().split()
    if len(parts) < 2 or len(parts) > 5:
        return False
    return parts[-1] in particles or (len(parts) >= 2 and parts[1] in particles)


# ──────────────────────────────────────────────
# 4. API 전송용 페이로드 Wrapper
# ──────────────────────────────────────────────
class WordPayload(BaseModel):
    """어드민 API로 전송할 최종 페이로드."""
    word: Word
    status: str = Field(default="DRAFT", description="어드민 검수 대기 상태")


class MeaningPayload(BaseModel):
    """기존 단어에 뜻/예문만 추가할 때 사용하는 페이로드."""
    word_name: str
    meanings: list[Meaning]
    status: str = Field(default="DRAFT", description="어드민 검수 대기 상태")


# ──────────────────────────────────────────────
# 5. LLM 파싱 결과 래핑용 (한 청크에서 여러 단어)
# ──────────────────────────────────────────────
class ParsedChunk(BaseModel):
    """LLM이 한 번의 호출로 반환하는 파싱 결과 (여러 단어 포함)."""
    words: list[Word] = Field(default_factory=list, description="파싱된 단어 목록")


# ──────────────────────────────────────────────
# 유틸 함수: meaning_raw -> meaning_parsed 변환
# ──────────────────────────────────────────────
def parse_meaning_raw(meaning_raw: str) -> str:
    """
    원본 뜻(meaning_raw)에서 품사 태그를 제거하고,
    구분자(||)를 세미콜론(;)으로 변환하여 meaning_parsed를 생성한다.

    예시:
        "$명사$ 과목 || $동사$ 생산하다, 제조하다"
        -> "과목;생산하다, 제조하다"
    """
    text = meaning_raw
    text = re.sub(r"\$[^$]+\$", "", text)
    text = re.sub(r"\[[^\]]+\]", "", text)
    text = re.sub(r"\s*\|\|\s*", ";", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*;\s*", ";", text)
    return text

# ──────────────────────────────────────────────
# 6. Streamlit UI용 평탄화(Flatten) & 역평탄화(Unflatten) 유틸
# ──────────────────────────────────────────────
import pandas as pd
import ast

def flatten_document(words: list[Word]) -> pd.DataFrame:
    """
    3단 구조(Word->Meaning->Example)를 2D DataFrame으로 평탄화한다.
    리스트형 필드는 쉼표(,) 구분 문자열로 변환하여 에디터에서 수정하기 쉽게 만든다.
    """
    rows = []
    for w in words:
        base_word = {
            "word_name": w.word_name,
            "word_type": w.word_type,
            "word_class": w.word_class,
            "etymology": w.etymology or "",
            "roots": ", ".join(w.roots),
            "derivatives": ", ".join(w.derivatives),
            "synonyms": ", ".join(w.synonyms),
            "antonyms": ", ".join(w.antonyms),
        }
        
        for m in w.meanings:
            base_meaning = {
                **base_word,
                "meaning_order": m.meaning_order,
                "meaning_raw": m.meaning_raw,
                "meaning_parsed": m.meaning_parsed,
            }
            
            if not m.examples:
                # 뜻은 있는데 예문이 없는 경우
                rows.append({
                    **base_meaning,
                    "english_sentence": "",
                    "korean_translation": ""
                })
            else:
                for ex in m.examples:
                    rows.append({
                        **base_meaning,
                        "english_sentence": ex.english_sentence,
                        "korean_translation": ex.korean_translation
                    })
    
    # 빈 DataFrame에 대한 에러 방지
    if not rows:
        return pd.DataFrame(columns=[
            "word_name", "word_type", "word_class", "etymology", "roots", 
            "derivatives", "synonyms", "antonyms", "meaning_order", 
            "meaning_raw", "meaning_parsed", "english_sentence", "korean_translation"
        ])
        
    return pd.DataFrame(rows)

def _parse_comma_list(s: str) -> list[str]:
    if not isinstance(s, str):
        return []
    s = s.strip()
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]

def unflatten_document(df: pd.DataFrame) -> list[Word]:
    """
    수정된 2D DataFrame을 다시 3단 Pydantic 구조로 변환한다.
    """
    word_dict = {}
    
    # 1. Row 반복 순회 
    for _, row in df.iterrows():
        w_name = str(row.get("word_name", "")).strip()
        if not w_name:
            continue
            
        m_order = int(row.get("meaning_order", 1))
        
        # Word 객체 뼈대 캐싱
        if w_name not in word_dict:
            word_dict[w_name] = {
                "word_name": w_name,
                "word_type": int(row.get("word_type", 1)),
                "word_class": str(row.get("word_class", "vocabulary")),
                "etymology": str(row.get("etymology", "")) or None,
                "roots": _parse_comma_list(str(row.get("roots", ""))),
                "derivatives": _parse_comma_list(str(row.get("derivatives", ""))),
                "synonyms": _parse_comma_list(str(row.get("synonyms", ""))),
                "antonyms": _parse_comma_list(str(row.get("antonyms", ""))),
                "meanings_dict": {}
            }
            
        w_info = word_dict[w_name]
        m_dict = w_info["meanings_dict"]
        
        # Meaning 캐싱
        if m_order not in m_dict:
            m_dict[m_order] = {
                "word_name": w_name,
                "meaning_order": m_order,
                "meaning_raw": str(row.get("meaning_raw", "")),
                "meaning_parsed": str(row.get("meaning_parsed", "")),
                "examples": []
            }
            
        # Example 추가
        eng_sent = str(row.get("english_sentence", "")).strip()
        kor_trans = str(row.get("korean_translation", "")).strip()
        
        if eng_sent and kor_trans:
            m_dict[m_order]["examples"].append({
                "meaning_order": m_order,
                "english_sentence": eng_sent,
                "korean_translation": kor_trans
            })
            
    # 2. Pydantic 객체로 빌드
    final_words = []
    for w_name, w_info in word_dict.items():
        meanings_list = []
        for m_order in sorted(w_info["meanings_dict"].keys()):
            m_data = w_info["meanings_dict"][m_order]
            meanings_list.append(Meaning(**m_data))
            
        final_words.append(Word(
            word_name=w_info["word_name"],
            word_type=w_info["word_type"],
            word_class=w_info["word_class"],
            etymology=w_info["etymology"],
            roots=w_info["roots"],
            derivatives=w_info["derivatives"],
            synonyms=w_info["synonyms"],
            antonyms=w_info["antonyms"],
            meanings=meanings_list
        ))
        
    return final_words

