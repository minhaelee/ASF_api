"""ASF v3 — 정책 매뉴얼 RAG 1회성 적재 스크립트 (작업지시서 v1~v4 "하지 않을 것"에
있던 항목을 2026-08-26 피드백으로 뒤집어 진행. app/policy_rag.py 참고).

대상 2건, 서로 다른 분할 전략을 쓴다(둘 다 실제 PDF를 직접 읽고 확인한 구조를 그대로
반영 — 가상의 구조를 가정하지 않는다):

1. 방역실시요령(제2026-23호, 현재 유효본) — "제N조(제목)" 패턴이 깨끗해서 정규식으로
   조문 단위 분할. 33개 조문 확인됨.
2. 긴급행동지침(SOP, 24.12.16) — 조문 번호가 없는 서술형 문서라 목차(TOC)를 직접 읽어
   확보한 31개 섹션 제목으로 분할한다. **pp.1~216(제1~3장)까지만 쓰고 pp.217~
   (제4장 부록 — 구버전 방역실시요령 사본 + OIE 규정)는 페이지 슬라이스로 아예 안 읽는다**
   — 부록의 구버전 조문이 최신 방역실시요령과 섞여 충돌하는 걸 원천 차단하기 위함.
   섹션 제목 문자열을 페이지 텍스트에서 순서대로 찾아 경계를 잡는다(TOC의 쪽번호는
   PDF 텍스트 추출 시 "2 7"처럼 숫자 사이에 공백이 끼는 등 신뢰할 수 없어서 안 씀).

재실행하면 해당 source_file의 기존 행을 지우고 다시 넣어 멱등적이다.
"""

import re
import sys

import psycopg2
from openai import OpenAI
from pgvector.psycopg2 import register_vector
from pypdf import PdfReader

from app.config import (
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
    PGDATABASE,
    PGHOST,
    PGPASSWORD,
    PGPORT,
    PGUSER,
)

REGULATION_PATH = (
    "data/방역공식자료/아프리카돼지열병 방역실시요령(농림축산식품부고시)(제2026-23호)(20260202).pdf"
)
REGULATION_SOURCE = "방역실시요령(제2026-23호, 2026.2.2. 시행)"
ARTICLE_PATTERN = re.compile(r"제(\d+)조\(([^)]+)\)")

SOP_PATH = "data/방역공식자료/[24.12.16] 아프리카돼지열병 긴급행동지침(SOP).pdf"
SOP_SOURCE = "긴급행동지침(SOP, 2024.12.16)"
SOP_LAST_PAGE = 216  # 1-based, 포함. 제4장 부록(구버전 방역실시요령+OIE)은 여기서 하드 제외.

# 목차를 직접 읽어 확보한 섹션 제목 — 순서대로 페이지 텍스트에서 찾아 경계를 삼는다.
# (챕터, 섹션 제목) 튜플. 번호/구두점은 빼고 본문에서도 안정적으로 매칭될 핵심 문구만 둔다.
SOP_SECTIONS: list[tuple[str, str]] = [
    ("제1장 아프리카돼지열병(ASF)이란?", "아프리카돼지열병(African Swine Fever)이란?"),
    ("제1장 아프리카돼지열병(ASF)이란?", "용어 정의"),
    ("제2장 발생상황별 행동체계", "발생상황별 행동체계"),
    ("제2장 발생상황별 행동체계", "관심단계"),
    ("제2장 발생상황별 행동체계", "주의단계"),
    ("제2장 발생상황별 행동체계", "심각단계"),
    ("제2장 발생상황별 행동체계", "진정 및 종식단계"),
    ("제2장 발생상황별 행동체계", "유관부처 협조사항"),
    ("제3장 발생시 긴급대처요령", "아프리카돼지열병 발생시 긴급대처요령"),
    ("제3장 발생시 긴급대처요령", "의심축 발생신고시 조치사항"),
    ("제3장 발생시 긴급대처요령", "의심축을 발견한 축산관련 종사자의 조치사항"),
    ("제3장 발생시 긴급대처요령", "시료채취, 송부 및 진단"),
    ("제3장 발생시 긴급대처요령", "초동방역팀 운영요령"),
    ("제3장 발생시 긴급대처요령", "일시이동중지"),
    ("제3장 발생시 긴급대처요령", "발생농장 등 방역지역 방역 요령"),
    ("제3장 발생시 긴급대처요령", "이동제한 요령"),
    ("제3장 발생시 긴급대처요령", "살처분 및 사체처리 요령"),
    ("제3장 발생시 긴급대처요령", "발생농장의 청소·세척 및 소독요령"),
    ("제3장 발생시 긴급대처요령", "역학조사 요령"),
    ("제3장 발생시 긴급대처요령", "이동통제 초소 및 거점소독시설 운용요령"),
    ("제3장 발생시 긴급대처요령", "거점소독시설 근무자 근무요령"),
    ("제3장 발생시 긴급대처요령", "통제초소 근무자 근무요령"),
    ("제3장 발생시 긴급대처요령", "도축장 지정 요령"),
    ("제3장 발생시 긴급대처요령", "도축부산물 처리요령"),
    ("제3장 발생시 긴급대처요령", "사료 공급 요령"),
    ("제3장 발생시 긴급대처요령", "가축분뇨 처리요령"),
    ("제3장 발생시 긴급대처요령", "방역지역별 이동제한 해제 및 종식"),
    ("제3장 발생시 긴급대처요령", "살처분 농장의 가축 재입식 요령"),
    ("제3장 발생시 긴급대처요령", "야생멧돼지에서 검출 시 방역조치"),
    ("제3장 발생시 긴급대처요령", "도축장 및 동물원에서 발생 시 방역조치"),
    ("제3장 발생시 긴급대처요령", "살처분 등 참여자 예방교육 및 심리지원"),
]

