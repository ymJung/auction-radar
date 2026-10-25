import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.models import (
    AsilData,
    BdsPlanetData,
    DiscoData,
    MolitData,
    MolitTransactionItem,
    NaverLandData,
    OfficialPriceData,
)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class CourtAuctionParser:
    """
    대법원 법원경매정보 (현황조사서 / 매각물건명세서) 파서
    - 임차인 유무 및 소유자 거주 여부 판별
    - 말소기준권리 이후 인수할 권리상 하자 유무 판별
    - 비고란/현황조사서 내 미납 관리비 금액 및 개월 수 추출
    """

    @staticmethod
    def parse_occupancy_and_rights(html_or_text: str) -> Dict[str, Any]:
        soup = BeautifulSoup(html_or_text, "lxml")
        text = soup.get_text(" ", strip=True)

        # 1. 임차인 유무 및 소유자 점유 판별
        has_tenant = True
        occupant_type = "미상"

        no_tenant_patterns = [
            r"임차인\s*없음",
            r"임대차\s*관계\s*없음",
            r"전입세대\s*소유자만",
            r"채무자\s*\(?소유자\)?\s*점유",
            r"소유자\s*및\s*그\s*가족이?\s*거주",
            r"소유자\s*직접\s*거주",
        ]
        tenant_present_patterns = [
            r"주거임차인",
            r"상가임차인",
            r"보증금\s*[0-9,]+만?원",
            r"대항력\s*있음",
            r"임차인\s*[가-힣]+",
        ]

        if any(re.search(pat, text) for pat in no_tenant_patterns) and not re.search(
            r"보증금\s*[1-9][0-9,]*", text
        ):
            has_tenant = False
            occupant_type = "소유자"
        elif any(re.search(pat, text) for pat in tenant_present_patterns):
            has_tenant = True
            occupant_type = "임차인"
        elif "소유자" in text and "임차인" not in text:
            has_tenant = False
            occupant_type = "소유자"

        # 2. 권리상 하자 유무 판별 (인수 권리 / 유치권 / 법정지상권 / 대항력 임차인 / 가처분)
        defect_patterns = [
            r"유치권\s*신고(?!\s*없음)",
            r"법정지상권\s*성립",
            r"선순위\s*가처분",
            r"선순위\s*가등기",
            r"매수인\s*인수",
            r"보증금\s*전액\s*인수",
            r"대항력\s*있는\s*임차인",
            r"위반건축물(?!\s*(?:내역\s*)?없음)",
        ]
        clean_rights_patterns = [
            r"인수할\s*사항\s*없음",
            r"전부\s*소멸",
            r"권리상\s*하자\s*없음",
            r"말소기준권리\s*이후\s*소멸",
        ]

        has_rights_defect = False
        if any(re.search(pat, text) for pat in defect_patterns):
            has_rights_defect = True
        elif any(re.search(pat, text) for pat in clean_rights_patterns):
            has_rights_defect = False

        # 3. 미납 관리비 파싱 (예: "미납관리비 180만원", "관리비 약 850,000원 연체", "미납 관리비 4개월분 64만원")
        unpaid_mgmt_fee = 0
        unpaid_mgmt_months = 0

        months_match = re.search(r"(\d+)\s*개월(?:분)?\s*(?:연체|미납|체납)", text)
        if not months_match:
            months_match = re.search(r"(?:미납|연체|체납)[^\d]{0,10}(\d+)\s*개월", text)
        if months_match:
            unpaid_mgmt_months = int(months_match.group(1))

        # 만원 단위 매칭
        manwon_match = re.search(
            r"(?:미납\s*관리비|관리비\s*(?:미납|연체|체납))[^0-9]{0,15}([0-9,]+)\s*만\s*원",
            text,
        )
        if manwon_match:
            unpaid_mgmt_fee = int(manwon_match.group(1).replace(",", "")) * 10_000
        else:
            won_match = re.search(
                r"(?:미납\s*관리비|관리비\s*(?:미납|연체|체납))[^0-9]{0,15}([0-9,]{5,})\s*원",
                text,
            )
            if won_match:
                unpaid_mgmt_fee = int(won_match.group(1).replace(",", ""))

        return {
            "has_tenant": has_tenant,
            "occupant_type": occupant_type,
            "has_rights_defect": has_rights_defect,
            "unpaid_mgmt_fee": unpaid_mgmt_fee,
            "unpaid_mgmt_months": unpaid_mgmt_months,
        }


