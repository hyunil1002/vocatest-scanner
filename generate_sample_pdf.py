"""
샘플 영단어 교재 PDF 생성 스크립트
실제 영단어 교재와 유사한 형태로 10개 단어를 2페이지에 걸쳐 생성한다.
"""
import os
from fpdf import FPDF

# 한글 폰트 경로 (Windows 기본)
FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD_PATH = r"C:\Windows\Fonts\malgunbd.ttf"

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "sample_vocab.pdf")

WORDS = [
    {
        "word": "produce",
        "pos": "[동] 생산하다, 제조하다  [명] 농산물",
        "etymology": "pro-(앞으로) + duc(이끌다)",
        "derivatives": "production(생산), productive(생산적인), producer(생산자), product(제품)",
        "synonyms": "manufacture, create, generate",
        "antonyms": "consume, destroy",
        "example_en": "The factory produces over 1,000 cars a day.",
        "example_ko": "그 공장은 하루에 1,000대 이상의 자동차를 생산한다.",
    },
    {
        "word": "subject",
        "pos": "[명] 과목, 주제  [형] ~을 받기 쉬운",
        "etymology": "sub-(아래에) + ject(던지다)",
        "derivatives": "subjective(주관적인), subjection(복종)",
        "synonyms": "topic, theme, matter",
        "antonyms": "",
        "example_en": "What is your favorite subject at school?",
        "example_ko": "학교에서 가장 좋아하는 과목이 뭐니?",
    },
    {
        "word": "major in",
        "pos": "[동사구] ~을 전공하다",
        "etymology": "",
        "derivatives": "major(전공, 주요한)",
        "synonyms": "specialize in, concentrate on",
        "antonyms": "",
        "example_en": "She decided to major in computer science.",
        "example_ko": "그녀는 컴퓨터 과학을 전공하기로 결심했다.",
    },
    {
        "word": "well-known",
        "pos": "[형] 유명한, 잘 알려진",
        "etymology": "well(잘) + known(알려진)",
        "derivatives": "",
        "synonyms": "famous, renowned, celebrated, prominent",
        "antonyms": "unknown, obscure, anonymous",
        "example_en": "He is a well-known scientist in the field of physics.",
        "example_ko": "그는 물리학 분야에서 유명한 과학자이다.",
    },
    {
        "word": "abundant",
        "pos": "[형] 풍부한, 많은",
        "etymology": "ab-(~로부터) + und(넘치다) + -ant(형용사형)",
        "derivatives": "abundance(풍부), abundantly(풍부하게)",
        "synonyms": "plentiful, ample, copious",
        "antonyms": "scarce, rare, insufficient",
        "example_en": "The region has abundant natural resources.",
        "example_ko": "그 지역은 풍부한 천연자원을 갖고 있다.",
    },
    {
        "word": "break the ice",
        "pos": "[숙어] 어색한 분위기를 깨다, 서먹함을 없애다",
        "etymology": "",
        "derivatives": "icebreaker(분위기 전환자)",
        "synonyms": "ease the tension, warm up",
        "antonyms": "",
        "example_en": "He told a joke to break the ice at the meeting.",
        "example_ko": "그는 회의에서 어색한 분위기를 깨기 위해 농담을 했다.",
    },
    {
        "word": "determine",
        "pos": "[동] 결정하다, 결심하다  [동] 알아내다",
        "etymology": "de-(완전히) + termin(끝, 한계)",
        "derivatives": "determination(결심), determined(단호한), determinant(결정 요인)",
        "synonyms": "decide, resolve, establish",
        "antonyms": "hesitate, waver",
        "example_en": "We need to determine the cause of the problem.",
        "example_ko": "우리는 그 문제의 원인을 알아내야 한다.",
    },
    {
        "word": "look forward to",
        "pos": "[동사구] ~을 기대하다, 고대하다 (뒤에 v-ing)",
        "etymology": "",
        "derivatives": "",
        "synonyms": "anticipate, await, expect",
        "antonyms": "dread",
        "example_en": "I look forward to meeting you next week.",
        "example_ko": "다음 주에 당신을 만나기를 고대합니다.",
    },
    {
        "word": "self-esteem",
        "pos": "[명] 자존감, 자부심",
        "etymology": "self-(자기 자신) + esteem(존경, 존중)",
        "derivatives": "esteem(존경하다)",
        "synonyms": "self-respect, self-worth, confidence",
        "antonyms": "self-doubt, insecurity",
        "example_en": "Building self-esteem is important for children.",
        "example_ko": "자존감을 기르는 것은 아이들에게 중요하다.",
    },
    {
        "word": "comprehensive",
        "pos": "[형] 포괄적인, 종합적인",
        "etymology": "com-(함께) + prehend(잡다) + -ive(형용사형)",
        "derivatives": "comprehension(이해), comprehend(이해하다), comprehensible(이해할 수 있는)",
        "synonyms": "thorough, inclusive, extensive, all-encompassing",
        "antonyms": "limited, partial, narrow",
        "example_en": "The report provides a comprehensive analysis of the market.",
        "example_ko": "그 보고서는 시장에 대한 포괄적인 분석을 제공한다.",
    },
]


