import time
import json
from SX127x.LoRa import LoRa  # pyright: ignore[reportMissingImports]
from SX127x.board_config import BOARD  # pyright: ignore[reportMissingImports]
from SX127x.constants import MODE  # pyright: ignore[reportMissingImports]

BOARD.setup()

class LoRaSender(LoRa):
    def __init__(self):
        super().__init__(verbose=False)
        self.set_mode(MODE.SLEEP)
        self.set_dio_mapping([0]*6)

        self.set_freq(868.0)
        self.set_pa_config(pa_select=1)
        self.set_spreading_factor(7)
        self.set_bw(7)
        self.set_coding_rate(5)

        self.set_mode(MODE.STDBY)

    def send(self, payload: dict):
        message = json.dumps(payload)
        self.write_payload([ord(c) for c in message])
        self.set_mode(MODE.TX)
        time.sleep(0.5)
        self.set_mode(MODE.STDBY)
        print("[LoRa] Payload sent:", message)


if __name__ == "__main__":
    sender = LoRaSender()

    crash_payload = {
        "node_id": "mesh-trace-node-001",
        "event": "crash",
        "lat": 18.4983,
        "lon": 73.9499,
        "severity": "HIGH",
        "confidence": 0.95
    }

    sender.send(crash_payload)
    BOARD.teardown()
