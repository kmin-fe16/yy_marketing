import os
import json as _json
import queue as _queue
import threading
import importlib
import requests as req
from flask import Flask, request, redirect, send_file, jsonify, Response, stream_with_context, make_response

import generate_dashboard
import ad_setup_page

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()


def _bg_refresh():
    with LOCK:
        os.chdir(BASE_DIR)
        importlib.reload(generate_dashboard)
        generate_dashboard.main()


@app.route("/")
def index():
    html_path = os.path.join(BASE_DIR, "dashboard.html")
    if not os.path.exists(html_path):
        _bg_refresh()
    resp = make_response(send_file(html_path))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/refresh", methods=["POST"])
def refresh():
    with LOCK:
        os.chdir(BASE_DIR)
        importlib.reload(generate_dashboard)
        generate_dashboard.main()
    return redirect("/")


@app.route("/notion-upload", methods=["POST"])
def notion_upload():
    results = []
    try:
        import notion_client_helper, create_campaign
        importlib.reload(notion_client_helper)
        importlib.reload(create_campaign)
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
                import notion_client_helper, create_campaign
                importlib.reload(notion_client_helper)
                importlib.reload(create_campaign)
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
                        try:
                            import json as _j
                            _lf = os.path.join(BASE_DIR, "logs", "upload_log.json")
                            _log = _j.load(open(_lf, encoding="utf-8")) if os.path.exists(_lf) else []
                            _log.insert(0, {
                                "uploaded_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"),
                                "캠페인명": camp.get("공연명", name),
                                "차수": camp.get("차수", ""),
                                "공연명": camp.get("공연명", ""),
                                "에셋A": "", "에셋B": "", "에셋C": "",
                                "캠페인ID": "",
                                "status": "실패",
                                "error": str(e),
                                "active": False,
                            })
                            open(_lf, "w", encoding="utf-8").write(_j.dumps(_log[:200], ensure_ascii=False, indent=2))
                        except Exception:
                            pass

                q.put(_sse({"type": "done", "results": results}))
            except Exception as e:
                q.put(_sse({"type": "error", "msg": str(e)}))
            finally:
                q.put(None)
                threading.Thread(target=_bg_refresh, daemon=True).start()

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
    importlib.reload(ad_setup_page)
    html = ad_setup_page.build_ad_setup_html()
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.route("/ad-setup/run/<page_id>", methods=["POST"])
def ad_setup_run(page_id):
    try:
        import notion_client_helper, create_campaign
        importlib.reload(notion_client_helper)
        importlib.reload(create_campaign)
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
        _bg_refresh()
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


@app.route("/api/upload-log/toggle", methods=["POST"])
def toggle_upload_log():
    data = request.get_json(force=True) or {}
    campaign_id = data.get("campaign_id", "")
    active = data.get("active", False)

    if not campaign_id:
        return jsonify({"error": "campaign_id 필요"}), 400

    META_TOKEN = os.getenv("META_ACCESS_TOKEN")
    META_VERSION = os.getenv("META_API_VERSION", "v20.0")
    meta_status = "ACTIVE" if active else "PAUSED"
    base_url = f"https://graph.facebook.com/{META_VERSION}"

    def _set_status(obj_id):
        r = req.post(
            f"{base_url}/{obj_id}",
            data={"status": meta_status, "access_token": META_TOKEN},
            timeout=15,
        )
        return r.json()

    def _get_ids(endpoint):
        ids = []
        url = f"{base_url}/{campaign_id}/{endpoint}"
        params = {"fields": "id", "access_token": META_TOKEN, "limit": 200}
        while url:
            r = req.get(url, params=params, timeout=15)
            body = r.json()
            ids.extend(x["id"] for x in body.get("data", []))
            url = body.get("paging", {}).get("next")
            params = {}
        return ids

    try:
        # 캠페인
        result = _set_status(campaign_id)
        if not result.get("success"):
            return jsonify({"error": "캠페인 Meta API 실패", "detail": result}), 500

        # 광고세트
        adset_ids = _get_ids("adsets")
        for aid in adset_ids:
            _set_status(aid)

        # 광고
        ad_ids = _get_ids("ads")
        for aid in ad_ids:
            _set_status(aid)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    log_file = os.path.join(BASE_DIR, "logs", "upload_log.json")
    if os.path.exists(log_file):
        with open(log_file, encoding="utf-8") as f:
            log = _json.load(f)
        for entry in log:
            if entry.get("캠페인ID") == campaign_id:
                entry["active"] = active
                break
        with open(log_file, "w", encoding="utf-8") as f:
            _json.dump(log, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True, "adsets": len(adset_ids), "ads": len(ad_ids)})


