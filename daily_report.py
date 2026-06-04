"""매일 09:00 실행 — 대시보드 갱신 + D-30 업로드 + D+2 최적화."""
import subprocess
import sys
import os
from datetime import date
from pathlib import Path

BASE = Path(__file__).parent
PYTHON = sys.executable


def run(script: str):
    print(f"\n{'='*50}")
    print(f"▶ {script}")
    print('='*50)
    result = subprocess.run(
        [PYTHON, str(BASE / script)],
        cwd=str(BASE),
        capture_output=False,
    )
    return result.returncode == 0


def main():
    print(f"🕘 일일 자동화 시작 ({date.today()})")

    # 1. 노션 "대기" 행사 → Meta 캠페인 자동 생성
    run("create_campaign.py")

    # 2. D-30 업로드 확인
    run("auto_upload.py")

    # 3. D+2 최적화
    run("auto_optimize.py")

    # 4. 대시보드 갱신
    run("generate_dashboard.py")

    print(f"\n✅ 일일 자동화 완료")


if __name__ == "__main__":
    main()
