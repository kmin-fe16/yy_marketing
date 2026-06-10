"""Notion DB '대기' 행사 → Meta 캠페인 자동 생성.

트래픽 캠페인 1개 (35,000원/일), 광고세트 1개 + 에셋 최대 3개.
완료 시 Notion 상태 → '업로드완료'.
"""
import os
import re
import requests
from datetime import datetime
from dotenv import load_dotenv
from notion_client_helper import parse_campaign, update_campaign, find_latest_settings
from telegram_bot import send_message

load_dotenv()

TOKEN      = os.getenv("META_ACCESS_TOKEN")
AD_ACCOUNT = os.getenv("META_AD_ACCOUNT_ID", "act_810493558680773")
API        = f"https://graph.facebook.com/{os.getenv('META_API_VERSION', 'v20.0')}"
NOTION_TOKEN   = os.getenv("NOTION_TOKEN")
CAMPAIGN_DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID", os.getenv("NOTION_DB_ID"))

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}

BUDGET_TRAFFIC = 35_000   # 트래픽 일예산 (원)
BUDGET_LEAD    = 20_000   # 잠재고객 일예산 (원)

_page_id_cache = None


# ── Notion 조회 ──────────────────────────────────────────────────────

def query_pending() -> list:
    """CAMPAIGN_NOTION_DB_ID에서 상태='대기' 페이지 전체 조회."""
    pages, cursor = [], None
    while True:
        body = {"filter": {"property": "상태", "select": {"equals": "대기"}}}
        if cursor:
            body["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{CAMPAIGN_DB_ID}/query",
            headers=NOTION_HEADERS, json=body, timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]
    return pages


# ── Google Drive URL → Meta 이미지 해시 ──────────────────────────────

def gdrive_to_image_hash(drive_url: str) -> str:
    """Google Drive 공유 URL에서 이미지를 다운로드해 Meta adimages에 업로드."""
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', drive_url) \
     or re.search(r'[?&]id=([a-zA-Z0-9_-]+)', drive_url)
    if not m:
        raise ValueError(f"Google Drive URL 파싱 실패: {drive_url}")
    file_id = m.group(1)

    dl_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    img_resp = requests.get(dl_url, timeout=30, allow_redirects=True)
    img_resp.raise_for_status()

    files = {"filename": (f"{file_id}.jpg", img_resp.content, "image/jpeg")}
    upload = requests.post(
        f"{API}/{AD_ACCOUNT}/adimages",
        params={"access_token": TOKEN},
        files=files,
        timeout=30,
    )
    upload.raise_for_status()
    images = upload.json().get("images", {})
    if not images:
        raise RuntimeError(f"이미지 업로드 실패: {upload.json()}")
    return list(images.values())[0]["hash"]


# ── Google Drive URL → Meta 동영상 ID ────────────────────────────────

def _gdrive_file_id(drive_url: str) -> str:
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', drive_url) \
     or re.search(r'[?&]id=([a-zA-Z0-9_-]+)', drive_url)
    if not m:
        raise ValueError(f"Google Drive URL 파싱 실패: {drive_url}")
    return m.group(1)

def _gdrive_download(drive_url: str) -> bytes:
    """Google Drive 파일 다운로드 (대용량 확인 토큰 자동 처리)."""
    file_id = _gdrive_file_id(drive_url)
    session = requests.Session()
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    resp = session.get(url, stream=True, timeout=60)
    resp.raise_for_status()
    # 대용량 파일 바이러스 확인 우회
    confirm = next(
        (v for k, v in resp.cookies.items() if k.startswith("download_warning")), None
    )
    if confirm:
        resp = session.get(url + f"&confirm={confirm}", stream=True, timeout=120)
        resp.raise_for_status()
    return resp.content