@app.route("/api/upload-log/48h", methods=["POST"])
def update_48h_log():
    data = request.get_json(force=True) or {}
    campaign_id = data.get("campaign_id", "")
    if not campaign_id:
        return jsonify({"error": "campaign_id 필요"}), 400
    log_file = os.path.join(BASE_DIR, "logs", "upload_log.json")
    if os.path.exists(log_file):
        with open(log_file, encoding="utf-8") as f:
            log = _json.load(f)
        for entry in log:
            if entry.get("캠페인ID") == campaign_id:
                if "h48_asset" in data:
                    entry["h48_asset"] = data["h48_asset"]
                if "h48_off_done" in data:
                    entry["h48_off_done"] = data["h48_off_done"]
                break
        with open(log_file, "w", encoding="utf-8") as f:
            _json.dump(log, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


@app.route("/api/active-asset")
def active_asset():
    campaign_id = request.args.get("campaign_id", "")
    if not campaign_id:
        return jsonify({"asset": None})
    META_TOKEN = os.getenv("META_ACCESS_TOKEN")
    META_VERSION = os.getenv("META_API_VERSION", "v20.0")
    try:
        r = req.get(
            f"https://graph.facebook.com/{META_VERSION}/{campaign_id}/ads",
            params={"fields": "name,status", "access_token": META_TOKEN, "limit": 10},
            timeout=15,
        )
        ads = r.json().get("data", [])
        active = [a for a in ads if a.get("status") == "ACTIVE"]
        # 광고가 1개만 ACTIVE일 때만 선택된 에셋으로 판단
        if len(active) != 1:
            return jsonify({"asset": None, "active_count": len(active)})
        name = active[0].get("name", "")
        for suffix, label in [("-1", "A"), ("-2", "B"), ("-3", "C")]:
            if name.endswith(suffix):
                return jsonify({"asset": label})
        return jsonify({"asset": None})
    except Exception as e:
        return jsonify({"asset": None, "error": str(e)})


@app.route("/api/campaign-insights")
def campaign_insights():
    from datetime import date as _date
    campaign_id = request.args.get("campaign_id", "")
    since = request.args.get("since", "")
    if not campaign_id or not since:
        return jsonify({"error": "파라미터 필요"}), 400
    META_TOKEN = os.getenv("META_ACCESS_TOKEN")
    META_VERSION = os.getenv("META_API_VERSION", "v20.0")
    try:
        until = _date.today().isoformat()
        r = req.get(
            f"https://graph.facebook.com/{META_VERSION}/{campaign_id}/insights",
            params={
                "fields": "impressions,reach,clicks,ctr,spend,cpc",
                "time_range": _json.dumps({"since": since[:10], "until": until}),
                "access_token": META_TOKEN,
            },
            timeout=15,
        )
        data = r.json().get("data", [])
        return jsonify(data[0] if data else {})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/dry-run-alerts")
def dry_run_alerts():
    alert_file = os.path.join(BASE_DIR, "logs", "dry_run_alerts.json")
    if not os.path.exists(alert_file):
        return jsonify([])
    with open(alert_file, encoding="utf-8") as f:
        return jsonify(_json.load(f))


@app.route("/api/dry-run-alerts/dismiss", methods=["POST"])
def dismiss_dry_run_alert():
    data = request.get_json(force=True) or {}
    key = (data.get("공연날짜", ""), data.get("공연명", ""), data.get("차수", ""))
    alert_file = os.path.join(BASE_DIR, "logs", "dry_run_alerts.json")
    if os.path.exists(alert_file):
        with open(alert_file, encoding="utf-8") as f:
            alerts = _json.load(f)
        alerts = [a for a in alerts if (a.get("공연날짜"), a.get("공연명"), a.get("차수")) != key]
        with open(alert_file, "w", encoding="utf-8") as f:
            _json.dump(alerts, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


if __name__ == "__main__":
    print("=" * 50)
    print("Meta 광고 대시보드 서버 시작")
    print("로컬: http://localhost:5001")
    print("팀 공유: ngrok http 5000 (별도 터미널)")
    print("=" * 50)
    threading.Thread(target=_bg_refresh, daemon=True).start()
    app.run(host="0.0.0.0", port=5001, debug=False)