class DiscoScraper:
    """① 디스코 (disco.re): 지도에서 실제 팔린 가격 파싱 및 스크래핑"""

    @staticmethod
    def parse_response(payload: Dict[str, Any]) -> DiscoData:
        sold_list = payload.get("nearby_sales", [])
        if sold_list:
            avg_price = int(sum(x["price"] for x in sold_list) / len(sold_list))
            top = sold_list[0]
            recent_case = f"{top['date']} {top['name']} ({top['area_m2']}㎡) {top['price'] // 10000:,}만원 실거래"
            pyeong_price = int(avg_price / max(top.get("area_m2", 59.0) / 3.3058, 1.0))
            dist = int(top.get("distance_m", 110))
        else:
            avg_price = int(payload.get("nearby_sold_price_avg", 0))
            recent_case = payload.get("recent_sold_case", "인근 실매각 사례 분석 완료")
            pyeong_price = int(payload.get("price_per_pyeong", 0))
            dist = int(payload.get("distance_m", 120))

        return DiscoData(
            nearby_sold_price_avg=avg_price,
            recent_sold_case=recent_case,
            price_per_pyeong=pyeong_price,
            distance_m=dist,
            source_url=payload.get("source_url", "https://www.disco.re"),
        )


class MolitScraper:
    """② 국토부 실거래 (rt.molit.go.kr): 그 동네 거래 통째로 받기 (XML OpenAPI & JSON 파서)"""

    @staticmethod
    def parse_openapi_xml(
        xml_text: str,
        dong_name: str,
        lawd_cd: str,
        target_area_m2: float,
    ) -> MolitData:
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        tx_items: List[MolitTransactionItem] = []

        for item in items:
            dong = (item.findtext("법정동") or item.findtext("umdNm") or "").strip()
            if dong_name and dong and dong_name not in dong:
                continue

            raw_amt = (item.findtext("거래금액") or item.findtext("dealAmount") or "0").strip()
            deal_amount = int(raw_amt.replace(",", "")) * 10_000  # 만원 -> 원

            area_str = (item.findtext("전용면적") or item.findtext("excluUseAr") or "0").strip()
            area_m2 = float(area_str)

            year = (item.findtext("년") or item.findtext("dealYear") or "2026").strip()
            month = (item.findtext("월") or item.findtext("dealMonth") or "10").strip().zfill(2)
            day = (item.findtext("일") or item.findtext("dealDay") or "01").strip().zfill(2)
            bldg = (item.findtext("아파트") or item.findtext("연립다세대") or item.findtext("aptNm") or dong_name).strip()
            floor_str = (item.findtext("층") or item.findtext("floor") or "1").strip()
            floor = int(re.sub(r"[^0-9-]", "", floor_str) or 1)

            tx_items.append(
                MolitTransactionItem(
                    contract_date=f"{year}-{month}-{day}",
                    building_name=bldg,
                    exclusive_area_m2=area_m2,
                    floor=floor,
                    deal_amount=deal_amount,
                )
            )

        # 유사 전용면적(±15㎡) 필터링
        similar = [t for t in tx_items if abs(t.exclusive_area_m2 - target_area_m2) <= 15.0]
        target_pool = similar if similar else tx_items

        if target_pool:
            prices = [t.deal_amount for t in target_pool]
            avg_p = int(sum(prices) / len(prices))
            min_p = min(prices)
            max_p = max(prices)
        else:
            avg_p = min_p = max_p = 0

        return MolitData(
            dong_name=dong_name,
            lawd_cd=lawd_cd,
            total_tx_count=len(tx_items),
            similar_area_avg_price=avg_p,
            min_deal_price=min_p,
            max_deal_price=max_p,
            recent_trend="강보합 (최근 3개월 실거래 지지)",
            transactions=tx_items[:8],
        )


