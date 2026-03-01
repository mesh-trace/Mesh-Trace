import sys
import os
import json
import logging
import time
from datetime import datetime, timezone
import base64
import hashlib
import hmac
from Crypto.Cipher import AES  # pyright: ignore[reportMissingImports]
from Crypto.Random import get_random_bytes  # pyright: ignore[reportMissingImports]
from dotenv import load_dotenv  # pyright: ignore[reportMissingImports]
load_dotenv()

logger = logging.getLogger(__name__)

key_hex = os.getenv("LORA_SECRET_KEY")

if not key_hex:
    logger.error("LORA_SECRET_KEY not set in environment")
    raise ValueError("LORA_SECRET_KEY not set in environment")

try:
    SECRET_KEY = bytes.fromhex(key_hex)
    logger.debug("LoRa secret key loaded (%d bytes)", len(SECRET_KEY))
except ValueError as e:
    logger.error("LORA_SECRET_KEY invalid hex: %s", e)
    raise ValueError("LORA_SECRET_KEY must be valid hex")

if len(SECRET_KEY) != 32:
    logger.error("LORA_SECRET_KEY wrong length: %d (expected 32)", len(SECRET_KEY))
    raise ValueError("LORA_SECRET_KEY must be 32 bytes (64 hex characters)")



BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../lora_driver"))
sys.path.append(BASE_DIR)

from SX127x.LoRa import LoRa  # pyright: ignore[reportMissingImports]
from SX127x.board_config import BOARD  # pyright: ignore[reportMissingImports]
from SX127x.constants import MODE  # pyright: ignore[reportMissingImports]


class LoRaCrashTX(LoRa):
    def __init__(self):
        logger.debug("Setting up LoRa board")
        BOARD.setup()
        super().__init__(verbose=False)

        logger.debug("Configuring LoRa radio: freq=433MHz bw=125kHz sf=9 cr=4/5")
        self.set_mode(MODE.STDBY)
        self.set_freq(433.0)
        self.set_bw(7)                 # 125 kHz
        self.set_spreading_factor(9)   # SF9
        self.set_coding_rate(1)        # 4/5
        self.set_sync_word(0x34)
        self.set_pa_config(pa_select=1, max_power=0x70, output_power=0x0F)

        logger.info("LoRa Crash TX initialized")

    def encrypt_payload(self, data: str):
        logger.debug("Encrypting payload: len=%d", len(data))
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
        encoded = base64.b64encode(final_packet).decode()
        logger.debug("Encryption complete: output_len=%d", len(encoded))
        return encoded
 

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)
        logger.info("Sending crash payload via LoRa: node_id=%s severity=%s", payload_dict.get("node_id"), payload_dict.get("severity"))
        logger.debug("Payload JSON: %s", payload_json[:200] + "..." if len(payload_json) > 200 else payload_json)

        try:
            secure_payload = self.encrypt_payload(payload_json)
            logger.debug("Writing %d bytes to LoRa radio", len(secure_payload))

            self.write_payload([ord(c) for c in secure_payload])
            self.set_mode(MODE.TX)
            logger.debug("TX mode set, waiting 0.5s for transmission")

            time.sleep(0.5)
            self.set_mode(MODE.STDBY)

            logger.info("Crash payload transmitted via LoRa successfully")
        except Exception as e:
            logger.error("LoRa transmission failed: %s", e, exc_info=True)
            raise


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
