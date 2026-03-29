"""
lora_tx.py  —  MESH-TRACE LoRa Crash Transmitter (Pi side)
=============================================================
ROOT CAUSE OF RX FAILURE (confirmed by library analysis):
  The SX127x library default is CRC = OFF.
  The ESP32 Arduino LoRa library has enableCrc() called in setup().
  When ESP32 RX has CRC enabled but the incoming packet has NO CRC,
  the Arduino LoRa library silently discards the packet — no error,
  no log, just dropped. This was the entire problem.

FIX SUMMARY (3 changes only, minimal and targeted):
  1. self.set_rx_crc(True)   ← THE fix. Enables CRC on TX packet.
  2. self.set_agc_auto_on(True) ← Improves RX sensitivity, recommended.
  3. Poll tx_done IRQ flag instead of blind sleep for reliable TX confirm.

All other parameters (SF7, BW125, CR4/5, sync=0x12, freq=433) are
already correct because the chip's power-on defaults match ESP32 defaults.
DO NOT add unnecessary set_bw / set_coding_rate calls — they risk
corrupting the register state if called in wrong mode.
"""

import sys
import os
import json
import time
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../lora_driver"))
sys.path.append(BASE_DIR)

from SX127x.LoRa import LoRa                        # pyright: ignore
from SX127x.board_config import BOARD               # pyright: ignore
from SX127x.constants import MODE, BW, CODING_RATE  # pyright: ignore


class LoRaCrashTX(LoRa):

    def __init__(self):
        BOARD.setup()
        super().__init__(verbose=False)
    # After super().__init__, self.mode cache = 0x80 (SLEEP)
    # but we must FORCE STDBY via direct register write, bypassing cache

    # Force STDBY directly — bypass the cache check in set_mode()
        self.spi.xfer([0x01 | 0x80, 0x81])   # write reg 0x01 = 0x81 (LoRa STDBY)
        self.mode = 0x81                       # update cache to match
        time.sleep(0.1)                        # let radio settle

    # Now safe to configure all registers
        self.set_freq(433.0)
        self.set_spreading_factor(7)
        self.set_bw(BW.BW125)
        self.set_coding_rate(CODING_RATE.CR4_5)
        self.set_sync_word(0x12)
        self.set_rx_crc(True)                  # THE CRC FIX
        self.set_agc_auto_on(True)
        self.set_preamble(8)
        self.set_pa_config(pa_select=1, max_power=0x07, output_power=0x0F)
   
    # Read back to verify — if SF still shows 0, it's an SPI wiring issue
        cfg2 = self.get_modem_config_2()
        cfg1 = self.get_modem_config_1()
        print(f"[INFO] Freq={self.get_freq():.3f} MHz | SF={cfg2['spreading_factor']} | "
              f"BW={cfg1['bw']} | CRC={'ON' if cfg2['rx_crc'] else 'OFF'} | "
              f"sync=0x{self.get_sync_word():02X}")
    

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)
        payload_bytes = [ord(c) for c in payload_json]
        payload_len = len(payload_bytes)

        print(f"[INFO] Sending crash payload ({payload_len} bytes):")
        print(payload_json)

        # write_payload() internally calls set_mode(STDBY) and sets FIFO ptr
        self.write_payload(payload_bytes)

        # Clear any stale TX done flag before transmitting
        self.set_irq_flags(tx_done=1)

        # Start transmission
        self.set_mode(MODE.TX)

        # FIX 3 — Poll the TxDone IRQ flag instead of blind sleep.
        # Time-on-air for 200 bytes @ SF7/BW125/CR4/5 ≈ 350ms.
        # We poll for up to 5 seconds to be safe.
        print("[INFO] Waiting for TX done...")
        deadline = time.time() + 5.0
        tx_confirmed = False
        while time.time() < deadline:
            irq = self.get_irq_flags()
            if irq.get('tx_done'):
                tx_confirmed = True
                break
            time.sleep(0.01)

        if tx_confirmed:
            print("[SUCCESS] Crash payload transmitted (TX done confirmed)")
        else:
            print("[WARNING] TX done flag never set — check radio hardware/wiring")

        # Clear TX done flag and return to standby
        self.clear_irq_flags(TxDone=1)
        self.set_mode(MODE.STDBY)

    def cleanup(self):
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

    time.sleep(0.5)  # short settle time after init
    lora.send_payload(crash_payload)
    lora.cleanup()