def gdrive_to_image_hash(drive_url: str) -> str:
    """Google Drive 공유 URL에서 이미지를 다운로드해 Meta adimages에 업로드."""
    file_id = _gdrive_file_id(drive_url)
    content = _gdrive_download(drive_url)
    files = {"filename": (f"{file_id}.jpg", content, "image/jpeg")}
    upload = requests.post(
        f"{API}/{AD_ACCOUNT}/adimages",
        params={"access_token": TOKEN},
        files=files,
        timeout=30,
    )
    upload.raise_for_status()
    images = upload.json().get("images", {})
    if not images:
        raise RuntimeError(f"이미지 업로드 실패: {upload.json()}")
    return list(images.values())[0]["hash"]

def _extract_first_frame(video_bytes: bytes) -> bytes:
    """ffmpeg으로 동영상 첫 프레임을 JPEG 바이트로 추출."""
    import subprocess, tempfile
    tmp_in = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False)
    tmp_out = tmp_in.name + '_thumb.jpg'
    try:
        tmp_in.write(video_bytes)
        tmp_in.close()
        subprocess.run(
            ['ffmpeg', '-y', '-i', tmp_in.name, '-vframes', '1', '-q:v', '2', tmp_out],
            capture_output=True, check=True,
        )
        with open(tmp_out, 'rb') as f:
            return f.read()
    finally:
        os.unlink(tmp_in.name)
        if os.path.exists(tmp_out):
            os.unlink(tmp_out)


def gdrive_to_video_id(drive_url: str) -> tuple:
    """Google Drive 동영상을 Meta에 업로드.
    Returns: (video_id, thumbnail_image_hash)
    """
    file_id = _gdrive_file_id(drive_url)
    content = _gdrive_download(drive_url)

    # 첫 프레임 → 썸네일 이미지 업로드
    thumb_bytes = _extract_first_frame(content)
    thumb_upload = requests.post(
        f"{API}/{AD_ACCOUNT}/adimages",
        params={"access_token": TOKEN},
        files={"filename": (f"{file_id}_thumb.jpg", thumb_bytes, "image/jpeg")},
        timeout=30,
    )
    thumb_upload.raise_for_status()
    images = thumb_upload.json().get("images", {})
    if not images:
        raise RuntimeError(f"썸네일 업로드 실패: {thumb_upload.json()}")
    img_info = list(images.values())[0]
    image_hash = img_info.get("hash") or ""
    image_url = img_info.get("url") or ""
    print(f"    [썸네일] hash={image_hash!r}  url={image_url!r}")
    if not image_hash and not image_url:
        raise RuntimeError(f"썸네일 hash/url 모두 없음: {img_info}")

    # 동영상 업로드
    upload = requests.post(
        f"{API}/{AD_ACCOUNT}/advideos",
        params={"access_token": TOKEN},
        files={"source": (f"{file_id}.mp4", content, "video/mp4")},
        data={"name": file_id},
        timeout=120,
    )
    upload.raise_for_status()
    result = upload.json()
    vid = result.get("id")
    if not vid:
        raise RuntimeError(f"동영상 업로드 실패: {result}")
    print(f"    [동영상] video_id={vid!r}")
    return vid, image_hash, image_url


# ── Meta API 헬퍼 ────────────────────────────────────────────────────

FB_PAGE_ID = os.getenv("META_FB_PAGE_ID", "952888584569714")
IG_USER_ID = os.getenv("META_IG_USER_ID", "17841478746782671")


def _get_page_id() -> str:
    global _page_id_cache
    if _page_id_cache:
        return _page_id_cache
    resp = requests.get(
        f"{API}/{AD_ACCOUNT}/promote_pages",
        params={"access_token": TOKEN, "fields": "id"},
        timeout=10,
    )
    if resp.ok:
        data = resp.json().get("data", [])
        if data:
            _page_id_cache = data[0]["id"]
            return _page_id_cache
    _page_id_cache = FB_PAGE_ID
    return FB_PAGE_ID


