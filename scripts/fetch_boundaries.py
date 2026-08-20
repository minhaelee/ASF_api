"""ASF T3 — 전국 시군구 경계 GeoJSON을 받아온다 (지도 색칠용, 저장소에 없던 파일).

출처   southkorea/southkorea-maps, kostat/2018/json/skorea-municipalities-2018-geo.json
       (통계청 SGIS, 2018-12-24 수집, 공공누리 제1유형 — 출처 표시 조건으로 상업적 이용 가능)
비고   시군구 250개, 속성은 name/name_eng/base_year/code(SGIS 5자리) — 시도 속성 없음.
       code는 법정동코드와 다른 체계라 app/geo_normalize.py가 별도 시도코드표로 조인한다.

실행   python scripts/fetch_boundaries.py
출력   data/boundaries/skorea-municipalities-2018-geo.json
"""

import sys

import requests

sys.stdout.reconfigure(encoding="utf-8")

URL = (
    "https://raw.githubusercontent.com/southkorea/southkorea-maps/master/"
    "kostat/2018/json/skorea-municipalities-2018-geo.json"
)
OUT_PATH = "data/boundaries/skorea-municipalities-2018-geo.json"
LICENSE_NOTE = (
    "출처: 통계청 통계지리정보서비스(SGIS), 2018-12-24 수집, 공공누리 제1유형 "
    "(southkorea/southkorea-maps 저장소 경유)"
)


def main():
    import os

    os.makedirs("data/boundaries", exist_ok=True)

    print(f"다운로드: {URL}")
    r = requests.get(URL, timeout=60)
    r.raise_for_status()

    with open(OUT_PATH, "wb") as f:
        f.write(r.content)

    import json

    with open(OUT_PATH, encoding="utf-8") as f:
        gj = json.load(f)

    print(f"저장 완료: {OUT_PATH} ({len(r.content) / 1024 / 1024:.1f} MB)")
    print(f"피처 수: {len(gj['features'])}개 (전국 시군구, 기대값 ~250)")
    print(LICENSE_NOTE)


if __name__ == "__main__":
    main()
