import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

def test_flash_1_5():
    api_key = os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=api_key)
    try:
        response = client.models.generate_content(
            model='gemini-flash-latest',
            contents='Hello'
        )
        print("Success with gemini-flash-latest!")
        print(response.text)
    except Exception as e:
        print(f"Failed with gemini-1.5-flash: {e}")

if __name__ == "__main__":
    test_flash_1_5()
