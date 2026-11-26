"""
지역 키워드 처리
- 검색어에서 시·도 / 시·군·구 / 업종(예: 맛집)을 인식
- 같은 시·도의 다른 구·군 키워드 만들기
- 연관 키워드에서 '동네·명소 + 업종' 키워드 골라내기
"""

from __future__ import annotations

import re

# 시·도 → 시·군·구 (2026년 기준. 인천은 2026-07 개편 후 이름과 기존 이름을 함께 둔다)
REGIONS: dict[str, list[str]] = {
    "서울": ["종로구", "중구", "용산구", "성동구", "광진구", "동대문구", "중랑구", "성북구", "강북구", "도봉구",
           "노원구", "은평구", "서대문구", "마포구", "양천구", "강서구", "구로구", "금천구", "영등포구", "동작구",
           "관악구", "서초구", "강남구", "송파구", "강동구"],
    "부산": ["중구", "서구", "동구", "영도구", "부산진구", "동래구", "남구", "북구", "해운대구", "사하구",
           "금정구", "강서구", "연제구", "수영구", "사상구", "기장군"],
    "대구": ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"],
    "인천": ["제물포구", "영종구", "중구", "동구", "미추홀구", "연수구", "남동구", "부평구", "계양구", "서구",
           "검단구", "강화군", "옹진군"],
    "광주": ["동구", "서구", "남구", "북구", "광산구"],
    "대전": ["동구", "중구", "서구", "유성구", "대덕구"],
    "울산": ["중구", "남구", "동구", "북구", "울주군"],
    "세종": [],
    "경기": ["수원시", "성남시", "의정부시", "안양시", "부천시", "광명시", "평택시", "동두천시", "안산시", "고양시",
           "과천시", "구리시", "남양주시", "오산시", "시흥시", "군포시", "의왕시", "하남시", "용인시", "파주시",
           "이천시", "안성시", "김포시", "화성시", "광주시", "양주시", "포천시", "여주시", "연천군", "가평군", "양평군"],
    "강원": ["춘천시", "원주시", "강릉시", "동해시", "태백시", "속초시", "삼척시", "홍천군", "횡성군", "영월군",
           "평창군", "정선군", "철원군", "화천군", "양구군", "인제군", "고성군", "양양군"],
    "충북": ["청주시", "충주시", "제천시", "보은군", "옥천군", "영동군", "증평군", "진천군", "괴산군", "음성군", "단양군"],
    "충남": ["천안시", "공주시", "보령시", "아산시", "서산시", "논산시", "계룡시", "당진시", "금산군", "부여군",
           "서천군", "청양군", "홍성군", "예산군", "태안군"],
    "전북": ["전주시", "군산시", "익산시", "정읍시", "남원시", "김제시", "완주군", "진안군", "무주군", "장수군",
           "임실군", "순창군", "고창군", "부안군"],
    "전남": ["목포시", "여수시", "순천시", "나주시", "광양시", "담양군", "곡성군", "구례군", "고흥군", "보성군",
           "화순군", "장흥군", "강진군", "해남군", "영암군", "무안군", "함평군", "영광군", "장성군", "완도군",
           "진도군", "신안군"],
    "경북": ["포항시", "경주시", "김천시", "안동시", "구미시", "영주시", "영천시", "상주시", "문경시", "경산시",
           "의성군", "청송군", "영양군", "영덕군", "청도군", "고령군", "성주군", "칠곡군", "예천군", "봉화군",
           "울진군", "울릉군"],
    "경남": ["창원시", "진주시", "통영시", "사천시", "김해시", "밀양시", "거제시", "양산시", "의령군", "함안군",
           "창녕군", "고성군", "남해군", "하동군", "산청군", "함양군", "거창군", "합천군"],
    "제주": ["제주시", "서귀포시"],
}
METRO = {"서울", "부산", "대구", "인천", "광주", "대전", "울산"}