# 목차 페이지에도 이 제목들이 전부 나오므로(그 자체가 목차니까), 본문 검색은 목차를
# 넘긴 페이지부터 시작해야 한다. 실측(인덱스 0,1=표지 공백, 2=목차 전체 한 페이지,
# 3=공백, 4="1"만 있는 페이지, 5=공백, 6="제1장...1 정 의..." 실제 본문 시작) — 인덱스
# 2에서 시작하면 목차 한 페이지 안에서 31개 제목이 전부(잘못) 매칭돼버린다.
SOP_BODY_START_PAGE_INDEX = 6


def _norm(s: str) -> str:
    """공백류를 전부 지운 비교용 문자열. PDF 추출 시 줄바꿈/여백으로 같은 문구가
    다르게 쪼개지는 걸 흡수하기 위함(예: "1 정  의" 같은 불규칙 간격)."""
    return re.sub(r"\s+", "", s)


def _extract_regulation_articles() -> list[dict]:
    reader = PdfReader(REGULATION_PATH)
    text = "\n".join(p.extract_text() for p in reader.pages)

    matches = list(ARTICLE_PATTERN.finditer(text))
    if len(matches) != 33:
        print(f"[ingest_policy_pdf] 경고: 방역실시요령 조문 수가 33이 아니라 {len(matches)}건 "
              f"— PDF가 바뀌었을 수 있음. 계속 진행하되 확인 필요.")

    chunks = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        article_no = f"제{m.group(1)}조"
        title = m.group(2)
        content = text[start:end].strip()
        chunks.append({
            "source_file": REGULATION_SOURCE,
            "article_no": article_no,
            "title": title,
            "content": content,
        })
    return chunks


def _extract_sop_sections() -> list[dict]:
    reader = PdfReader(SOP_PATH)
    pages_text = [p.extract_text() or "" for p in reader.pages[:SOP_LAST_PAGE]]

    # 각 섹션 제목이 처음 등장하는 페이지 인덱스를 순서대로(커서 전진) 찾는다 —
    # 목차 페이지를 건너뛰고 본문에서부터 찾으므로 목차와 오매칭될 일이 없다.
    boundaries: list[tuple[int, str, str]] = []  # (page_idx, chapter, title)
    cursor = SOP_BODY_START_PAGE_INDEX
    missing = []
    for chapter, title in SOP_SECTIONS:
        target = _norm(title)
        found_idx = None
        # 제목이 페이지 경계에서 줄바꿈될 수 있으니 인접 2페이지를 합쳐서 비교한다.
        for idx in range(cursor, len(pages_text) - 1):
            window = _norm(pages_text[idx] + pages_text[idx + 1])
            if target in window:
                found_idx = idx
                break
        if found_idx is None:
            missing.append(title)
            continue
        boundaries.append((found_idx, chapter, title))
        cursor = found_idx  # 다음 섹션은 이 지점 이후부터 찾는다(같은 페이지에 여러 섹션 시작 가능)

    if missing:
        print(f"[ingest_policy_pdf] 경고: SOP에서 못 찾은 섹션 제목 {len(missing)}건 "
              f"(건너뜀, PDF 추출 텍스트가 예상과 다를 수 있음): {missing}")

    chunks = []
    for i, (page_idx, chapter, title) in enumerate(boundaries):
        end_idx = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(pages_text)
        # 다음 섹션 제목이 같은 페이지에서 발견되면 end_idx == page_idx가 되는데, 그럴
        # 때도 이 섹션이 시작된 그 페이지 자체는 내용에 포함해야 한다(0글자가 되면 안 됨).
        end_idx = max(end_idx, page_idx + 1)
        content = "\n".join(pages_text[page_idx:end_idx]).strip()
        full_title = f"{chapter} - {title}"

        parts = _split_long_content(content)
        for j, part in enumerate(parts):
            part_title = full_title if len(parts) == 1 else f"{full_title} ({j + 1}/{len(parts)})"
            chunks.append({
                "source_file": SOP_SOURCE,
                "article_no": None,
                "title": part_title,
                "content": part,
            })
    return chunks


