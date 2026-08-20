"""T3 — 환경변수/경로 설정. 모든 app/ 모듈이 여기서만 KEY와 경로를 가져온다.

준비
    .env에 KAKAO_KEY(T1부터 사용 중)와 OPENAI_API_KEY(T3 신규, Node1/Node3용)가 필요.
"""

import os

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = "data"
BOUNDARY_PATH = f"{DATA_DIR}/boundaries/skorea-municipalities-2018-geo.json"
MASTER_PATH = f"{DATA_DIR}/asf_master_v1.csv"
MASTER_GEOCODED_PATH = f"{DATA_DIR}/asf_master_v1_geocoded.csv"
FARMS_PATH = f"{DATA_DIR}/farms_geocoded.csv"

CACHE_DIR = ".cache"
EXTRACTION_CACHE_PATH = f"{CACHE_DIR}/case_extraction.json"

KAKAO_KEY = os.getenv("KAKAO_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Node1 구조화 추출 / Node3 브리핑 생성에 쓰는 모델. 필요 시 이 상수만 바꾸면 된다.
OPENAI_EXTRACTION_MODEL = "gpt-4.1-mini"
OPENAI_BRIEFING_MODEL = "gpt-4.1-mini"
