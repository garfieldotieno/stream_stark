from flask import Flask, request, jsonify, Response, render_template, send_file, make_response
from flask_cors import CORS
import redis
import os
from dotenv import load_dotenv
from datetime import datetime
from models import db, ClientDevice, Payment, Transaction
import re

# Load environment variables
load_dotenv()

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
CHANNEL = "video_control"

app = Flask(__name__)
CORS(app)

# Configure database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///platform.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

with app.app_context():
    db.create_all()

# Redis connection
rdb = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
CHUNK = 1024 * 64  # 64KB per chunk

# -------------------- Regex Parsing --------------------
def parse_payment_message(msg):
    result = {}
    txn_id_match = re.search(r'([A-Z]{3,}\d+[A-Z\d]*)', msg)
    result['transaction_id'] = txn_id_match.group(1) if txn_id_match else None
    amount_match = re.search(r'Ksh\s?([\d,]+(?:\.\d{1,2})?)', msg)
    result['amount'] = float(amount_match.group(1).replace(',', '')) if amount_match else None
    phone_match = re.search(r'\b(\d{7,12})\b', msg)
    result['phone'] = phone_match.group(1) if phone_match else None
    name_match = re.search(r'(?:sent to|from)\s([A-Z][a-zA-Z]+\s[A-Z][a-zA-Z]+)', msg)
    result['name'] = name_match.group(1) if name_match else None
    date_match = re.search(r'on\s(\d{1,2}/\d{1,2}/\d{2,4})\s+at\s([\d:APM\s]+)', msg)
    if date_match:
        result['date'] = date_match.group(1)
        result['time'] = date_match.group(2)
    else:
        result['date'] = None
        result['time'] = None
    return result

# -------------------- File & Video Endpoints --------------------
def send_with_range(path, mime, download_name):
    if not os.path.exists(path):
        return {"error": "File not found"}, 404
    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range", "").strip()
    if request.method == "HEAD":
        resp = make_response("", 200)
        resp.headers["Content-Type"] = mime
        resp.headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(file_size)
        return resp
    if not range_header:
        resp = make_response(send_file(path, mimetype=mime, as_attachment=True, download_name=download_name))
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Content-Length"] = str(file_size)
        return resp
    try:
        units, rng = range_header.split("=")
        start_s, end_s = rng.split("-", 1)
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
        if start > end or end >= file_size:
            resp = Response(status=416)
            resp.headers["Content-Range"] = f"bytes */{file_size}"
            return resp
    except Exception:
        resp = make_response(send_file(path, mimetype=mime, as_attachment=True, download_name=download_name))
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
    return send_with_range(path, mime="application/vnd.android.package-archive", download_name="app-release.apk")

@app.route("/download-icon", methods=["GET", "HEAD"])
def download_icon():
    path = os.path.join(app.root_path, "static", "apps", "icon.png")
    return send_with_range(path, mime="image/png", download_name="icon.png")

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

# -------------------- Client Device API --------------------
@app.route("/client-device", methods=["POST", "GET"])
def client_device():
    if request.method == "POST":
        data = request.get_json()
        device_id = data.get("device_id")
        if not device_id:
            return jsonify({"error": "device_id required"}), 400
        device = ClientDevice.query.filter_by(device_id=device_id).first()
        if not device:
            device = ClientDevice(device_id=device_id)
            db.session.add(device)
            db.session.commit()
        return jsonify({"id": device.id, "device_id": device.device_id, "tokens": device.tokens})
    else:
        devices = ClientDevice.query.all()
        return jsonify([{"id": d.id, "device_id": d.device_id, "tokens": d.tokens} for d in devices])

@app.route("/client-device/<device_id>/balance", methods=["GET"])
def check_balance(device_id):
    device = ClientDevice.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Device not found"}), 404
    return jsonify({"device_id": device.device_id, "tokens": device.tokens})

# -------------------- Payment API --------------------
@app.route("/payment", methods=["POST"])
def add_payment():
    data = request.get_json()
    device_id = data.get("device_id")
    reference_message = data.get("reference_message")

    if not device_id or not reference_message:
        return jsonify({"error": "device_id and reference_message required"}), 400

    device = ClientDevice.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Device not found"}), 404

    parsed = parse_payment_message(reference_message)
    amount_paid = parsed.get("amount", 0)
    txn_id = parsed.get("transaction_id")

    payment = Payment(
        client_device_id=device.id,
        amount_paid=amount_paid,
        tokens_received=0,
        transaction_id=txn_id,
        reference_message=reference_message,
        status="pending"
    )
    db.session.add(payment)
    db.session.commit()

    parsed.update({
        "payment_id": payment.id,
        "status": payment.status
    })
    return jsonify(parsed)

@app.route("/payment/verify", methods=["POST"])
def verify_payment():
    data = request.get_json()
    transaction_id = data.get("transaction_id")
    amount_paid = data.get("amount_paid")

    payment = Payment.query.filter_by(transaction_id=transaction_id, amount_paid=amount_paid, status="pending").first()
    if not payment:
        return jsonify({"error": "No matching pending payment found"}), 404

    device = ClientDevice.query.get(payment.client_device_id)
    tokens = int(amount_paid * 1.2)
    payment.tokens_received = tokens
    payment.status = "verified"
    device.tokens += tokens

    tx = Transaction(
        client_device_id=device.id,
        type="purchase_token",
        amount=tokens
    )
    db.session.add(tx)
    db.session.commit()

    return jsonify({
        "status": "verified",
        "device_id": device.device_id,
        "tokens_added": tokens,
        "current_tokens": device.tokens
    })

# -------------------- Item Purchase --------------------
@app.route("/transaction/purchase-item", methods=["POST"])
def purchase_item():
    data = request.get_json()
    device_id = data.get("device_id")
    item = data.get("item")
    token_cost = data.get("token_cost")

    device = ClientDevice.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Device not found"}), 404
    if device.tokens < token_cost:
        return jsonify({"error": "Not enough tokens"}), 400

    device.tokens -= token_cost
    tx = Transaction(client_device_id=device.id, type="purchase_item", amount=token_cost, item=item)
    db.session.add(tx)
    db.session.commit()

    return jsonify({"status": "ok", "remaining_tokens": device.tokens})


@app.route("/payment/<device_id>", methods=["GET"])
def list_payments(device_id):
    device = ClientDevice.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Device not found"}), 404

    payments = Payment.query.filter_by(client_device_id=device.id).all()
    return jsonify([{
        "id": p.id,
        "amount_paid": p.amount_paid,
        "tokens_received": p.tokens_received,
        "transaction_id": p.transaction_id,
        "status": p.status,
        "created_at": p.created_at.isoformat()
    } for p in payments])



@app.route("/transaction/<device_id>", methods=["GET"])
def list_transactions(device_id):
    device = ClientDevice.query.filter_by(device_id=device_id).first()
    if not device:
        return jsonify({"error": "Device not found"}), 404
    transactions = Transaction.query.filter_by(client_device_id=device.id).all()
    return jsonify([{
        "id": t.id,
        "type": t.type,
        "amount": t.amount,
        "item": t.item,
        "created_at": t.created_at.isoformat()
    } for t in transactions])

# -------------------- Run Server --------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        threaded=True,
        debug=True
    )
