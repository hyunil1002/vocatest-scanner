# 📘 VocaTest AI Scanner

VocaTest AI Scanner는 영어 단어장 PDF 문서를 지능적으로 분석하여 디지털 데이터로 변환해 주는 도구입니다. **Toss 스타일의 심플한 UI**와 **Google Gemini-1.5-Flash** 모델을 탑재하여 빠르고 정확한 데이터 추출을 지원합니다.

## ✨ 주요 기능
- **PDF 고해상도 스캔**: PDF 페이지를 이미지로 변환하여 텍스트 오인식 최소화.
- **Gemini AI 분석**: 단어, 뜻, 파생어, 예문 등을 구조화된 JSON 데이터로 자동 추출.
- **Toss 2.0 스타일 UX**: 직관적이고 깔끔한 화이트 앤 블루 톤의 인터페이스.
- **실시간 진행률 표시**: 처리 중임을 알리는 'Shimmer' 애니메이션 탑재.
- **데이터 검수 및 수정**: 추출된 데이터를 표 형식으로 확인하고 직접 수정 가능.
- **엑셀 다운로드**: 가공된 데이터를 즉시 엑셀 파일(`.xlsx`)로 저장.

## 🚀 빠른 시작 (로컬 실행)
1. 파이썬 설치 (Python 3.9+)
2. 종속성 설치: `pip install -r requirements.txt`
3. 환경 변수 설정: `.env` 파일에 `GOOGLE_API_KEY` 입력
4. 실행: `streamlit run app.py`

---
*Developed for VocaTest Data Pipeline.*
