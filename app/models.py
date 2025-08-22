from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class ClientDevice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(100), unique=True, nullable=False)
    tokens = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    payments = db.relationship("Payment", backref="client_device", lazy=True)
    transactions = db.relationship("Transaction", backref="client_device", lazy=True)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_device_id = db.Column(db.Integer, db.ForeignKey("client_device.id"), nullable=False)
    amount_paid = db.Column(db.Float, nullable=False)
    tokens_received = db.Column(db.Integer, default=0)
    transaction_id = db.Column(db.String(50))  # extracted from message
    status = db.Column(db.String(20), default="pending")  # pending / verified / rejected
    reference_message = db.Column(db.Text)  # raw message
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_device_id = db.Column(db.Integer, db.ForeignKey("client_device.id"), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # "purchase_token" or "purchase_item"
    amount = db.Column(db.Integer, nullable=False)   # token amount
    item = db.Column(db.String(100), nullable=True)  # for purchase_item
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