SIDO_ALIASES = {
    "서울": ["서울특별시", "서울시", "서울"], "부산": ["부산광역시", "부산시", "부산"],
    "대구": ["대구광역시", "대구시", "대구"], "인천": ["인천광역시", "인천시", "인천"],
    "광주": ["광주광역시", "광주"], "대전": ["대전광역시", "대전시", "대전"],
    "울산": ["울산광역시", "울산시", "울산"], "세종": ["세종특별자치시", "세종시", "세종"],
    "경기": ["경기도", "경기"], "강원": ["강원특별자치도", "강원도", "강원"],
    "충북": ["충청북도", "충북"], "충남": ["충청남도", "충남"],
    "전북": ["전북특별자치도", "전라북도", "전북"], "전남": ["전라남도", "전남"],
    "경북": ["경상북도", "경북"], "경남": ["경상남도", "경남"],
    "제주": ["제주특별자치도", "제주도"],
}

# 동네 이름이 아니라 '메뉴·상황' 수식어인 것들 (동네 후보에서 제외)
GENERIC = set("""
가성비 데이트 점심 저녁 아침 회식 혼밥 혼술 모임 단체 가족 아이랑 아기랑 부모님 룸 분위기 분위기좋은 신상 줄서는 숨은 현지인
유명한 맛있는 노포 핫플 인생 주차 주차가능 24시 새벽 배달 포장 상견례 돌잔치 생일 기념일 뷔페 한식 중식 일식 양식 분식
고기 삼겹살 소고기 한우 돼지갈비 갈비 오리 백숙 국밥 냉면 칼국수 해장국 곱창 막창 대창 족발 보쌈 찜닭 닭갈비 치킨 피자
파스타 초밥 스시 오마카세 횟집 회 해산물 조개구이 샤브샤브 브런치 빵집 베이커리 디저트 케이크 카페 술집 포차 이자카야
와인바 바 룸술집 한정식 쌈밥 보리밥 추어탕 아구찜 떡볶이 마라탕 쌀국수 돈까스 우동 라멘 짬뽕 짜장면 중국집 감자탕 순대
주변 내주변 근처 내근처 동네 우리동네 요즘 근교 전국 국내 서울근교 지역 시내 시외 현재위치 여기
""".split())


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _short(name: str) -> str:
    """'포항시' → '포항', '달성군' → '달성'. 구 이름(동구)은 그대로 (줄이면 '동'이 되어 버림)."""
    if name[-1] in "시군" and len(name) >= 3:
        return name[:-1]
    return name


def _gu_owners() -> dict[str, list[str]]:
    owners: dict[str, list[str]] = {}
    for sido, gus in REGIONS.items():
        for g in gus:
            owners.setdefault(g, []).append(sido)
    return owners


GU_OWNERS = _gu_owners()


def parse_region(query: str) -> dict | None:
    """'대구 동구 맛집' → {sido:'대구', gu:'동구', category:'맛집'}. 지역이 없으면 None."""
    q = _n(query)
    sido, rest = None, q
    for s, aliases in SIDO_ALIASES.items():
        for a in sorted(aliases, key=len, reverse=True):
            if q.startswith(a):
                sido, rest = s, q[len(a):]
                break
        if sido:
            break

    pool = REGIONS[sido] if sido else [g for g, o in GU_OWNERS.items() if len(o) == 1]  # 시·도 없으면 겹치지 않는 이름만
    gu = None
    for g in sorted(pool, key=len, reverse=True):
        for form in sorted({g, _short(g)}, key=len, reverse=True):
            if rest.startswith(form):
                gu, rest = g, rest[len(form):]
                break
        if gu:
            break
    if gu is None:
        # '부산 해운대 맛집', '강남 맛집'처럼 '구'를 뺀 이름이 단어로 따로 쓰인 경우
        toks = query.split()
        for i, t in enumerate(toks):
            cands = [g for g in pool if g.endswith("구") and len(g) >= 3 and g[:-1] == t]
            if cands:
                gu = cands[0]
                rest = "".join(toks[i + 1:]) if sido or i == 0 else "".join(toks[:i] + toks[i + 1:])
                break
    if gu and not sido:
        sido = GU_OWNERS[gu][0]
    if not sido:
        return None
    return {"sido": sido, "gu": gu, "category": rest}


def region_label(r: dict) -> str:
    return " ".join(x for x in [r["sido"], r["gu"]] if x)


