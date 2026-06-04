import os
import requests
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_message(text: str, chat_id: str = None) -> bool:
    """텔레그램 메시지 발송. 실패해도 예외 없이 False 반환."""
    token = BOT_TOKEN
    cid = chat_id or CHAT_ID
    if not token or not cid or token.startswith("여기에"):
        print(f"[텔레그램] 설정 미완료 — .env에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 입력 필요")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": cid, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.ok:
            print(f"[텔레그램] 발송 완료")
            return True
        print(f"[텔레그램] 발송 실패: {resp.text}")
        return False
    except Exception as e:
        print(f"[텔레그램] 오류: {e}")
        return False


if __name__ == "__main__":
    # 테스트 메시지
    ok = send_message("✅ 텔레그램 봇 연결 테스트 성공!")
    if not ok:
        print()
        print("설정 방법:")
        print("1. 텔레그램에서 @BotFather 검색")
        print("2. /newbot 명령어로 봇 생성 → 토큰 복사")
        print("3. 봇에게 아무 메시지 전송 후 아래 URL로 chat_id 확인:")
        print("   https://api.telegram.org/bot<토큰>/getUpdates")
        print("4. .env 파일에 TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 입력")