def create_campaign(name: str) -> str:
    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/campaigns",
        params={"access_token": TOKEN},
        json={
            "name": name,
            "objective": "OUTCOME_TRAFFIC",
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def _get_adset_geo_locations(adset_id: str) -> dict:
    """이전 광고세트에서 지역 타겟팅 정보 가져옴. 실패 시 전국(KR) 반환."""
    if not adset_id:
        return {"countries": ["KR"]}
    try:
        resp = requests.get(
            f"{API}/{adset_id}",
            params={"access_token": TOKEN, "fields": "targeting"},
            timeout=10,
        )
        if resp.ok:
            geo = resp.json().get("targeting", {}).get("geo_locations")
            if geo:
                return geo
    except Exception:
        pass
    return {"countries": ["KR"]}


def create_adset(campaign_id: str, name: str, daily_budget: int, info: dict, geo_locations: dict = None) -> str:
    targeting = {
        "age_min": 32,
        "age_max": 62,
        "genders": [2],                          # 여성
        "geo_locations": geo_locations or {"countries": ["KR"]},
        "locales": [12],                         # 한국어
        "publisher_platforms": ["facebook", "instagram"],
        "targeting_relaxation_types": {"lookalike": 0, "custom_audience": 0},
        "targeting_automation": {"advantage_audience": 0},
    }

    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adsets",
        params={"access_token": TOKEN},
        json={
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": daily_budget,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LANDING_PAGE_VIEWS",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "targeting": targeting,
            "status": "PAUSED",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_lead_campaign(name: str) -> str:
    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/campaigns",
        params={"access_token": TOKEN},
        json={
            "name": name,
            "objective": "OUTCOME_LEADS",
            "status": "PAUSED",
            "special_ad_categories": [],
            "is_adset_budget_sharing_enabled": False,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


def create_lead_adset(campaign_id: str, name: str, geo_locations: dict = None) -> str:
    targeting = {
        "age_min": 32,
        "age_max": 62,
        "genders": [2],
        "geo_locations": geo_locations or {"countries": ["KR"]},
        "locales": [12],
        "publisher_platforms": ["facebook", "instagram"],
        "targeting_relaxation_types": {"lookalike": 0, "custom_audience": 0},
        "targeting_automation": {"advantage_audience": 0},  # 원래 타겟 옵션 + 광고 도달에 제한 추가
    }
    resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adsets",
        params={"access_token": TOKEN},
        json={
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": BUDGET_LEAD,
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "LEAD_GENERATION",
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "destination_type": "ON_AD",
            "targeting": targeting,
            "status": "PAUSED",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["id"]


_LEAD_CREATIVE_OPTS = {
    "degrees_of_freedom_spec": {
        "creative_features_spec": {
            "standard_enhancements": {"enroll_status": "OPT_OUT"}
        }
    },
}


def create_lead_ad_image(adset_id: str, camp_name: str, n: int, image_hash: str, info: dict, form_id: str) -> str:
    ad_name = f"{camp_name}-{n}"
    label = ["A", "B", "C"][n - 1]
    creative_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adcreatives",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "object_story_spec": {
                "page_id": _get_page_id(),
                "instagram_user_id": IG_USER_ID,
                "link_data": {
                    "image_hash": image_hash,
                    "message": info.get(f"광고본문{label}") or "",
                    "name": info.get(f"광고제목{label}") or "",
                    "call_to_action": {
                        "type": "SIGN_UP",
                        "value": {"lead_gen_form_id": form_id},
                    },
                },
            },
            **_LEAD_CREATIVE_OPTS,
        },
        timeout=15,
    )
    if not creative_resp.ok:
        raise RuntimeError(f"lead adcreative(이미지) 실패: {creative_resp.json()}")
    creative_id = creative_resp.json()["id"]

    ad_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/ads",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
        timeout=15,
    )
    ad_resp.raise_for_status()
    return ad_resp.json()["id"]


