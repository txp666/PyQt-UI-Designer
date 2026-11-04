"""JSON send mode matches tests/data/json_command_vectors.json, which FluentHMI Studio's encoder is checked
against too, so both apps send the same bytes for the same .uidp."""
import json
from pathlib import Path
import unittest

from app.core.command_runtime import json_command

VECTORS = json.loads((Path(__file__).parent / "data" / "json_command_vectors.json").read_text(encoding="utf-8"))


class JsonCommandVectorTests(unittest.TestCase):
    def test_encoded_bytes_and_errors_match_the_shared_vectors(self):
        for case in VECTORS["cases"]:
            with self.subTest(case["name"]):
                if "error" in case:
                    with self.assertRaises(ValueError) as caught:
                        json_command(case["props"], case["value"])
                    self.assertEqual(str(caught.exception), case["error"])
                else:
                    self.assertEqual(json_command(case["props"], case["value"]), case["out"].encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
