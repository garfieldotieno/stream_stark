from zeroconf import Zeroconf, ServiceBrowser
import socket
import json
import time

SERVICE_TYPE = "_mycast._tcp.local."

class ReceiverListener:
    def __init__(self):
        self.receiver_info = None

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        if info:
            print(f"[+] Found receiver: {info.name}")
            self.receiver_info = info

    def remove_service(self, zeroconf, type, name):
        print(f"[-] Service removed: {name}")

def send_and_recv(sock, msg):
    sock.sendall(json.dumps(msg).encode("utf-8"))
    data = sock.recv(1024).decode("utf-8")
    try:
        response = json.loads(data)
        print(f"[TV ACK] {response}")
    except:
        print(f"[!] Invalid response: {data}")

def main():
    zeroconf = Zeroconf()
    listener = ReceiverListener()
    browser = ServiceBrowser(zeroconf, SERVICE_TYPE, listener)

    print("[*] Searching for receiver...")
    time.sleep(5)

    if not listener.receiver_info:
        print("[-] No receiver found.")
        return

    ip = socket.inet_ntoa(listener.receiver_info.addresses[0])
    port = listener.receiver_info.port
    print(f"[+] Connecting to {ip}:{port}")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ip, port))

    # Play command
    play_cmd = {"action": "play", "url": "https://sample-videos.com/video123/mp4/720/big_buck_bunny_720p_1mb.mp4"}
    send_and_recv(sock, play_cmd)

    time.sleep(30)  # shorter wait for testing

    # Stop command
    stop_cmd = {"action": "stop"}
    send_and_recv(sock, stop_cmd)

    sock.close()
    zeroconf.close()

if __name__ == "__main__":
    main()
