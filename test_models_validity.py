from dotenv import load_dotenv
import os
import parser
from langchain_core.messages import HumanMessage, SystemMessage
from models import ParsedChunk

load_dotenv(override=True)
api_key = os.environ.get('GOOGLE_API_KEY')

models_to_test = [
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

for m in models_to_test:
    try:
        print(f"Testing {m}...")
        llm = parser.build_llm(m, 0.0, api_key)
        res = llm.invoke([SystemMessage(content="Return valid JSON with words array"), HumanMessage(content="apple, banana")])
        print(f"  -> SUCCESS! Words: {len(res.words)}")
    except Exception as e:
        err_msg = str(e).replace('\n', ' ')
        print(f"  -> ERROR: {err_msg[:150]}...")