def keyword_forms(sido: str, gu: str | None, cat: str) -> list[str]:
    """
    사람들이 실제로 검색하는 형태 후보들. 검색량을 조회해 가장 많은 형태를 대표로 쓴다.
    광역시 구 → 대구수성구맛집 / 수성구맛집 / 수성맛집, 도의 시·군 → 경주맛집 / 경주시맛집
    """
    if gu is None:
        return [f"{sido}{cat}"]
    forms = []
    if sido in METRO:
        forms.append(f"{sido}{gu}{cat}")
        if len(GU_OWNERS.get(gu, [])) == 1:           # 이름이 전국에 하나뿐일 때만 지역명 없이
            forms.append(f"{gu}{cat}")
            if gu.endswith("구") and len(gu) >= 3:
                forms.append(f"{gu[:-1]}{cat}")
        if gu.endswith("군"):
            forms.append(f"{_short(gu)}{cat}")
    else:
        forms += [f"{_short(gu)}{cat}", f"{gu}{cat}"]
    return list(dict.fromkeys(forms))


def keyword_for(sido: str, gu: str | None, cat: str) -> str:
    return keyword_forms(sido, gu, cat)[0]


def sibling_keywords(r: dict) -> list[tuple[str, list[str]]]:
    """같은 시·도의 다른 구·군 (이름, 키워드 형태들). 시·도만 입력했으면 그 시·도의 모든 구·군."""
    out = []
    for g in REGIONS.get(r["sido"], []):
        if g == r["gu"]:
            continue
        if r["sido"] == "인천" and g in ("중구", "동구"):  # 개편 후 이름과 중복
            continue
        out.append((f"{r['sido']} {g}", keyword_forms(r["sido"], g, r["category"])))
    return out


def _other_region_names(own_sido: str) -> list[str]:
    names = set()
    for s, aliases in SIDO_ALIASES.items():
        if s != own_sido:
            names.update(a for a in aliases if len(a) >= 2)
    for g, owners in GU_OWNERS.items():
        if own_sido not in owners:
            names.add(g)
            if _short(g) != g and len(_short(g)) >= 2:
                names.add(_short(g))
            if g.endswith("구") and len(g) >= 4:      # 해운대구 → 해운대, 영등포구 → 영등포
                names.add(g[:-1])
    return sorted(names, key=len, reverse=True)


def extract_neighborhoods(r: dict, keywords: list[str]) -> list[tuple[str, str]]:
    """
    연관 키워드 중 '동네·명소 + 업종' 형태를 골라 (동네 이름, 키워드)로 돌려준다.
    예) 대구 동구 맛집 → ('동촌', '동촌맛집'), ('율하', '대구율하맛집')
    """
    cat = _n(r["category"])
    own = [a for a in SIDO_ALIASES[r["sido"]]] + ([r["gu"], _short(r["gu"])] if r["gu"] else [])
    own = sorted(set(own), key=len, reverse=True)
    siblings = {g for g in REGIONS.get(r["sido"], [])} | {_short(g) for g in REGIONS.get(r["sido"], [])}
    others = _other_region_names(r["sido"])
    seen, out = set(), []
    for kw in keywords:
        k = _n(kw)
        if cat:
            if not k.endswith(cat) or len(k) == len(cat):
                continue
            prefix = k[: -len(cat)]
        else:
            prefix = k
            if not re.search(r"(동|읍|면|리|역|가)$", prefix):
                continue
        # 앞에 붙은 내 지역 이름(대구, 동구)은 떼어낸다
        changed = True
        while changed:
            changed = False
            for o in own:
                if prefix.startswith(o) and len(prefix) > len(o):
                    prefix, changed = prefix[len(o):], True
        if not prefix or prefix in own or prefix in siblings or len(prefix) < 2:
            continue
        # 메뉴·상황 수식어(고기, 가성비 …)이거나 그것으로 끝나면 동네 키워드가 아님
        if prefix in GENERIC or any(prefix.endswith(g) or prefix.startswith(g) for g in GENERIC if len(g) >= 2):
            continue
        # 다른 지역 이름으로 시작하면 제외 (단 '진천동'처럼 지역명+동/리/역은 동네일 수 있어 둔다)
        if any(prefix == o or (prefix.startswith(o) and (len(o) >= 3 or not prefix[len(o):].startswith(("동", "리", "역", "로"))))
               for o in others):
            continue
        if prefix in seen:
            continue
        seen.add(prefix)
        out.append((prefix, kw))
    return out