def create_lead_ad_video(adset_id: str, camp_name: str, n: int, video_id: str, image_hash: str, image_url: str, info: dict, form_id: str) -> str:
    ad_name = f"{camp_name}-{n}"
    label = ["A", "B", "C"][n - 1]
    video_data = {
        "video_id": video_id,
        "title": info.get(f"광고제목{label}") or "",
        "message": info.get(f"광고본문{label}") or "",
        "call_to_action": {
            "type": "SIGN_UP",
            "value": {"lead_gen_form_id": form_id},
        },
    }
    if image_hash:
        video_data["image_hash"] = image_hash
    elif image_url:
        video_data["image_url"] = image_url
    else:
        raise RuntimeError("동영상 썸네일 없음")
    creative_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adcreatives",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "object_story_spec": {
                "page_id": _get_page_id(),
                "instagram_user_id": IG_USER_ID,
                "video_data": video_data,
            },
            **_LEAD_CREATIVE_OPTS,
        },
        timeout=15,
    )
    if not creative_resp.ok:
        raise RuntimeError(f"lead adcreative(영상) 실패: {creative_resp.json()}")
    creative_id = creative_resp.json()["id"]

    ad_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/ads",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
        timeout=15,
    )
    ad_resp.raise_for_status()
    return ad_resp.json()["id"]


def create_ad(adset_id: str, camp_name: str, n: int, image_hash: str, info: dict) -> str:
    ad_name = f"{camp_name}-{n}"
    label = ["A", "B", "C"][n - 1]
    headline = info.get(f"광고제목{label}") or ""
    body = info.get(f"광고본문{label}") or ""
    creative_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adcreatives",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "object_story_spec": {
                "page_id": _get_page_id(),
                "instagram_user_id": IG_USER_ID,
                "link_data": {
                    "image_hash": image_hash,
                    "link": info["랜딩URL"],
                    "message": body,
                    "name": headline,
                    "call_to_action": {
                        "type": "APPLY_NOW",
                    },
                },
            },
        },
        timeout=15,
    )
    if not creative_resp.ok:
        raise RuntimeError(f"adcreative 실패: {creative_resp.json()}")
    creative_id = creative_resp.json()["id"]

    ad_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/ads",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
        timeout=15,
    )
    ad_resp.raise_for_status()
    return ad_resp.json()["id"]


def create_ad_video(adset_id: str, camp_name: str, n: int, video_id: str, image_hash: str, image_url: str, info: dict) -> str:
    ad_name = f"{camp_name}-{n}"
    label = ["A", "B", "C"][n - 1]
    headline = info.get(f"광고제목{label}") or ""
    body = info.get(f"광고본문{label}") or ""
    video_data = {
        "video_id": video_id,
        "message": body,
        "title": headline,
        "call_to_action": {
            "type": "APPLY_NOW",
            "value": {"link": info["랜딩URL"]},
        },
    }
    if image_hash:
        video_data["image_hash"] = image_hash
    elif image_url:
        video_data["image_url"] = image_url
    else:
        raise RuntimeError("동영상 썸네일 없음: image_hash, image_url 모두 없음")
    print(f"    [크리에이티브] video_id={video_id!r}  thumbnail={'hash:'+image_hash if image_hash else 'url:'+image_url}")
    creative_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/adcreatives",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "object_story_spec": {
                "page_id": _get_page_id(),
                "instagram_user_id": IG_USER_ID,
                "video_data": video_data,
            },
        },
        timeout=15,
    )
    if not creative_resp.ok:
        raise RuntimeError(f"adcreative(영상) 실패: {creative_resp.json()}")
    creative_id = creative_resp.json()["id"]

    ad_resp = requests.post(
        f"{API}/{AD_ACCOUNT}/ads",
        params={"access_token": TOKEN},
        json={
            "name": ad_name,
            "adset_id": adset_id,
            "creative": {"creative_id": creative_id},
            "status": "PAUSED",
        },
        timeout=15,
    )
    ad_resp.raise_for_status()
    return ad_resp.json()["id"]