def create_pdf():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)

    # 한글 폰트 등록
    pdf.add_font("Malgun", "", FONT_PATH, uni=True)
    pdf.add_font("Malgun", "B", FONT_BOLD_PATH, uni=True)

    # ── 표지 ──
    pdf.add_page()
    pdf.set_font("Malgun", "B", 28)
    pdf.cell(0, 60, "", ln=True)
    pdf.cell(0, 15, "VOCATEST", ln=True, align="C")
    pdf.set_font("Malgun", "", 16)
    pdf.cell(0, 12, "Essential Vocabulary Book", ln=True, align="C")
    pdf.cell(0, 12, "Level 1 - 기본편", ln=True, align="C")

    # ── 목차 ──
    pdf.add_page()
    pdf.set_font("Malgun", "B", 18)
    pdf.cell(0, 12, "Contents", ln=True, align="L")
    pdf.ln(5)
    pdf.set_font("Malgun", "", 11)
    pdf.cell(0, 8, "Chapter 1. Core Vocabulary .............. 3", ln=True)
    pdf.cell(0, 8, "Chapter 2. Phrasal Verbs & Idioms ....... 5", ln=True)

    # ── 단어 페이지들 ──
    words_per_page = 5

    for page_idx in range(0, len(WORDS), words_per_page):
        pdf.add_page()
        page_words = WORDS[page_idx : page_idx + words_per_page]

        if page_idx == 0:
            pdf.set_font("Malgun", "B", 16)
            pdf.cell(0, 12, "Chapter 1. Core Vocabulary", ln=True)
            pdf.ln(3)
        else:
            pdf.set_font("Malgun", "B", 16)
            pdf.cell(0, 12, "Chapter 2. Phrasal Verbs & Idioms", ln=True)
            pdf.ln(3)

        for w in page_words:
            # 단어 헤더
            pdf.set_font("Malgun", "B", 13)
            pdf.cell(0, 9, w["word"], ln=True)

            # 품사/뜻
            pdf.set_font("Malgun", "", 10)
            pdf.cell(0, 7, w["pos"], ln=True)

            # 어원
            if w["etymology"]:
                pdf.set_font("Malgun", "", 9)
                pdf.cell(0, 6, f"  [Etymology] {w['etymology']}", ln=True)

            # 파생어
            if w["derivatives"]:
                pdf.cell(0, 6, f"  [Derivatives] {w['derivatives']}", ln=True)

            # 유의어
            if w["synonyms"]:
                pdf.cell(0, 6, f"  [Synonyms] {w['synonyms']}", ln=True)

            # 반의어
            if w["antonyms"]:
                pdf.cell(0, 6, f"  [Antonyms] {w['antonyms']}", ln=True)

            # 예문
            pdf.set_font("Malgun", "", 10)
            pdf.cell(0, 7, f"  Ex) {w['example_en']}", ln=True)
            pdf.cell(0, 7, f"      {w['example_ko']}", ln=True)

            pdf.ln(4)

    pdf.output(OUTPUT_PATH)
    print(f"Sample PDF created: {OUTPUT_PATH}")
    print(f"Total pages: {pdf.pages_count}")


if __name__ == "__main__":
    create_pdf()
