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
    from ..config import LORA_FREQUENCY, LORA_POWER
except ImportError:
    import importlib.util
    _config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../config.py"))
    _spec = importlib.util.spec_from_file_location("config", _config_path)
    _config = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_config)
    LORA_FREQUENCY = _config.LORA_FREQUENCY
    LORA_POWER     = _config.LORA_POWER

logger = logging.getLogger(__name__)


class LoRaCrashTX(LoRa):
    def __init__(self):
        BOARD.setup()
        super().__init__(verbose=False)

        self.set_mode(MODE.STDBY)
        self.set_freq(LORA_FREQUENCY)

        self.set_pa_config(pa_select=1, max_power=0x70, output_power=0x0F)

        logger.info("LoRa Crash TX initialized: freq=%.1f MHz", LORA_FREQUENCY)

    def send_payload(self, payload_dict):
        payload_json = json.dumps(payload_dict)

        logger.info("Sending LoRa crash payload: %d bytes", len(payload_json))
        logger.debug("LoRa payload: %s", payload_json)

        self.write_payload([ord(c) for c in payload_json])
        self.set_mode(MODE.TX)

        time.sleep(0.5)
        self.set_mode(MODE.STDBY)

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