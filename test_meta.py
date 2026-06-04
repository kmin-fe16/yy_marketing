import requests
import json

ACCESS_TOKEN = "EAAcS3syXjtcBRqFui6iZBybqqcUYJmjQQCZCSy9zFUY3KN0JRtivnEdRmnmbchMKr4O3j03FIRvVqmZCRtklJ5ijGODGlIZBteZCoGTyf74Pkh8GJ0SXlGIW65r2QW0Ifs6njWqvIjqwU1DfJ6lasdxkLnbeaIuOvo5cVrDZAkufu47dOs8ZC5TZBk1svQnZCqMg2cdOzgYX2C19d4ZBtZAef8j"
AD_ACCOUNT_ID = "act_810493558680773"
API_VERSION = "v20.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


def get_campaigns():
    url = f"{BASE_URL}/{AD_ACCOUNT_ID}/campaigns"
    params = {
        "fields": "id,name,status,objective",
        "access_token": ACCESS_TOKEN,
        "limit": 100,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json().get("data", [])


def get_campaign_insights(campaign_id):
    url = f"{BASE_URL}/{campaign_id}/insights"
    params = {
        "fields": "campaign_name,impressions,clicks,spend,reach,ctr,cpc,actions",
        "date_preset": "last_30d",
        "access_token": ACCESS_TOKEN,
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    return response.json().get("data", [])


def main():
    print(f"광고 계정 {AD_ACCOUNT_ID} 캠페인 조회 중...\n")

    campaigns = get_campaigns()
    if not campaigns:
        print("캠페인이 없습니다.")
        return

    print(f"총 {len(campaigns)}개 캠페인 발견\n")
    print("=" * 60)

    for campaign in campaigns:
        cid = campaign["id"]
        name = campaign.get("name", "이름 없음")
        status = campaign.get("status", "-")
        objective = campaign.get("objective", "-")

        print(f"\n[캠페인] {name}")
        print(f"  ID: {cid} | 상태: {status} | 목표: {objective}")

        insights = get_campaign_insights(cid)
        if not insights:
            print("  성과 데이터 없음 (기간 내 집행 없음)")
            continue

        for row in insights:
            print(f"  노출수:    {row.get('impressions', 0)}")
            print(f"  클릭수:    {row.get('clicks', 0)}")
            print(f"  CTR:       {row.get('ctr', '0')}%")
            print(f"  CPC:       ${row.get('cpc', '0')}")
            print(f"  소진금액:  ${row.get('spend', '0')}")
            print(f"  도달수:    {row.get('reach', 0)}")

            actions = row.get("actions", [])
            if actions:
                print("  전환:")
                for action in actions:
                    print(f"    {action['action_type']}: {action['value']}")

        print("-" * 60)


if __name__ == "__main__":
    main()
