import os
import json as _json
import queue as _queue
import threading
import requests as req
from flask import Flask, request, redirect, send_file, jsonify, Response, stream_with_context

import generate_dashboard
import ad_setup_page

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()


def _bg_refresh():
    with LOCK:
        os.chdir(BASE_DIR)
        generate_dashboard.main()


@app.route("/")
def index():
    html_path = os.path.join(BASE_DIR, "dashboard.html")
    if not os.path.exists(html_path):
        _bg_refresh()
    return send_file(html_path)


@app.route("/refresh", methods=["POST"])
def refresh():
    with LOCK:
        os.chdir(BASE_DIR)
        generate_dashboard.main()
    return redirect("/")


@app.route("/notion-upload", methods=["POST"])
def notion_upload():
    results = []
    try:
        from notion_client_helper import query_campaigns as _qc, parse_campaign as _parse
        from create_campaign import process as _upload
        pending_pages = _qc(filter_status="대기")
        if not pending_pages:
            return jsonify({"message": "대기 캠페인 없음"}), 200
        for page in pending_pages:
            camp = _parse(page)
            name = camp.get("공연명", page.get("id", "?"))
            try:
                _upload(page)
                results.append({"name": name, "status": "완료"})
            except Exception as e:
                results.append({"name": name, "status": "실패", "error": str(e)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return redirect("/")


@app.route("/notion-sync-sse")
def notion_sync_sse():
    def generate():
        q = _queue.Queue()

        def run():
            try:
                from notion_client_helper import query_campaigns as _qc, parse_campaign as _parse
                from create_campaign import process as _upload

                q.put(_sse({"type": "status", "msg": "노션 대기 캠페인 조회 중..."}))
                pending_pages = _qc(filter_status="대기")

                if not pending_pages:
                    q.put(_sse({"type": "done", "msg": "대기 캠페인 없음", "results": []}))
                    q.put(None)
                    return

                total = len(pending_pages)
                q.put(_sse({"type": "total", "total": total}))

                results = []
                for i, page in enumerate(pending_pages):
                    camp = _parse(page)
                    name = camp.get("공연명", "?")
                    q.put(_sse({"type": "progress", "current": i + 1, "total": total, "name": name}))
                    try:
                        _upload(page, on_step=lambda msg, i=i, t=total: q.put(
                            _sse({"type": "sub", "msg": msg, "campaign_idx": i + 1, "total": t})
                        ))
                        results.append({"name": name, "ok": True})
                        q.put(_sse({"type": "item", "name": name, "ok": True}))
                    except Exception as e:
                        results.append({"name": name, "ok": False, "error": str(e)})
                        q.put(_sse({"type": "item", "name": name, "ok": False, "error": str(e)}))

                q.put(_sse({"type": "done", "results": results}))
            except Exception as e:
                q.put(_sse({"type": "error", "msg": str(e)}))
            finally:
                q.put(None)

        threading.Thread(target=run, daemon=True).start()
        while True:
            msg = q.get()
            if msg is None:
                break
            yield msg

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(data: dict) -> str:
    return f"data: {_json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/ad-setup")
def ad_setup():
    html = ad_setup_page.build_ad_setup_html()
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ad-setup/run/<page_id>", methods=["POST"])
def ad_setup_run(page_id):
    try:
        from create_campaign import process
        import requests as req
        from notion_client_helper import query_campaigns, parse_campaign
        NOTION_TOKEN = os.getenv("NOTION_TOKEN")
        CAMPAIGN_DB_ID = os.getenv("CAMPAIGN_NOTION_DB_ID")
        NOTION_HEADERS = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28",
        }
        resp = req.get(
            f"https://api.notion.com/v1/pages/{page_id}",
            headers=NOTION_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        page = resp.json()
        process(page)
        return jsonify({"message": "캠페인 생성 완료 — 노션 상태가 '업로드완료'로 변경됐습니다."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/campaign/activate", methods=["POST"])
def campaign_activate():
    data = request.get_json(force=True)
    campaign_id = (data or {}).get("campaign_id")
    page_id = (data or {}).get("page_id")
    if not campaign_id:
        return jsonify({"error": "campaign_id 필요"}), 400

    META_TOKEN = os.getenv("META_ACCESS_TOKEN")
    META_VERSION = os.getenv("META_API_VERSION", "v20.0")

    try:
        meta_resp = req.post(
            f"https://graph.facebook.com/{META_VERSION}/{campaign_id}",
            data={"status": "ACTIVE", "access_token": META_TOKEN},
            timeout=15,
        )
        result = meta_resp.json()
        if not result.get("success"):
            return jsonify({"error": "Meta API 실패", "detail": result}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if page_id:
        try:
            from notion_client_helper import update_campaign
            update_campaign(page_id, {"상태": "집행중"})
        except Exception as e:
            return jsonify({"success": True, "notion_warning": str(e)})

    return jsonify({"success": True})


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("csv")
    if f and f.filename:
        f.save(os.path.join(BASE_DIR, "당근.csv"))
    with LOCK:
        os.chdir(BASE_DIR)
        generate_dashboard.main()
    return redirect("/")


if __name__ == "__main__":
    print("=" * 50)
    print("Meta 광고 대시보드 서버 시작")
    print("로컬: http://localhost:5001")
    print("팀 공유: ngrok http 5000 (별도 터미널)")
    print("=" * 50)
    threading.Thread(target=_bg_refresh, daemon=True).start()
    app.run(host="0.0.0.0", port=5001, debug=False)
