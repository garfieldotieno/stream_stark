from flask import Flask, request, jsonify, Response, render_template, send_from_directory, stream_with_context, send_file, make_response
import redis
import os
import json
import time
from dotenv import load_dotenv
from flask_cors import CORS

# Load environment variables
load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
CHANNEL = "video_control"

app = Flask(__name__)
CORS(app)

# Redis connection
rdb = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)


CHUNK = 1024 * 64  # 64KB per chunk

def send_with_range(path, mime, download_name):
    """
    Serve a file with proper Range/206 support and correct headers.
    Works for GET and HEAD.
    """
    if not os.path.exists(path):
        return {"error": "File not found"}, 404

    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range", "").strip()

    # HEAD request: just return headers
    if request.method == "HEAD":
        resp = make_response("", 200)
        resp.headers["Content-Type"] = mime
        resp.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(file_size)
        return resp

    # No range → send full with explicit headers
    if not range_header:
        resp = make_response(
            send_file(path, mimetype=mime, as_attachment=True, download_name=download_name)
        )
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(file_size)
        return resp

    # Parse Range: bytes=start-end
    try:
        units, rng = range_header.split("=")
        if units != "bytes":
            raise ValueError
        start_s, end_s = rng.split("-", 1)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        if start > end or end >= file_size:
            # 416 Range Not Satisfiable
            resp = Response(status=416)
            resp.headers["Content-Range"] = f"bytes */{file_size}"
            return resp
    except Exception:
        # Bad range → fall back to full file
        resp = make_response(
            send_file(path, mimetype=mime, as_attachment=True, download_name=download_name)
        )
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(file_size)
        return resp

    length = end - start + 1

    def generate():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(CHUNK, remaining))
                if not chunk:
                    break
                yield chunk
                remaining -= len(chunk)

    resp = Response(generate(), status=206, mimetype=mime, direct_passthrough=True)
    resp.headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Content-Length"] = str(length)
    resp.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return resp


@app.route("/download-apk", methods=["GET", "HEAD"])
def download_apk():
    path = os.path.join(app.root_path, "static", "apps", "app-release.apk")
    return send_with_range(path,
                           mime="application/vnd.android.package-archive",
                           download_name="app-release.apk")


@app.route("/download-icon", methods=["GET", "HEAD"])
def download_icon():
    path = os.path.join(app.root_path, "static", "apps", "icon.png")
    return send_with_range(path,
                           mime="image/png",
                           download_name="icon.png")

@app.route("/", methods=["GET"])
def index():
    return render_template("apps.html")

@app.route("/control", methods=["POST"])
def control():
    data = request.get_json()
    action = data.get("action")
    if action not in {"play", "pause", "forward", "reverse"}:
        return jsonify({"status": "error", "message": "Invalid action"}), 400
    rdb.publish(CHANNEL, action)
    return jsonify({"status": "ok", "sent": action})

@app.route("/stream")
def stream():
    def event_stream():
        pubsub = rdb.pubsub()
        pubsub.subscribe(CHANNEL)
        for message in pubsub.listen():
            if message["type"] == "message":
                yield f"data: {message['data']}\n\n"
    return Response(event_stream(), mimetype="text/event-stream")

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True,
        debug=True,
        # ssl_context=("cert.pem", "key.pem")
    )

