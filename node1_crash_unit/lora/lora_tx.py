import sys
import os
import json
import time
from datetime import datetime, timezone

sys.path.append(os.path.abspath("../lora_driver"))

from SX127x.LoRa import LoRa
from SX127x.board_config import BOARD
from SX127x.constants import MODE


class LoRaCrashTX(LoRa):
    def __init__(self):
        BOARD.setup()
        super().__init__(verbose=False)

        self.set_mode(MODE.STDBY)
        self.set_freq(433.0)

        self.set_pa_config(pa_select=1, max_power=0x70, output_power=0x0F)

        print("[INFO] LoRa Crash TX initialized")

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)

        print("[INFO] Sending crash payload:")
        print(payload_json)

        self.write_payload([ord(c) for c in payload_json])
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
