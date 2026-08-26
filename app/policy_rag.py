"""ASF v3 — 정책 매뉴얼 RAG(작업지시서 v1~v4 "하지 않을 것"에 있던 항목을 2026-08-26
피드백으로 뒤집어 진행). scripts/ingest_policy_pdf.py가 채운 policy_chunks(방역실시요령
33 + SOP 75)를 코사인 거리로 검색해 답을 만든다.

원칙(app/briefing.py와 동일): LLM은 검색된 조문/섹션을 요약만 하고, 검색으로 못 찾은
내용은 절대 지어내지 않는다. disclaimer는 서버가 항상 별도 필드로 붙인다 — LLM 문장이
빠뜨려도 API 응답에는 항상 남는다(기존 GRADE_METHOD_NOTE 패턴과 동일).
"""

import sys

import psycopg2
from openai import OpenAI
from pgvector.psycopg2 import register_vector

from app.config import (
    OPENAI_API_KEY,
    OPENAI_BRIEFING_MODEL,
    OPENAI_EMBEDDING_MODEL,
    PGDATABASE,
    PGHOST,
    PGPASSWORD,
    PGPORT,
    PGUSER,
    POLICY_DISCLAIMER,
)

POLICY_TOP_K = 5
# 코사인 거리(0=완전 일치, 2=완전 반대) 컷오프 — 이보다 멀면 LLM도 안 부르고 바로
# "관련 없음" 처리한다. 실측(2026-08-26)해보니 처음 가정(0.3대/0.5대로 뚜렷이 갈림)은
# 틀렸다 — "관리지역 반경"(정답 있음) top1=0.59, "소 살처분 보상"(돼지 문서라 답 없어야
# 함) top1=0.62, "조류인플루엔자 기준"(역시 답 없어야 함) top1=0.68로 겹친다. 같은
# 방역·살처분 어휘를 공유하는 주제 인접 질문은 임베딩 거리만으로 못 거른다는 뜻 —
# 진짜 엉뚱한 질문("저녁 메뉴 추천")만 0.80으로 뚜렷이 떨어진다. 그래서 이 컷오프는
# "명백히 무관한 질문만 걸러 LLM 호출 자체를 아끼는 용도"로 넉넉하게 잡고, "내용은
# 검색됐지만 실제로 질문에 답하진 못하는" 판단은 프롬프트의 LLM 판단(주어진 내용만
# 근거로, 없으면 모른다고 답하라)에 맡긴다 — 이게 진짜 안전장치다.
NO_MATCH_DISTANCE_THRESHOLD = 0.75

NO_MATCH_ANSWER = "제공된 방역실시요령·긴급행동지침에서 관련 내용을 찾을 수 없습니다."


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


def answer_policy_question(question: str) -> dict:
    """반환: {"question", "answer", "sources": [{"source_file","article_no","title"}],
              "disclaimer": POLICY_DISCLAIMER, "matched": bool}"""
    if not OPENAI_API_KEY:
        sys.exit("OPENAI_API_KEY 환경변수가 없습니다. .env를 확인하세요.")

    client = OpenAI(api_key=OPENAI_API_KEY)
    chunks = retrieve_chunks(client, question)

    if not chunks or chunks[0]["distance"] > NO_MATCH_DISTANCE_THRESHOLD:
        return {
            "question": question,
            "answer": NO_MATCH_ANSWER,
            "sources": [],
            "disclaimer": POLICY_DISCLAIMER,
            "matched": False,
        }

    context = "\n\n---\n\n".join(
        f"[출처: {c['source_file']}"
        f"{' ' + c['article_no'] if c['article_no'] else ''} {c['title']}]\n{c['content']}"
        for c in chunks
    )

    instructions = (
        "너는 ASF 방역실시요령·긴급행동지침(SOP) 검색 결과를 요약해 방역 담당 공무원에게 "
        "답하는 도우미다. 아래 제공된 조문/섹션 내용만 근거로 답하라 — 여기 없는 내용을 "
        "추정하거나 지어내지 마라. 방역실시요령은 법령(고시)이고 SOP는 운영 지침이니, "
        "답변에서 어느 문서에 근거한 내용인지 성격을 구분해 언급하라(예: '방역실시요령 "
        "제18조에 따르면...', 'SOP상 살처분 방법으로는...'). 근거가 된 조 번호나 섹션명을 "
        "반드시 언급하라. 제공된 내용으로 답할 수 없는 질문이면 "
        f'"{NO_MATCH_ANSWER}"라고만 답하라. 마크다운 문법 없이 순수 텍스트로 작성하라.'
    )
    input_text = f"질문: {question}\n\n검색된 조문/섹션:\n{context}"

    resp = client.responses.create(
        model=OPENAI_BRIEFING_MODEL,
        instructions=instructions,
        input=input_text,
    )

    sources = [
        {"source_file": c["source_file"], "article_no": c["article_no"], "title": c["title"]}
        for c in chunks
        if c["distance"] <= NO_MATCH_DISTANCE_THRESHOLD
    ]

    return {
        "question": question,
        "answer": resp.output_text,
        "sources": sources,
        "disclaimer": POLICY_DISCLAIMER,
        "matched": True,
    }


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for q in [
        "관리지역의 반경은 몇 미터인가요?",
        "일시 이동중지(Standstill) 명령은 최대 몇 시간인가요?",
        "살처분 참여자 심리지원은 어떻게 하나요?",
        "소 살처분 보상 절차는 어떻게 되나요?",
    ]:
        result = answer_policy_question(q)
        print(f"Q: {q}")
        print(f"matched={result['matched']}")
        print(f"A: {result['answer']}")
        print(f"sources: {result['sources']}")
        print()
