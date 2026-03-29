import sys
import os
import json
import time
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../lora_driver"))
sys.path.append(BASE_DIR)

from SX127x.LoRa import LoRa                    # pyright: ignore[reportMissingImports]
from SX127x.board_config import BOARD           # pyright: ignore[reportMissingImports]
from SX127x.constants import MODE, BW, CODING_RATE  # pyright: ignore[reportMissingImports]

# ============================================================
# CRITICAL: ALL parameters below MUST match esp32.ino exactly
#   esp32.ino: 433 MHz, SF7, BW125kHz, CR4/5, sync=0x12, CRC ON
# ============================================================

LORA_FREQUENCY       = 433.0   # MHz  — matches #define LORA_FREQ 433E6
LORA_SF              = 7       #       — matches #define LORA_SF 7
LORA_SYNC_WORD       = 0x12    #       — matches #define LORA_SYNC_WORD 0x12
# BW.BW125 = index 7 in SX127x lib = 125 kHz — matches #define LORA_BW 125E3
# CODING_RATE.CR4_5  = CR 4/5         — matches #define LORA_CR 5


class LoRaCrashTX(LoRa):
    def __init__(self):
        BOARD.setup()
        super().__init__(verbose=False)

        # Step 1: Standby before configuring
        self.set_mode(MODE.STDBY)
        time.sleep(0.1)

        # Step 2: Frequency — MUST match ESP32
        self.set_freq(LORA_FREQUENCY)

        # Step 3: Modem config — MUST all match ESP32
        self.set_spreading_factor(LORA_SF)       # SF7
        self.set_bw(BW.BW125)                    # 125 kHz  ← was MISSING before
        self.set_coding_rate(CODING_RATE.CR4_5)  # CR 4/5   ← was MISSING before
        self.set_sync_word(LORA_SYNC_WORD)       # 0x12     ← was MISSING before

        # Step 4: CRC ON — MUST match ESP32 (which calls LoRa.enableCrc())
        self.set_rx_crc(True)                    # ← was MISSING before

        # Step 5: TX power
        self.set_pa_config(pa_select=1, max_power=0x70, output_power=0x0F)

        # Step 6: Preamble length — default is 8, must match both sides
        self.set_preamble(8)

        print("[INFO] LoRa Crash TX initialized")
        print(f"[INFO] Config: {LORA_FREQUENCY} MHz | SF{LORA_SF} | BW125kHz | CR4/5 | sync=0x{LORA_SYNC_WORD:02X} | CRC=ON")

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)
        payload_bytes = [ord(c) for c in payload_json]
        payload_len = len(payload_bytes)

        print(f"[INFO] Sending crash payload ({payload_len} bytes):")
        print(payload_json)

        # Make sure we are in STDBY before writing payload
        self.set_mode(MODE.STDBY)
        time.sleep(0.05)

        # Write payload to FIFO
        self.write_payload(payload_bytes)

        # Trigger transmission
        self.set_mode(MODE.TX)

        # -------------------------------------------------------
        # Wait long enough for the packet to finish transmitting.
        # Time-on-air at SF7 / BW125 / CR4/5 for ~200 bytes ≈ 400ms
        # We wait 2s to be safe — do NOT cut this short.
        # -------------------------------------------------------
        wait_s = max(2.0, payload_len * 0.010)
        print(f"[INFO] Waiting {wait_s:.1f}s for TX to complete...")
        time.sleep(wait_s)

        # Return to standby after TX
        self.set_mode(MODE.STDBY)

        print("[SUCCESS] Crash payload transmitted")

    def cleanup(self):
        """Call this before exiting to put radio to sleep."""
        self.set_mode(MODE.SLEEP)
        BOARD.teardown()


if __name__ == "__main__":
    lora = LoRaCrashTX()

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

    # Give radio time to settle after init before first TX
    time.sleep(1)

    lora.send_payload(crash_payload)
    lora.cleanup()