# 임베딩 모델 입력 한도(8192 토큰)를 안전하게 피하기 위한 상한. 살처분 및 사체처리
# 요령처럼 44쪽짜리 섹션이 실제로 있어서(2026-08-26 실측 — 5만자 넘어 400-500-Error 확인),
# 조문 단위와 달리 SOP는 섹션 하나가 이 한도를 넘을 수 있다. 문단(빈 줄) 경계에서만 잘라
# 문장이 중간에 끊기지 않게 한다.
_MAX_CHUNK_CHARS = 3000


def _split_long_content(content: str) -> list[str]:
    if len(content) <= _MAX_CHUNK_CHARS:
        return [content]

    paragraphs = content.split("\n")
    parts: list[str] = []
    current = ""
    for para in paragraphs:
        if current and len(current) + len(para) + 1 > _MAX_CHUNK_CHARS:
            parts.append(current.strip())
            current = para
        else:
            current = f"{current}\n{para}" if current else para
    if current.strip():
        parts.append(current.strip())
    return parts


def _ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS policy_chunks (
                id          SERIAL PRIMARY KEY,
                source_file TEXT NOT NULL,
                article_no  TEXT,
                title       TEXT,
                content     TEXT NOT NULL,
                embedding   VECTOR(1536) NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )
    conn.commit()
    register_vector(conn)


def _embed_all(client: OpenAI, texts: list[str]) -> list[list[float]]:
    # OpenAI 임베딩 API는 배치 입력을 지원한다 — 33+31개 정도는 한 번에 보내도 된다.
    resp = client.embeddings.create(model=OPENAI_EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in resp.data]


def ingest(source_file: str, chunks: list[dict], conn, client: OpenAI) -> int:
    # 내용이 없는 청크(예: 텍스트 없이 그림/표지로만 된 챕터 구분 페이지)는 임베딩
    # API가 빈 문자열을 거부하기도 하고 애초에 검색에 쓸모도 없어 건너뛴다.
    empty_titles = [c["title"] for c in chunks if not c["content"]]
    chunks = [c for c in chunks if c["content"]]
    if empty_titles:
        print(f"[ingest_policy_pdf] {source_file}: 내용 없는 섹션 {len(empty_titles)}건 건너뜀: {empty_titles}")

    if not chunks:
        print(f"[ingest_policy_pdf] {source_file}: 추출된 청크 0개 — 적재 건너뜀")
        return 0

    embeddings = _embed_all(client, [c["content"] for c in chunks])

    with conn.cursor() as cur:
        cur.execute("DELETE FROM policy_chunks WHERE source_file = %s;", (source_file,))
        for chunk, emb in zip(chunks, embeddings):
            cur.execute(
                """
                INSERT INTO policy_chunks (source_file, article_no, title, content, embedding)
                VALUES (%s, %s, %s, %s, %s);
                """,
                (chunk["source_file"], chunk["article_no"], chunk["title"], chunk["content"], emb),
            )
    conn.commit()
    print(f"[ingest_policy_pdf] {source_file}: {len(chunks)}개 청크 적재 완료")
    return len(chunks)


def main() -> None:
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    client = OpenAI(api_key=OPENAI_API_KEY)
    conn = psycopg2.connect(host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD)
    _ensure_schema(conn)

    reg_chunks = _extract_regulation_articles()
    print(f"[ingest_policy_pdf] 방역실시요령: {len(reg_chunks)}개 조문 추출")
    ingest(REGULATION_SOURCE, reg_chunks, conn, client)

    sop_chunks = _extract_sop_sections()
    print(f"[ingest_policy_pdf] SOP(pp.1~{SOP_LAST_PAGE}): {len(sop_chunks)}개 섹션 추출")
    ingest(SOP_SOURCE, sop_chunks, conn, client)

    conn.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
