"""The Modbus slave of a link card in the 从站 role: its replies, log lines and slave messages, how it frames
requests and what it sends at the start, as tests/data/modbus_slave_vectors.json (shared with FluentHMI Studio)
has them."""
import json
from pathlib import Path
import unittest

from app.core.modbus_slave import ModbusSlave, SlaveStore, hex_text, request_framer

VECTORS = json.loads((Path(__file__).resolve().parent / "data" / "modbus_slave_vectors.json")
                     .read_text(encoding="utf-8"))


def _bytes(text):
    return bytes.fromhex(text.replace(" ", ""))


class ModbusSlaveVectorTests(unittest.TestCase):
    def test_requests(self):
        for case in VECTORS["requests"]:
            with self.subTest(case["name"]):
                store = SlaveStore(case["areas"], case.get("init", ""))
                slave = ModbusSlave(case["framing"], case["slave"], case["exceptions"], store)
                for step in case["steps"]:
                    reply, log, emits = slave.request(_bytes(step["in"]))
                    self.assertEqual(hex_text(reply) if reply else None, step["out"], step["in"])
                    self.assertEqual(log, step["log"], step["in"])
                    self.assertEqual(emits, step["emit"], step["in"])
                for key, value in case["after"].items():
                    self.assertEqual(store.get(key[:2], int(key[2:])), value, key)

    def test_streams(self):
        for case in VECTORS["streams"]:
            with self.subTest(case["name"]):
                framer = request_framer("modbus" if case["framing"] == "rtu" else "modbus_tcp")
                frames = []
                for chunk in case["chunks"]:
                    frames += framer.flush() if chunk == "idle" else framer.frames(_bytes(chunk))
                self.assertEqual([hex_text(frame) for frame in frames], case["frames"])

    def test_start(self):
        for case in VECTORS["start"]:
            with self.subTest(case["name"]):
                store = SlaveStore(case["areas"], case["init"])
                self.assertEqual(store.start_messages(case["slave"]), case["emit"])


if __name__ == "__main__":
    unittest.main()
