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
LIVESTOCK_STATS_PATH = f"{DATA_DIR}/18년-26년+전국+시군별+일반돼지+사육규모+통계.csv"

CACHE_DIR = ".cache"
EXTRACTION_CACHE_PATH = f"{CACHE_DIR}/case_extraction.json"

KAKAO_KEY = os.getenv("KAKAO_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MAFRA_API_KEY = os.getenv("MAFRA_API_KEY")

# Node1 구조화 추출 / Node3 브리핑 생성에 쓰는 모델. 필요 시 이 상수만 바꾸면 된다.
# 2026-08-24: 기존 gpt-4.1-mini는 현재 OPENAI_API_KEY가 속한 프로젝트에서 403(모델
# 접근 권한 없음)이 나 gpt-5.4-mini로 교체(client.models.list()로 실제 접근 가능 모델
# 확인 후 결정 — gpt-5.4-nano/gpt-5.6-luna/gpt-5.6-terra도 가능하나 mini가 기존
# 용도(구조화 추출/짧은 브리핑 문장)에 맞는 크기).
OPENAI_EXTRACTION_MODEL = "gpt-5.4-mini"
OPENAI_BRIEFING_MODEL = "gpt-5.4-mini"

# ASF v4 4.7 — 갱신 계층(mafra API). 엔드포인트/제약은 작업지시서 4.7에서 실측 확인됨.
MAFRA_API_BASE = "http://211.237.50.150:7080/openapi"
MAFRA_GRID_ID = "Grid_20151204000000000316_1"
MAFRA_PAGE_SIZE = 999
MAFRA_REFRESH_INTERVAL_HOURS = 6
# 자동 갱신은 전체(~46,084건, 47페이지)를 매번 안 받고 최근 N행만 받는다(2026-08-24
# 변경 — app/master_refresh.py 모듈 docstring 참고). 넉넉하게 잡아도 페이지 수가
# 전체 대비 1/10 이하라 서버 간헐적 불안정에 걸릴 확률이 크게 준다.
MAFRA_RECENT_WINDOW_ROWS = 5000

# 2026-08-26 — 정책 매뉴얼 RAG(app/policy_rag.py, scripts/ingest_policy_pdf.py)용.
# .env에 이미 있던 값인데(로컬 pgvector) 이번에 처음 코드에서 읽는다.
PGHOST = os.getenv("PGHOST")
PGPORT = os.getenv("PGPORT")
PGDATABASE = os.getenv("PGDATABASE")
PGUSER = os.getenv("PGUSER")
PGPASSWORD = os.getenv("PGPASSWORD")

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"

POLICY_DISCLAIMER = (
    "이 답변은 방역실시요령·긴급행동지침(SOP) 조문/섹션 검색 결과를 요약한 참고용 "
    "정보이며, 법적 효력이 있는 유권해석이 아닙니다. 실제 방역 조치는 반드시 관할 "
    "가축방역기관에 재확인하십시오."
)
