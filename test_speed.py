import importlib
import parser
importlib.reload(parser)
from dotenv import load_dotenv
import os
import time

load_dotenv()

print('=== 텍스트 추출 모드 성능 테스트 ===')
t = time.time()
words = parser.parse_pdf('sample_vocab.pdf', api_key=os.environ.get('GOOGLE_API_KEY'))
elapsed = time.time() - t
print(f'완료! {len(words)}개 단어, {elapsed:.1f}초')
for w in words[:5]:
    m = w.meanings[0].meaning_parsed if w.meanings else '??'
    print(f'  - {w.word_name}: {m}')
