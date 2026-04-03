import os
import sys
import logging
from dotenv import load_dotenv

# 현재 디렉토리를 path에 추가
sys.path.append(os.getcwd())

from parser import extract_images_from_pdf, build_llm, parse_chunk
from models import ParsedChunk

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("debug_parser")

load_dotenv()

def debug_parsing(pdf_path: str):
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found in environment.")
        return

    print(f"--- Debugging PDF: {pdf_path} ---")
    
    try:
        # 1. 이미지 추출 테스트
        images = extract_images_from_pdf(pdf_path)
        print(f"Successfully extracted {len(images)} pages.")
        
        # 실제 단어가 있는 페이지(3페이지 = 인덱스 2) 테스트
        test_page_idx = 2 if len(images) > 2 else 0
        
        if images:
            import base64
            with open("debug_page.png", "wb") as f:
                f.write(base64.b64decode(images[test_page_idx]))
            print(f"Saved page {test_page_idx+1} to debug_page.png for verification.")
        
        if not images:
            print("No images extracted from PDF.")
            return

        # 2. LLM 호출 테스트
        structured_llm = build_llm(api_key=api_key)
        
        # 테스트 청크 (이미지 1개)
        test_chunk = [images[test_page_idx]]
        
        print(f"Calling Gemini Flash with Native Structured Output (Page {test_page_idx+1})...")
        
        # parse_chunk 호출
        result = parse_chunk(structured_llm, test_chunk, 0)
        
        print(f"--- PARSING RESULT (Page {test_page_idx+1}) ---")
        print(f"Extracted {len(result.words)} words.")
        for word in result.words:
            print(f"Word: {word.word_name}")
            for m in word.meanings:
                print(f"  - Meaning: {m.meaning_parsed}")
                for ex in m.examples:
                    print(f"    - Ex: {ex.english_sentence}")
            
    except Exception as e:
        print(f"An error occurred during debugging: {e}")
        import traceback
        traceback.print_exc()
            
    except Exception as e:
        print(f"An error occurred during debugging: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    # PDF 파일이 있는지 확인
    pdf_files = [f for f in os.listdir(".") if f.endswith(".pdf")]
    if not pdf_files:
        print("No PDF files found in current directory.")
    else:
        # 첫 번째 PDF 파일로 테스트
        debug_parsing(pdf_files[0])
