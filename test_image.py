from dotenv import load_dotenv
import os
import parser
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv(override=True)
images = parser.extract_images_from_pdf_range('sample_vocab.pdf', [0, 1])
llm = parser.build_llm('gemini-2.5-flash', 0.0, os.environ.get('GOOGLE_API_KEY'))

content = [{'type': 'text', 'text': 'Extract vocabulary'}]
for b64 in images:
    content.append({'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}})

print('Calling LLM with image...')
try:
    res = llm.invoke([SystemMessage(content=parser.SYSTEM_PROMPT_IMAGE), HumanMessage(content=content)])
    print('SUCCESS:', len(res.words))
except Exception as e:
    print('ERROR:', str(e))