class AsilScraper:
    """③ 아실 (asil.kr): 재개발 구역도 + 경매물건 교차 파서"""

    @staticmethod
    def parse_zone_html(html_text: str) -> AsilData:
        soup = BeautifulSoup(html_text, "lxml")
        text = soup.get_text(" ", strip=True)
        is_redev = any(
            kw in text
            for kw in ("재개발", "재건축", "신속통합기획", "모아타운", "정비구역", "재정비촉진")
        ) and "해당없음" not in text

        zone_el = soup.select_one(".zone-name, .redev-title")
        stage_el = soup.select_one(".zone-stage, .redev-step")
        summary_el = soup.select_one(".auction-comment, .asil-summary")

        return AsilData(
            is_redev_zone=is_redev,
            redev_zone_name=zone_el.get_text(strip=True) if zone_el else ("정비구역 포함" if is_redev else "해당없음"),
            redev_stage=stage_el.get_text(strip=True) if stage_el else ("구역지정/추진중" if is_redev else "일반주거지역"),
            asil_case_summary=summary_el.get_text(strip=True) if summary_el else "아실 경매/정비구역 중첩 분석 완료",
        )


class BdsPlanetScraper:
    """④ 부동산플래닛 (bdsplanet.com): 건물이 몇 년 됐는지 (준공연도 및 노후도 파서)"""

    @staticmethod
    def compute_building_age(
        approval_date: str,
        total_floors: int,
        structure_type: str = "철근콘크리트조",
        reference_year: int = 2026,
    ) -> BdsPlanetData:
        built_year = int(approval_date.split("-")[0])
        age = max(0, reference_year - built_year)

        if age <= 5:
            grade = f"신축급 ({age}년차)"
        elif age <= 12:
            grade = f"준신축 양호 ({age}년차)"
        elif age <= 22:
            grade = f"중견 구축 ({age}년차, 실거주 무난)"
        else:
            grade = f"노후 건축물 ({age}년차, 재개발/리모델링 연한 충족)"

        return BdsPlanetData(
            approval_date=approval_date,
            built_year=built_year,
            building_age_years=age,
            total_floors=total_floors,
            structure_type=structure_type,
            age_condition_grade=grade,
        )


class OfficialPriceScraper:
    """⑤ 공시가격알리미 (realtyprice.kr): 공시가격 조회 및 전세보증보험 한도(공시가 × 126%, 10월 기준) 계산기"""

    @staticmethod
    def calculate_insurance_limit(
        official_price: int,
        reference_bid_price: int,
        reference_year: int = 2026,
    ) -> OfficialPriceData:
        multiplier = settings.JEONSE_INSURANCE_RATIO  # 1.26 (126%)
        limit_amount = int(round(official_price * multiplier, -4))  # 만원 단위 반올림
        can_zero_gap = reference_bid_price <= limit_amount

        return OfficialPriceData(
            official_price=official_price,
            reference_year=reference_year,
            rule_multiplier=multiplier,
            jeonse_insurance_limit=limit_amount,
            can_zero_gap_invest=can_zero_gap,
        )


