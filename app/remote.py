#!/usr/bin/env python3
import json
import os
import sys
from urllib.parse import urljoin
import requests

ALLOWED = {"play", "pause", "forward", "reverse"}
DEFAULT_SERVER_URL = "http://localhost:5000/"

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ALLOWED:
        print(f"Usage: {sys.argv[0]} <play|pause|forward|reverse>")
        sys.exit(1)

    action = sys.argv[1]
    server = os.getenv("SERVER_URL", DEFAULT_SERVER_URL)
    url = urljoin(server, "control")

    try:
        resp = requests.post(url, json={"action": action}, timeout=3)
        resp.raise_for_status()
        data = resp.json()
        print("Server response:", json.dumps(data, indent=2))
    except Exception as exc:
        print("❌ Could not send command:", exc)
        sys.exit(1)

if __name__ == "__main__":
    main()
