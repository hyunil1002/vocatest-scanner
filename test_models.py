"""
models.py 유닛 테스트 - 핵심 정책 검증
"""
import json
from models import (
    Word, Meaning, Example, WordPayload, MeaningPayload,
    ParsedChunk, parse_meaning_raw,
    WORD_TYPE_BASIC, WORD_TYPE_PHRASAL_VERB, WORD_TYPE_HYPHEN,
)
from pydantic import ValidationError

passed = 0
failed = 0

def test(name, func):
    global passed, failed
    try:
        func()
        print(f"  [PASS] {name}")
        passed += 1
    except Exception as e:
        print(f"  [FAIL] {name}: {e}")
        failed += 1


# ═══════════════════════════════════════
# 1. parse_meaning_raw 테스트
# ═══════════════════════════════════════
print("\n[1] parse_meaning_raw 가공 로직")

def test_meaning_basic():
    result = parse_meaning_raw("$명사$ 과목 || $동사$ 생산하다, 제조하다")
    assert result == "과목;생산하다, 제조하다", f"Got: {result}"

def test_meaning_bracket():
    result = parse_meaning_raw("[명] 사과 || [동] 사과하다")
    assert result == "사과;사과하다", f"Got: {result}"

def test_meaning_single():
    result = parse_meaning_raw("$형용사$ 아름다운")
    assert result == "아름다운", f"Got: {result}"

def test_meaning_no_tag():
    result = parse_meaning_raw("사랑하다")
    assert result == "사랑하다", f"Got: {result}"

test("품사 태그($...$) 제거 + || → ; 변환", test_meaning_basic)
test("품사 태그([]) 제거 + || → ; 변환", test_meaning_bracket)
test("단일 뜻 품사 제거", test_meaning_single)
test("태그 없는 원본 그대로", test_meaning_no_tag)


# ═══════════════════════════════════════
# 2. word_type 자동 분류 테스트
# ═══════════════════════════════════════
print("\n[2] word_type 자동 분류")

def test_type_basic():
    w = Word(word_name="love", meanings=[
        Meaning(word_name="love", meaning_raw="사랑", meaning_parsed="사랑", meaning_order=1)
    ])
    assert w.word_type == WORD_TYPE_BASIC, f"Got: {w.word_type}"

def test_type_hyphen():
    w = Word(word_name="well-known", meanings=[
        Meaning(word_name="well-known", meaning_raw="유명한", meaning_parsed="유명한", meaning_order=1)
    ])
    assert w.word_type == WORD_TYPE_HYPHEN, f"Got: {w.word_type}"

def test_type_phrasal():
    w = Word(word_name="major in", meanings=[
        Meaning(word_name="major in", meaning_raw="전공하다", meaning_parsed="전공하다", meaning_order=1)
    ])
    assert w.word_type == WORD_TYPE_PHRASAL_VERB, f"Got: {w.word_type}"

def test_type_explicit():
    w = Word(word_name="put up with", word_type=2, meanings=[
        Meaning(word_name="put up with", meaning_raw="참다", meaning_parsed="참다", meaning_order=1)
    ])
    assert w.word_type == WORD_TYPE_PHRASAL_VERB, f"Got: {w.word_type}"

test("일반 단어 → type 1", test_type_basic)
test("하이픈 단어 → type 18", test_type_hyphen)
test("동사구 → type 2", test_type_phrasal)
test("명시적 type 2 유지", test_type_explicit)


# ═══════════════════════════════════════
# 3. 예문 중괄호 검증 테스트
# ═══════════════════════════════════════
print("\n[3] 예문 중괄호 {} 검증")

def test_braces_ok():
    ex = Example(meaning_order=1, english_sentence="I {love} you.", korean_translation="나는 너를 사랑해.")
    assert "{love}" in ex.english_sentence

def test_braces_missing():
    try:
        Example(meaning_order=1, english_sentence="I love you.", korean_translation="나는 너를 사랑해.")
        assert False, "검증 실패: 예외가 발생해야 함"
    except ValidationError:
        pass

def test_braces_multiple_rejected():
    try:
        Example(meaning_order=1, english_sentence="She {loves} me, and he {loves} her.", korean_translation="테스트")
        assert False, "검증 실패: 중괄호 2개는 거부되어야 함"
    except ValidationError:
        pass

def test_braces_single_correct():
    ex = Example(meaning_order=1, english_sentence="She {loves} me, and he loves her.", korean_translation="그녀는 나를 사랑하고, 그는 그녀를 사랑한다.")
    assert ex.english_sentence.count("{") == 1

