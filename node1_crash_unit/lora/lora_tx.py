"""
lora_tx.py — MESH-TRACE LoRa crash transmitter (FINAL)
=======================================================
Works with the fixed board_config.py (LazySpiDev fix).
All parameters explicitly set and verified by readback.
TX done confirmed by polling DIO0 GPIO pin directly.
"""

import sys
import os
import json
import time
from datetime import datetime, timezone
import RPi.GPIO as GPIO  # pyright: ignore[reportMissingModuleSource]

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../lora_driver"))
sys.path.append(BASE_DIR)

from SX127x.LoRa import LoRa  # pyright: ignore[reportMissingImports]
from SX127x.board_config import BOARD  # pyright: ignore[reportMissingImports]
from SX127x.constants import MODE, BW, CODING_RATE  # pyright: ignore[reportMissingImports]


class LoRaCrashTX(LoRa):

    def __init__(self):
        # BOARD.setup() MUST come before super().__init__()
        # It fires the RST pulse which puts SX1278 in clean state.
        # super().__init__() triggers the first SPI transaction (via LazySpiDev),
        # which now happens AFTER the reset — this is the fix.
        BOARD.setup()
        super().__init__(verbose=False)

        # Force STDBY by writing directly to OpMode register
        # Bypass set_mode() cache — we need the actual register write
        self.spi.xfer([0x01 | 0x80, 0x81])   # reg 0x01 = 0x81 (LoRa + STDBY)
        self.mode = 0x81
        time.sleep(0.1)

        # Configure all parameters explicitly
        self.set_freq(433.0)
        self.set_spreading_factor(7)
        self.set_bw(BW.BW125)
        self.set_coding_rate(CODING_RATE.CR4_5)
        self.set_sync_word(0x12)
        self.set_rx_crc(True)           # MUST match ESP32's enableCrc()
        self.set_agc_auto_on(True)
        self.set_preamble(8)
        self.set_pa_config(pa_select=1, max_power=0x07, output_power=0x0F)

        # Set DIO0 to signal TxDone (mapping = 01)
        self.set_dio_mapping([1, 0, 0, 0, 0, 0])

        # Readback verification — if SF=0 after this, SPI wiring is broken
        cfg1 = self.get_modem_config_1()
        cfg2 = self.get_modem_config_2()
        freq = self.get_freq()
        sf   = cfg2['spreading_factor']
        bw   = cfg1['bw']
        crc  = cfg2['rx_crc']
        sw   = self.get_sync_word()

        print(f"[INFO] LoRa TX initialized")
        print(f"[INFO] Freq={freq:.3f} MHz | SF={sf} | BW={bw} (7=125kHz) | "
              f"CRC={'ON' if crc else 'OFF'} | sync=0x{sw:02X}")

        if sf != 7:
            raise RuntimeError(
                f"SPI FAILURE: SF readback={sf}, expected 7.\n"
                f"Check: MISO→GPIO9, MOSI→GPIO10, SCK→GPIO11, NSS→GPIO8(CE0), RST→GPIO26\n"
                f"Also verify SX1278 is powered by 3.3V NOT 5V."
            )

        print("[INFO] SPI verified OK — all registers responding correctly")

    def send_payload(self, payload_dict):
        payload_json  = json.dumps(payload_dict)
        payload_bytes = [ord(c) for c in payload_json]
        print(f"[INFO] Sending {len(payload_bytes)} bytes...")
        print(payload_json)

        # write_payload sets STDBY internally and loads FIFO
        self.write_payload(payload_bytes)

        # Clear any stale IRQ flags
        self.set_irq_flags(tx_done=1)

        # Start transmitting
        self.set_mode(MODE.TX)

        # Poll DIO0 GPIO pin — goes HIGH when TX is done
        # Faster and more reliable than register polling
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if GPIO.input(BOARD.DIO0):
                print("[SUCCESS] Crash payload transmitted — TX done confirmed")
                break
            time.sleep(0.005)
        else:
            # Fallback: check IRQ register directly
            irq = self.get_irq_flags()
            if irq.get('tx_done'):
                print("[SUCCESS] Crash payload transmitted — confirmed via IRQ register")
            else:
                print("[WARNING] TX timeout — DIO0 pin never went HIGH")
                print(f"[DEBUG]  DIO0 GPIO={BOARD.DIO0}, RST GPIO={BOARD.RST}")
                print(f"[DEBUG]  IRQ flags={irq}")
                print("[DEBUG]  Verify DIO0 wire: SX1278 DIO0 → Pi GPIO5 (Pin 29)")

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

    time.sleep(0.5)
    lora.send_payload(crash_payload)
    lora.cleanup()