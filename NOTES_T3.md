# T3 작업 시 고려사항 (T1에서 넘어온 메모)

## 동일 좌표 중복 마커 처리 필요

`data/farms_geocoded.csv` 기준(2,285행), **동일 좌표 그룹이 166개(648행)** 존재한다.
도로명주소가 같은 농장은 지오코딩 결과도 같은 좌표로 나오는 게 당연한 결과이지만,
지도에 그대로 찍으면 점이 완전히 겹쳐서 하나로만 보인다.

- 최대 그룹 크기: 57건 (한 좌표에 57개 농장이 겹침)
- **처리 없이 지도만 그리면 농장 수가 실제보다 훨씬 적어 보이는 문제 발생**

**T3에서 지도 그릴 때 다음 중 하나로 처리할 것:**
- 마커를 좌표 기준으로 살짝 흩뿌리기 (jitter)
- 같은 좌표를 클러스터로 묶고 개수를 라벨로 표시

확인 방법 (재현):
```python
import pandas as pd
geo = pd.read_csv("data/farms_geocoded.csv", encoding="utf-8-sig")
g = geo.groupby(["위도", "경도"]).size()
dup_groups = g[g > 1]
# len(dup_groups) == 166, dup_groups.sum() == 648, dup_groups.max() == 57
```
