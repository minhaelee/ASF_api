"""ASF T3 — 지도: 전국 시군 색칠(등급) + 농장 점(T1, 표시 전용) + 발생 지점 10km 원.

NOTES_T3.md(T1이 남긴 메모): farms_geocoded.csv에 동일 좌표 166그룹(648행, 최대 57건)이
있어 그대로 찍으면 점이 겹쳐 농장 수가 실제보다 적어 보인다. 메모가 제시한 두 선택지
(클러스터 / jitter) 중 jitter는 실제로 비교해보니 점이 흩어져 어수선해 제외하고,
클러스터 방식으로 확정했다 — 멀리서는 버블 크기/색으로 밀집도를 보고, 확대하면 개별
점이 펼쳐진다. 버블 색은 기본 초록/노랑/주황-빨강 대신 파란 계열로 바꿔, 시군 등급의
주황/빨강과 헷갈리지 않게 한다.

농장 데이터 없는 시군(발생 이력은 있지만 farms_geocoded.csv에 없는 시군)은 색칠만 되고
점이 없다 — 폴리곤 중심에 "농장 데이터 미확보" 라벨을 얹어 빈 지도가 아니라 "데이터가
없다"는 사실 자체를 보여준다.

10km 원은 표시 전용이다: 지금 등급(grade_stub)은 반경 계산을 하지 않으므로, 원이 있다고
해서 그 반경이 등급에 반영됐다는 뜻이 아니다 — 지도 위 안내 문구로 이 점을 명시한다.
"""

import json

import pandas as pd
import folium
from folium.plugins import MarkerCluster

from app.config import BOUNDARY_PATH, FARMS_PATH, MASTER_GEOCODED_PATH
from app.geo_normalize import resolve_address
from app.grade_stub import STUB_NOTE

GRADE_COLOR = {
    "평시": "#dcdcdc",
    "주의": "#f4b400",
    "심각": "#d33f3f",
}

FARM_DOT_COLOR = "#2b6cb0"
CIRCLE_RADIUS_M = 10_000

# 클러스터 버블 색을 등급 색(회색/주황/빨강)과 겹치지 않는 파란 계열로 고정한다.
# 기본 MarkerCluster.Default.css는 초록/노랑/주황-빨강 그라데이션이라, 시군 등급의
# 주황/빨강과 같은 지도 위에서 "농장이 몰린 곳=위험도 높은 곳"으로 오독될 수 있다.
_CLUSTER_ICON_JS = """
function(cluster) {
    var count = cluster.getChildCount();
    var size = count < 10 ? 30 : count < 100 ? 38 : 46;
    var shade = count < 10 ? '#7fa8d9' : count < 100 ? '#2b6cb0' : '#173d63';
    return new L.DivIcon({
        html: '<div style="background:' + shade + ';border-radius:50%;width:' + size + 'px;height:' + size + 'px;' +
              'display:flex;align-items:center;justify-content:center;color:white;font-weight:bold;' +
              'font-size:12px;border:2px solid white;box-shadow:0 0 3px rgba(0,0,0,0.4);">' + count + '</div>',
        className: 'asf-farm-cluster',
        iconSize: new L.Point(size, size)
    });
}
"""


def _rough_centroid(geometry: dict) -> tuple[float, float]:
    """폴리곤 좌표 평균으로 대략적인 중심을 구한다(라벨 배치용, 면적 가중 없음)."""
    coords = []

    def _walk(node):
        if isinstance(node, (float, int)):
            return
        if len(node) == 2 and isinstance(node[0], (float, int)):
            coords.append(node)
            return
        for child in node:
            _walk(child)

    _walk(geometry["coordinates"])
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def _farm_coverage_codes() -> set[str]:
    farms = pd.read_csv(FARMS_PATH, encoding="utf-8-sig")
    codes = set()
    for addr in farms["주소"]:
        code = resolve_address(str(addr))
        if code is not None:
            codes.add(code)
    return codes


