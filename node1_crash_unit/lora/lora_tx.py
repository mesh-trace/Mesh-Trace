import sys
import os
import json
import logging
import time
from datetime import datetime, timezone

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../lora_driver"))
sys.path.append(BASE_DIR)

if not os.path.exists(BASE_DIR):
    raise FileNotFoundError(
        f"LoRa driver not found at: {BASE_DIR}\n"
        "Install the SX127x driver at that path or update BASE_DIR in lora_tx.py"
    )

from SX127x.LoRa import LoRa  # pyright: ignore[reportMissingImports]
from SX127x.board_config import BOARD  # pyright: ignore[reportMissingImports]
from SX127x.constants import MODE  # pyright: ignore[reportMissingImports]

# ---------------------------------------------------------------------------
# Import config — works in BOTH modes:
#   1. Run as part of the package:  python3 -m node1_crash_unit.main
#      → relative import succeeds normally
#   2. Run directly as a script:    python3 lora_tx.py
#      → relative import fails (no parent package), so we fall back to
#        loading config.py from the parent directory using importlib
# ---------------------------------------------------------------------------
try:
    from ..config import LORA_FREQUENCY, LORA_POWER, LORA_SPREADING_FACTOR, LORA_BANDWIDTH, LORA_CODING_RATE
except ImportError:
    import importlib.util
    _config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config.py"))
    _spec = importlib.util.spec_from_file_location("config", _config_path)
    _config = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_config)
    LORA_FREQUENCY        = _config.LORA_FREQUENCY
    LORA_POWER            = _config.LORA_POWER
    LORA_SPREADING_FACTOR = _config.LORA_SPREADING_FACTOR
    LORA_BANDWIDTH        = _config.LORA_BANDWIDTH
    LORA_CODING_RATE      = _config.LORA_CODING_RATE

logger = logging.getLogger(__name__)


class LoRaCrashTX(LoRa):
    def __init__(self):
        BOARD.setup()
        super().__init__(verbose=False)

        self.set_mode(MODE.STDBY)
        self.set_freq(LORA_FREQUENCY)

        # ----------------------------------------------------------------
        # Radio parameters — ALL four must match exactly on the ESP32 side.
        # Values come from config.py (loaded at module level above, works
        # whether run as a package or directly with python3 lora_tx.py).
        #   LORA_SPREADING_FACTOR = 7   (SF7)
        #   LORA_BANDWIDTH        = 125000  (125 kHz  → BW_125)
        #   LORA_CODING_RATE      = 5   (4/5)
        #   Sync word             = 0x12 (private network, must match ESP32)
        # ----------------------------------------------------------------

        # Map bandwidth Hz value to SX127x register constant
        BW_MAP = {
            7800:   0,  10400: 1, 15600:  2, 20800: 3,
            31250:  4,  41700: 5, 62500:  6, 125000: 7,
            250000: 8, 500000: 9
        }
        bw_reg = BW_MAP.get(LORA_BANDWIDTH, 7)   # default 125 kHz
        self.set_bw(bw_reg)
        self.set_spreading_factor(LORA_SPREADING_FACTOR)
        self.set_coding_rate(LORA_CODING_RATE)
        self.set_sync_word(0x12)    # 0x12 = private LoRa network (must match ESP32)

        self.set_pa_config(pa_select=1, max_power=0x70, output_power=0x0F)

        logger.info(
            "LoRa Crash TX initialized: freq=%.1f MHz  SF=%d  BW=%d Hz  CR=4/%d  sync=0x12",
            LORA_FREQUENCY, LORA_SPREADING_FACTOR, LORA_BANDWIDTH, LORA_CODING_RATE
        )

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)

        logger.info("Sending LoRa crash payload: %d bytes", len(payload_json))
        logger.debug("LoRa payload: %s", payload_json)

        # Write payload bytes to FIFO buffer, then trigger TX
        self.write_payload([ord(c) for c in payload_json])

        # Clear all IRQ flags before TX so we can detect TxDone cleanly
        self.set_irq_flags(tx_done=1)

        self.set_mode(MODE.TX)

        # Wait for TxDone IRQ flag — poll register 0x12 bit 3
        # Timeout = 5 seconds (well above worst-case SF12 airtime)
        timeout = time.time() + 5.0
        while True:
            irq = self.get_irq_flags()
            if irq.get("tx_done"):
                break
            if time.time() > timeout:
                logger.error("LoRa TX timeout — TxDone flag never set")
                break
            time.sleep(0.01)

        # Return to standby and clear flags
        self.set_mode(MODE.STDBY)
        self.set_irq_flags(tx_done=1)

        logger.info("LoRa crash payload transmitted successfully")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

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

    time.sleep(1)
    lora.send_payload(crash_payload)