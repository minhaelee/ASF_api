"""ASF v3 — 정책 매뉴얼 RAG(작업지시서 v1~v4 "하지 않을 것"에 있던 항목을 2026-08-26
피드백으로 뒤집어 진행). scripts/ingest_policy_pdf.py가 채운 policy_chunks(방역실시요령
33 + SOP 75)를 코사인 거리로 검색한다.

저수준 검색 함수(embed_text/retrieve_chunks)만 여기 둔다 — 검색 결과를 어떻게 답으로
합성할지는 호출부 책임(app/field_response.py, 시군 클릭 시 현장 대응 체크리스트 생성)
이다. 처음엔 이 모듈이 자유 질문 Q&A(answer_policy_question)까지 담당했지만, 2026-08-26
피드백으로 "질문에 답하는 도구"가 아니라 "시군 클릭 시 자동 생성되는 체크리스트"로
용도가 바뀌면서 Q&A 전용 로직(NO_MATCH 판정 등)은 걷어냈다.
"""

import sys

import psycopg2
from openai import OpenAI
from pgvector.psycopg2 import register_vector

from app.config import (
    OPENAI_API_KEY,
    OPENAI_EMBEDDING_MODEL,
    PGDATABASE,
    PGHOST,
    PGPASSWORD,
    PGPORT,
    PGUSER,
)

POLICY_TOP_K = 8


def _connect():
    conn = psycopg2.connect(
        host=PGHOST, port=PGPORT, dbname=PGDATABASE, user=PGUSER, password=PGPASSWORD
    )
    register_vector(conn)
    return conn


def embed_text(client: OpenAI, text: str) -> list[float]:
    resp = client.embeddings.create(model=OPENAI_EMBEDDING_MODEL, input=text)
    return resp.data[0].embedding


def retrieve_chunks(client: OpenAI, question: str, top_k: int = POLICY_TOP_K) -> list[dict]:
    """질문 임베딩과 코사인 거리가 가까운 순으로 top_k개 청크를 돌려준다.
    source_file 구분 없이 방역실시요령/SOP를 한 벡터 공간에서 같이 검색한다."""
    q_embedding = embed_text(client, question)
    # pgvector.psycopg2.register_vector()의 자동 어댑팅이 plain list 파라미터에는 안
    # 먹어(2026-08-26 실측 — numeric[]로 잘못 캐스팅되는 오류 확인) 리터럴 문자열로
    # 직접 만들어 ::vector로 캐스팅한다.
    q_embedding_literal = "[" + ",".join(str(x) for x in q_embedding) + "]"

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_file, article_no, title, content, embedding <=> %s::vector AS distance
                FROM policy_chunks
                ORDER BY distance
                LIMIT %s;
                """,
                (q_embedding_literal, top_k),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "source_file": r[0],
            "article_no": r[1],
            "title": r[2],
            "content": r[3],
            "distance": float(r[4]),
        }
        for r in rows
    ]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")
    client = OpenAI(api_key=OPENAI_API_KEY)

    # app/field_response.py가 실제로 쓰는 등급별 고정 질의로 검색 품질을 확인한다.
    for label, query in [
        ("심각", "10km 방역대 내 살처분 대상 농장 현장 조치, 이동제한, 통제초소 운영, 소독, 역학조사 절차"),
        ("주의", "예찰지역·보호지역 예찰 강화, 이동제한, 임상검사 절차"),
    ]:
        print(f"[{label}] {query}")
        for c in retrieve_chunks(client, query):
            print(f"  distance={c['distance']:.4f} [{c['source_file']} {c['article_no'] or ''}] {c['title']}")
        print()