def build_map(state: dict) -> folium.Map:
    grades: dict[str, dict] = state["grades"]
    extracted_cases: list[dict] = state["extracted_cases"]
    as_of = state["as_of"]

    history_codes = {c["sgg_code"] for c in extracted_cases if c["sgg_code"] is not None}
    farm_codes = _farm_coverage_codes()
    no_farm_data_codes = history_codes - farm_codes

    m = folium.Map(location=[36.4, 127.9], zoom_start=7, tiles="cartodbpositron")

    with open(BOUNDARY_PATH, encoding="utf-8") as f:
        boundary = json.load(f)

    def style_function(feature):
        code = feature["properties"]["code"]
        g = grades.get(code, {}).get("grade", "평시")
        return {
            "fillColor": GRADE_COLOR[g],
            "color": "#888888",
            "weight": 0.5,
            "fillOpacity": 0.75,
        }

    def tooltip_fields(feature):
        code = feature["properties"]["code"]
        g = grades.get(code, {})
        feature["properties"]["_grade"] = g.get("grade", "평시")
        feature["properties"]["_days_since_last"] = g.get("days_since_last")
        return feature

    boundary["features"] = [tooltip_fields(f) for f in boundary["features"]]

    folium.GeoJson(
        boundary,
        name="시군 등급",
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(
            fields=["name", "_grade", "_days_since_last"],
            aliases=["시군", "등급(임시 함수)", "최근 발생 경과일"],
        ),
    ).add_to(m)

    for code in no_farm_data_codes:
        feature = next(f for f in boundary["features"] if f["properties"]["code"] == code)
        lat, lon = _rough_centroid(feature["geometry"])
        folium.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(html='<div style="font-size:10px;color:#333;background:white;'
                                      'padding:1px 3px;border:1px solid #999;border-radius:3px;'
                                      'white-space:nowrap;">농장 데이터 미확보</div>'),
        ).add_to(m)

    farms = pd.read_csv(FARMS_PATH, encoding="utf-8-sig").dropna(subset=["위도", "경도"])

    cluster = MarkerCluster(
        name="농장(T1, 표시 전용)",
        icon_create_function=_CLUSTER_ICON_JS,
    ).add_to(m)
    for _, row in farms.iterrows():
        label = row["농장명"] if pd.notna(row["농장명"]) else "(농장명 미상)"
        folium.CircleMarker(
            location=[row["위도"], row["경도"]],
            radius=3,
            color=FARM_DOT_COLOR,
            fill=True,
            fill_opacity=0.7,
            tooltip=f"{row['시군']} {label}",
        ).add_to(cluster)

    outbreaks = pd.read_csv(MASTER_GEOCODED_PATH, encoding="utf-8-sig")
    circle_layer = folium.FeatureGroup(name="발생 지점 10km 원(표시 전용)")
    for _, row in outbreaks.iterrows():
        folium.Circle(
            location=[row["위도"], row["경도"]],
            radius=CIRCLE_RADIUS_M,
            color="#d33f3f",
            weight=1,
            fill=False,
            tooltip=f"{row['case_date']} {row['address']}",
        ).add_to(circle_layer)
    circle_layer.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    legend_html = f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999;
                background: white; padding: 10px 14px; border: 1px solid #999;
                border-radius: 4px; font-size: 12px; max-width: 320px;">
      <b>기준일(as_of): {as_of}</b><br>
      <span style="color:{GRADE_COLOR['평시']}">■</span> 평시
      &nbsp;<span style="color:{GRADE_COLOR['주의']}">■</span> 주의
      &nbsp;<span style="color:{GRADE_COLOR['심각']}">■</span> 심각<br>
      <hr style="margin:4px 0;">
      <b>임시 등급 함수:</b> {STUB_NOTE}<br>
      <b>10km 원:</b> 발생 지점 표시 전용 — 현재 등급 계산(자기 시군 최근성)에는
      반경이 반영되지 않는다.<br>
      <b>농장 점:</b> 발생 이력 {len(history_codes)}개 시군 중 {len(history_codes & farm_codes)}개 시군만 확보
      (나머지 {len(no_farm_data_codes)}개는 위 라벨로 표시), 지자체 공개 여부에 따른 선택 편향 있음.
      등급/검증 계산에는 쓰이지 않는다.<br>
      <b>파란 버블(숫자 포함):</b> 시군 등급과 무관 — 그 안에 뭉쳐 있는 농장 개수만
      나타낸다(진할수록 개수 많음). 확대하면 개별 농장 점으로 펼쳐진다.
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m