# ── 캠페인명 생성 ────────────────────────────────────────────────────

def build_camp_name(info: dict, suffix: str = "") -> str:
    d = datetime.fromisoformat(info["공연날짜"])
    yymmdd = d.strftime("%y%m%d")
    return f"{yymmdd} {info['공연장소']} {info['행사구분']} {info['차수']}{suffix}"


# ── 행사 1개 처리 ────────────────────────────────────────────────────

def _upload_assets(asset_urls: list, is_video: bool, emit) -> list:
    asset_ids = []
    media_type = "동영상" if is_video else "이미지"
    for i, url in enumerate(asset_urls, 1):
        emit(f"{media_type} {i}/{len(asset_urls)} 업로드 중...")
        asset_ids.append(gdrive_to_video_id(url) if is_video else gdrive_to_image_hash(url))
        emit(f"{media_type} {i}/{len(asset_urls)} 완료")
        print(f"    ✓ 업로드 완료: {url[:60]}...")
    return asset_ids


def process(page: dict, on_step=None):
    def emit(msg):
        if on_step:
            on_step(msg)

    info = parse_campaign(page)
    name = info["공연명"]
    print(f"\n  처리 중: {name}")

    if info.get("차수") == "잠재":
        _process_lead(info, emit)
    else:
        _process_traffic(info, emit)

    print(f"  ✅ 완료: {name}")


def _process_traffic(info: dict, emit):
    camp_name = build_camp_name(info)
    is_video = info.get("차수") == "영상"

    geo_locations = None
    if info.get("차수") != "1차":
        emit("이전 지역 설정 조회 중...")
        prev = find_latest_settings(info["공연명"], info.get("공연날짜"))
        if prev and prev.get("광고세트ID"):
            geo_locations = _get_adset_geo_locations(prev["광고세트ID"])
            print(f"    ← 이전 지역 설정 적용: {geo_locations}")

    asset_urls = [u for u in [info["에셋A"], info["에셋B"], info["에셋C"]] if u]
    if not asset_urls:
        print(f"  ⚠️  에셋 URL 없음 — 건너뜀: {info['공연명']}")
        return

    asset_ids = _upload_assets(asset_urls, is_video, emit)

    emit("캠페인 생성 중...")
    print(f"    캠페인 생성: {camp_name}")
    cid = create_campaign(camp_name)

    try:
        emit("광고세트 생성 중...")
        asid = create_adset(cid, camp_name, BUDGET_TRAFFIC, info, geo_locations)

        for n, asset_id in enumerate(asset_ids, 1):
            emit(f"광고 소재 {n}/{len(asset_ids)} 생성 중...")
            if is_video:
                video_id, thumb_hash, thumb_url = asset_id
                create_ad_video(asid, camp_name, n, video_id, thumb_hash, thumb_url, info)
            else:
                create_ad(asid, camp_name, n, asset_id, info)

        emit("노션 업데이트 중...")
        print(f"    → 캠페인ID: {cid}, 에셋 {len(asset_ids)}개")
        update_campaign(info["page_id"], {
            "상태": "업로드완료",
            "Meta 캠페인 ID": cid,
            "Meta 광고세팅 ID": asid,
        })
    except Exception:
        try:
            requests.delete(f"{API}/{cid}", params={"access_token": TOKEN}, timeout=10)
            print(f"    ↩ 롤백: 캠페인 {cid} 삭제")
        except Exception:
            pass
        raise

    send_message(
        f"🎭 <b>[{camp_name}] 캠페인 생성 완료</b>\n\n"
        f"📍 장소: {info['공연장소']}\n"
        f"📅 공연일: {info['공연날짜']}\n"
        f"{'🎬' if info.get('차수') == '영상' else '🖼'} 에셋: {len(asset_ids)}개\n"
        f"💰 일예산 ₩{BUDGET_TRAFFIC:,}\n\n"
        f"대시보드에서 확인 후 ACTIVE 전환해주세요."
    )