test("정상 중괄호 1개", test_braces_ok)
test("중괄호 누락 → ValidationError", test_braces_missing)
test("중괄호 2개 → ValidationError", test_braces_multiple_rejected)
test("동일 단어 반복 시 1개만 허용", test_braces_single_correct)


# ═══════════════════════════════════════
# 4. pronunciation_file 자동 생성 테스트
# ═══════════════════════════════════════
print("\n[4] pronunciation_file 자동 생성")

def test_pron_auto():
    w = Word(word_name="produce", meanings=[
        Meaning(word_name="produce", meaning_raw="생산하다", meaning_parsed="생산하다", meaning_order=1)
    ])
    assert w.pronunciation_file == "produce.mp3", f"Got: {w.pronunciation_file}"

def test_pron_hyphen():
    w = Word(word_name="well-known", meanings=[
        Meaning(word_name="well-known", meaning_raw="유명한", meaning_parsed="유명한", meaning_order=1)
    ])
    assert w.pronunciation_file == "well_known.mp3", f"Got: {w.pronunciation_file}"

def test_pron_space():
    w = Word(word_name="pen name", meanings=[
        Meaning(word_name="pen name", meaning_raw="필명", meaning_parsed="필명", meaning_order=1)
    ])
    assert w.pronunciation_file == "pen_name.mp3", f"Got: {w.pronunciation_file}"

test("일반 단어 → 단어명.mp3", test_pron_auto)
test("하이픈 단어 → 언더스코어 변환", test_pron_hyphen)
test("공백 단어 → 언더스코어 변환", test_pron_space)


# ═══════════════════════════════════════
# 5. API 페이로드 직렬화 테스트
# ═══════════════════════════════════════
print("\n[5] API 페이로드 직렬화")

def test_word_payload():
    w = Word(word_name="subject", meanings=[
        Meaning(
            word_name="subject",
            meaning_raw="$명사$ 과목 || $동사$ 생산하다",
            meaning_parsed="과목;생산하다",
            meaning_order=1,
            examples=[
                Example(meaning_order=1, english_sentence="What {subject} do you like?", korean_translation="어떤 과목을 좋아하니?")
            ]
        )
    ])
    payload = WordPayload(word=w)
    data = payload.model_dump(mode="json")
    assert data["status"] == "DRAFT"
    assert data["word"]["word_name"] == "subject"
    # JSON 직렬화 가능한지 확인
    json_str = json.dumps(data, ensure_ascii=False)
    assert len(json_str) > 0

def test_meaning_payload():
    payload = MeaningPayload(
        word_name="love",
        meanings=[
            Meaning(word_name="love", meaning_raw="사랑", meaning_parsed="사랑", meaning_order=1)
        ],
    )
    data = payload.model_dump(mode="json")
    assert data["status"] == "DRAFT"
    assert data["word_name"] == "love"

test("WordPayload에 DRAFT 상태 포함", test_word_payload)
test("MeaningPayload(기존 단어 뜻 추가) DRAFT", test_meaning_payload)


# ═══════════════════════════════════════
# 6. ParsedChunk (LLM 결과 래핑) 테스트
# ═══════════════════════════════════════
print("\n[6] ParsedChunk LLM 결과 래핑")

def test_parsed_chunk():
    raw = {
        "words": [
            {
                "word_name": "produce",
                "word_type": 1,
                "etymology": None,
                "pronunciation_file": None,
                "meanings": [
                    {
                        "word_name": "produce",
                        "meaning_raw": "$동사$ 생산하다",
                        "meaning_parsed": "생산하다",
                        "meaning_order": 1,
                        "examples": [
                            {
                                "meaning_order": 1,
                                "english_sentence": "People are seeking a new way to {produce} energy.",
                                "korean_translation": "사람들은 에너지를 생산하는 새로운 방법을 찾고 있다."
                            }
                        ]
                    }
                ]
            }
        ]
    }
    chunk = ParsedChunk.model_validate(raw)
    assert len(chunk.words) == 1
    assert chunk.words[0].word_name == "produce"
    assert chunk.words[0].meanings[0].examples[0].english_sentence.count("{") == 1

test("LLM JSON → ParsedChunk 검증 성공", test_parsed_chunk)


# =======================================
print(f"\n{'='*45}")
print(f"  Result: PASS={passed} / FAIL={failed}")
print(f"{'='*45}\n")

