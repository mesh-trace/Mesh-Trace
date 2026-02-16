import sys
import os
import json
import time
from datetime import datetime, timezone
import base64
import hashlib
import hmac
from Crypto.Cipher import AES  # pyright: ignore[reportMissingImports]
from Crypto.Random import get_random_bytes  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
load_dotenv()
key_hex = os.getenv("LORA_SECRET_KEY")

if not key_hex:
    raise ValueError("LORA_SECRET_KEY not set in environment")

try:
    SECRET_KEY = bytes.fromhex(key_hex)
except ValueError:
    raise ValueError("LORA_SECRET_KEY must be valid hex")

if len(SECRET_KEY) != 32:
    raise ValueError("LORA_SECRET_KEY must be 32 bytes (64 hex characters)")



BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../lora_driver"))
sys.path.append(BASE_DIR)

from SX127x.LoRa import LoRa  # pyright: ignore[reportMissingImports]
from SX127x.board_config import BOARD  # pyright: ignore[reportMissingImports]
from SX127x.constants import MODE  # pyright: ignore[reportMissingImports]


class LoRaCrashTX(LoRa):
    def __init__(self):
        BOARD.setup()
        super().__init__(verbose=False)

        self.set_mode(MODE.STDBY)
        self.set_freq(433.0)
        self.set_bw(7)                 # 125 kHz
        self.set_spreading_factor(9)   # SF7
        self.set_coding_rate(1)        # 4/5
        self.set_sync_word(0x34)
        self.set_pa_config(pa_select=1, max_power=0x70, output_power=0x0F)

        print("[INFO] LoRa Crash TX initialized")

    def encrypt_payload(self, data: str):
        iv = get_random_bytes(16) # pyright: ignore[reportUnknownReturnType]
        cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv) # pyright: ignore[reportUnknownReturnType]

        # PKCS7 padding
        data_bytes = data.encode()
        pad_len = 16 - (len(data_bytes) % 16)
        padded = data_bytes + bytes([pad_len] * pad_len)
        encrypted = cipher.encrypt(padded) # pyright: ignore[reportUnknownReturnType]


        # HMAC
        mac = hmac.new(SECRET_KEY, iv + encrypted, hashlib.sha256).digest() # pyright: ignore[reportUnknownReturnType]

        final_packet = iv + mac + encrypted
        return base64.b64encode(final_packet).decode()
 

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)
        secure_payload = self.encrypt_payload(payload_json)


        print("[INFO] Sending crash payload:")
        print(payload_json)

        self.write_payload([ord(c) for c in secure_payload])
        self.set_mode(MODE.TX)

        time.sleep(0.5)
        self.set_mode(MODE.STDBY)

        print("[SUCCESS] Crash payload transmitted")


if __name__ == "__main__":
    lora = LoRaCrashTX()

    # Example crash payload (this will come from main.py later)
    crash_payload = {
        "alert": "VEHICLE_CRASH_DETECTED",
        "node_id": "mesh-trace-node-001",
        "severity": "HIGH",
        "location": {
            "latitude": 18.49831,
            "longitude": 73.94994
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    time.sleep(1)
    lora.send_payload(crash_payload)
