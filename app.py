import os
import threading
from flask import Flask, request, redirect, send_file, jsonify

import generate_dashboard

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOCK = threading.Lock()


@app.route("/")
def index():
    html_path = os.path.join(BASE_DIR, "dashboard.html")
    if not os.path.exists(html_path):
        with LOCK:
            os.chdir(BASE_DIR)
            generate_dashboard.main()
    return send_file(html_path)


@app.route("/refresh", methods=["POST"])
def refresh():
    with LOCK:
        os.chdir(BASE_DIR)
        generate_dashboard.main()
    return redirect("/")


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
    app.run(host="0.0.0.0", port=5001, debug=False)