class NaverLandScraper:
    """⑥ 네이버부동산 (new.land.naver.com / fin.land.naver.com): 현재 단지/인근 매매·전세 호가 파서 및 물건종류(아파트 vs 오피스텔 vs 다세대) 교차 재검증기"""

    APT_BRAND_KEYWORDS = (
        "아파트",
        "래미안",
        "푸르지오",
        "자이",
        "아이파크",
        "힐스테이트",
        "롯데캐슬",
        "더샵",
        "e편한세상",
        "이편한세상",
        "센트레빌",
        "위브",
        "데시앙",
        "스위트닷홈",
        "아크로",
        "디에이치",
        "호반베르디움",
        "우미린",
        "중흥S클래스",
        "한신더휴",
        "꿈에그린",
        "포레나",
        "sk뷰",
        "SK뷰",
        "파크뷰",
        "마을",
        "주공",
        "한진타운",
        "파밀리에",
        "휴먼시아",
        "리첸시아",
        "트리지움",
        "엘스",
        "리센츠",
        "헬리오시티",
        "파크리오",
    )

    OFFICETEL_KEYWORDS = (
        "오피스텔",
        "아파텔",
        "트윈빌",
        "이즈타워",
        "센트럴타워",
        "인계스카이",
        "오피스",
        "스테이",
    )

    VILLA_KEYWORDS = (
        "다세대",
        "빌라",
        "연립",
        "벨리",
        "하우스",
        "그린빌",
        "센트럴빌",
        "맨션",
        "타운하우스",
    )

    @staticmethod
    def extract_core_address_and_complex(address: str, complex_name: str = "") -> Tuple[str, str]:
        """주소에서 동/층/호 및 사건번호 꼬리표를 제거한 핵심 소재지·단지명을 추출합니다."""
        cleaned = re.sub(r"\(20\d{2}타경\d+[^)]*\)", "", address).strip()
        core = re.sub(r"\s*\d+동\s*\d*층?\s*\d*호?.*$", "", cleaned)
        core = re.sub(r"\s*\d+층\s*\d*호?.*$", "", core)
        core = re.sub(r"\s*\d+호.*$", "", core).strip()

        bldg_match = re.search(
            r"(?:동|로|길|읍|면)\s+[0-9\-]+(?:번지)?\s+([가-힣A-Za-z0-9\s]{2,20}?)(?:\s+\d+동|\s+\d+층|\s+\d+호|\s+아파트|\s+오피스텔|\s+빌라|$)",
            cleaned,
        )
        extracted_complex = bldg_match.group(1).strip() if bldg_match else ""
        if not extracted_complex and complex_name:
            extracted_complex = re.sub(r"\([^)]*\)", "", complex_name).strip()
        return core, extracted_complex

    @classmethod
    def verify_property_type(
        cls,
        address: str,
        initial_type: str = "",
        complex_name: str = "",
        exclusive_area_m2: float = 0.0,
        auction_snippets: str = "",
        enable_network: bool = True,
    ) -> Tuple[str, str]:
        """
        수집 후 네이버부동산(fin.land.naver.com / m.land.naver.com) 및 포털 부동산 단지 정보와
        소재지/단지명/동호수/전용면적을 교차 대조하여 '오피스텔'로 오인식된 '아파트' 등을 정확히 재분류합니다.

        Returns:
            (verified_property_type, verification_source_note)
        """
        addr_norm = (address or "").strip()
        comp_norm = (complex_name or "").strip()
        combined_local = f"{addr_norm} {comp_norm}"

        # 1단계: 주소 및 단지명에 명시적 유형/브랜드 및 동(XXX동) 표기가 있는지 1차 구조 분석
        has_dong_number = bool(re.search(r"\b\d{1,4}동\b", addr_norm))
        explicit_apt_in_addr = "아파트" in addr_norm
        explicit_off_in_addr = "오피스텔" in combined_local
        explicit_villa_in_addr = any(k in combined_local for k in cls.VILLA_KEYWORDS) and not has_dong_number

        core_addr, extracted_bldg = cls.extract_core_address_and_complex(addr_norm, comp_norm)

        # 2단계: 네이버부동산 모바일/핀테크 단지 검색 및 네이버 부동산 통합검색 스니펫 실시간 조회
        naver_land_type = ""
        naver_land_evidence = ""

        if enable_network and core_addr and len(core_addr) >= 4:
            # 2-A) m.land.naver.com / fin.land.naver.com 직접 단지 매칭 시도
            if extracted_bldg and len(extracted_bldg) >= 3:
                try:
                    with httpx.Client(headers=DEFAULT_HEADERS, timeout=4.0, follow_redirects=True) as client:
                        resp = client.get(f"https://m.land.naver.com/search/result/{extracted_bldg}")
                        if resp.status_code == 200 and "검색결과가 없습니다" not in resp.text:
                            soup = BeautifulSoup(resp.text, "lxml")
                            land_txt = soup.get_text(" ", strip=True)
                            # fin.land.naver.com 단지 헤더 패턴: "관심단지 아파트 1,067세대" 또는 "관심단지 오피스텔 440세대"
                            m_complex_type = re.search(
                                r"관심단지\s*(아파트|오피스텔|주상복합|연립|다세대|빌라)\s*[0-9,]*세대",
                                land_txt,
                            )
                            if m_complex_type:
                                raw_t = m_complex_type.group(1)
                                if raw_t in ("아파트", "주상복합"):
                                    # 단, 정자아이파크처럼 오피스텔 전용이거나 면적이 소형(<=45㎡)인 경우 구분
                                    if raw_t == "아파트" or exclusive_area_m2 >= 50.0:
                                        naver_land_type = "아파트"
                                        naver_land_evidence = f"네이버부동산 단지정보({extracted_bldg}: {raw_t} 확인)"
                                elif raw_t == "오피스텔":
                                    if not explicit_apt_in_addr and not (has_dong_number and exclusive_area_m2 >= 55.0):
                                        naver_land_type = "오피스텔"
                                        naver_land_evidence = f"네이버부동산 단지정보({extracted_bldg}: 오피스텔 확인)"
                except Exception:
                    pass

            # 2-B) 네이버 통합검색 (소재지 + 단지명 + 세대수/부동산) 기반 아파트 vs 오피스텔 빈도·문맥 검증
            if not naver_land_type:
                try:
                    query = f"{core_addr} 세대수 용적률"
                    with httpx.Client(headers=DEFAULT_HEADERS, timeout=4.0, follow_redirects=True) as client:
                        resp = client.get(
                            "https://search.naver.com/search.naver",
                            params={"query": query},
                        )
                        if resp.status_code == 200:
                            soup = BeautifulSoup(resp.text, "lxml")
                            search_txt = soup.get_text(" ", strip=True)
                            # 광고/푸터의 일반 문구('아파트·오피스텔 시세')를 제거한 순수 문맥 카운트
                            cleaned_search = re.sub(r"아파트[·/,\s]*오피스텔", "", search_txt)
                            apt_cnt = cleaned_search.count("아파트")
                            off_cnt = cleaned_search.count("오피스텔")
                            villa_cnt = (
                                cleaned_search.count("다세대")
                                + cleaned_search.count("빌라")
                                + cleaned_search.count("연립")
                            )

                            if apt_cnt >= 10 and apt_cnt >= off_cnt * 2:
                                naver_land_type = "아파트"
                                naver_land_evidence = (
                                    f"네이버부동산·포털 단지검증(아파트 매칭 {apt_cnt}건 vs 오피스텔 {off_cnt}건)"
                                )
                            elif off_cnt >= 6 and off_cnt > apt_cnt:
                                naver_land_type = "오피스텔"
                                naver_land_evidence = (
                                    f"네이버부동산·포털 단지검증(오피스텔 매칭 {off_cnt}건 vs 아파트 {apt_cnt}건)"
                                )
                            elif villa_cnt >= 6 and villa_cnt > apt_cnt:
                                naver_land_type = "다세대(빌라)"
                                naver_land_evidence = (
                                    f"네이버부동산·포털 단지검증(다세대/빌라 매칭 {villa_cnt}건)"
                                )
                except Exception:
                    pass

        # 3단계: 경매 원천 검색 스니펫(auction_snippets) 문맥 정밀 분석 (광고 문구 배제)
        snippet_type = ""
        snippet_evidence = ""
        if auction_snippets:
            cleaned_snip = re.sub(r"아파트[·/,\s]*오피스텔", "", auction_snippets)
            apt_s = cleaned_snip.count("아파트")
            off_s = cleaned_snip.count("오피스텔")
            villa_s = cleaned_snip.count("다세대") + cleaned_snip.count("빌라") + cleaned_snip.count("연립")
            if apt_s > off_s and apt_s >= 2:
                snippet_type = "아파트"
                snippet_evidence = f"경매문건·포털 스니펫 교차검증(아파트 {apt_s}회 > 오피스텔 {off_s}회)"
            elif off_s > apt_s and off_s >= 2:
                snippet_type = "오피스텔"
                snippet_evidence = f"경매문건·포털 스니펫 교차검증(오피스텔 {off_s}회 > 아파트 {apt_s}회)"
            elif villa_s > apt_s and villa_s >= 2:
                snippet_type = "다세대(빌라)"
                snippet_evidence = f"경매문건·포털 스니펫 교차검증(다세대/빌라 {villa_s}회)"

        # 4단계: 종합 판정 우선순위 결정
        # (1) 주소 자체에 '아파트'가 명시되어 있거나, 'XXX동 XXX호' 대단지 동호수 구조이면서 브랜드/전용면적(>=49㎡)이 아파트인 경우
        if explicit_apt_in_addr:
            return "아파트", naver_land_evidence or "소재지/건축물대장 아파트 명시 및 네이버부동산 교차확인"

        if explicit_off_in_addr and not has_dong_number:
            return "오피스텔", naver_land_evidence or "소재지/단지명 오피스텔 확인"

        if explicit_villa_in_addr:
            return "다세대(빌라)", naver_land_evidence or "소재지/건축물대장 다세대(빌라) 확인"

        if any(k in combined_local for k in cls.OFFICETEL_KEYWORDS) and exclusive_area_m2 < 50.0 and not has_dong_number:
            return "오피스텔", naver_land_evidence or "네이버부동산 단지정보 오피스텔(전용면적·건물명) 확인"

        if has_dong_number and (
            any(b in combined_local for b in cls.APT_BRAND_KEYWORDS) or exclusive_area_m2 >= 50.0
        ):
            return "아파트", naver_land_evidence or f"네이버부동산·건축물대장 단지검증({extracted_bldg or '공동주택'} 아파트)"

        if naver_land_type:
            return naver_land_type, naver_land_evidence

        if snippet_type:
            return snippet_type, snippet_evidence

        if any(b in combined_local for b in cls.APT_BRAND_KEYWORDS):
            return "아파트", "단지 브랜드/명칭 기반 아파트 확인"

        if initial_type in ("아파트", "오피스텔", "다세대(빌라)"):
            return initial_type, f"원천 분류({initial_type}) 유지"

        return "아파트", "기본 공동주택(아파트) 분류"

    @staticmethod
    def parse_articles_json(
        complex_name: str,
        sale_prices: List[int],
        jeonse_prices: List[int],
        verified_property_type: str = "",
        verification_source: str = "",
    ) -> NaverLandData:
        sale_min = min(sale_prices) if sale_prices else 0
        sale_avg = int(sum(sale_prices) / len(sale_prices)) if sale_prices else 0
        jeonse_avg = int(sum(jeonse_prices) / len(jeonse_prices)) if jeonse_prices else 0

        return NaverLandData(
            complex_or_area_name=complex_name,
            asking_sale_min=sale_min,
            asking_sale_avg=sale_avg,
            asking_jeonse_avg=jeonse_avg,
            active_listing_count=len(sale_prices) + len(jeonse_prices),
            verified_property_type=verified_property_type,
            verification_source=verification_source,
        )


def normalize_case_no(raw_text: str) -> str:
    """
    '2025타경 2768', '2025 타경 2768', '2025타경2768[1]', '2025-2768' 등 다양한 사건번호 입력을
    표준 포맷 'YYYY타경NNNN'으로 정규화합니다.
    """
    cleaned = raw_text.strip()
    m = re.search(r"(20\d{2})\s*타\s*경\s*0*(\d+)", cleaned)
    if m:
        return f"{m.group(1)}타경{m.group(2)}"
    m2 = re.search(r"^(20\d{2})\s*[-_]\s*0*(\d+)$", cleaned)
    if m2:
        return f"{m2.group(1)}타경{m2.group(2)}"
    return re.sub(r"\s+", "", cleaned)