def _process_lead(info: dict, emit):
    form_id = info.get("잠재폼id") or ""
    if not form_id:
        raise ValueError(f"잠재폼id 없음 — 노션에 입력 필요: {info['공연명']}")

    emit("이전 세팅값 조회 중...")
    prev = find_latest_settings(info["공연명"], info.get("공연날짜"))
    if not prev:
        raise RuntimeError(f"이전 업로드완료 세팅 없음 — 트래픽 캠페인 먼저 생성 필요: {info['공연명']}")

    print(f"    ← 이전 세팅 참조: {prev['차수']} (마지막 업로드완료)")

    geo_locations = None
    if prev.get("광고세트ID"):
        geo_locations = _get_adset_geo_locations(prev["광고세트ID"])
        print(f"    ← 이전 지역 설정 적용 (잠재): {geo_locations}")

    camp_name = build_camp_name(info)
    is_video = prev.get("차수") == "영상"

    asset_urls = [u for u in [prev["에셋A"], prev["에셋B"], prev["에셋C"]] if u]
    if not asset_urls:
        raise RuntimeError(f"이전 세팅에 에셋 URL 없음: {info['공연명']}")

    asset_ids = _upload_assets(asset_urls, is_video, emit)

    emit("잠재고객 캠페인 생성 중...")
    print(f"    캠페인 생성(잠재): {camp_name}")
    cid = create_lead_campaign(camp_name)

    try:
        emit("광고세트 생성 중...")
        asid = create_lead_adset(cid, camp_name, geo_locations)

        for n, asset_id in enumerate(asset_ids, 1):
            emit(f"광고 소재 {n}/{len(asset_ids)} 생성 중...")
            if is_video:
                video_id, thumb_hash, thumb_url = asset_id
                create_lead_ad_video(asid, camp_name, n, video_id, thumb_hash, thumb_url, prev, form_id)
            else:
                create_lead_ad_image(asid, camp_name, n, asset_id, prev, form_id)

        emit("노션 업데이트 중...")
        print(f"    → 캠페인ID: {cid}, 에셋 {len(asset_ids)}개, 폼ID: {form_id}")
        update_campaign(info["page_id"], {
            "상태": "업로드완료",
            "Meta 캠페인 ID": cid,
            "Meta 광고세팅 ID": asid,
        })
    except Exception:
        try:
            requests.delete(f"{API}/{cid}", params={"access_token": TOKEN}, timeout=10)
            print(f"    ↩ 롤백: 캠페인 {cid} 삭제")
        except Exception:
            pass
        raise

    send_message(
        f"📋 <b>[{camp_name}] 잠재고객 캠페인 생성 완료</b>\n\n"
        f"📍 장소: {info['공연장소']}\n"
        f"📅 공연일: {info['공연날짜']}\n"
        f"{'🎬' if is_video else '🖼'} 에셋: {len(asset_ids)}개 (이전 세팅 재사용)\n"
        f"📝 폼ID: {form_id}\n"
        f"💰 일예산 ₩{BUDGET_LEAD:,}\n\n"
        f"대시보드에서 확인 후 ACTIVE 전환해주세요."
    )


# ── 메인 ─────────────────────────────────────────────────────────────

def main():
    print(f"캠페인 자동 생성 시작 (DB: {CAMPAIGN_DB_ID})")
    pages = query_pending()
    if not pages:
        print("'대기' 상태 행사 없음.")
        return

    print(f"{len(pages)}개 행사 처리 시작...")
    for page in pages:
        try:
            process(page)
        except Exception as e:
            info = parse_campaign(page)
            print(f"  ❌ 실패: {info.get('공연명', '?')} — {e}")
            send_message(f"❌ [{info.get('공연명', '?')}] 캠페인 생성 실패\n오류: {e}")

    print("\n완료.")


if __name__ == "__main__":
    main()
