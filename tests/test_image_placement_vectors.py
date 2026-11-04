"""ImageDisplay places its picture as tests/data/image_placement_vectors.json says, which FluentHMI Studio's image
widget is checked against too, so a picture lands in the same place in either app."""
import json
from pathlib import Path
import unittest

from PyQt5.QtCore import QPointF

from app.core.image_runtime import image_transform

VECTORS = json.loads((Path(__file__).resolve().parent / "data" / "image_placement_vectors.json")
                     .read_text(encoding="utf-8"))


class ImagePlacementVectorTests(unittest.TestCase):
    def test_picture_corners_land_where_the_shared_vectors_say(self):
        tolerance = VECTORS["tolerance"]
        for index, case in enumerate(VECTORS["vectors"]):
            (box_w, box_h), (img_w, img_h) = case["box"], case["image"]
            transform = image_transform(box_w, box_h, img_w, img_h, case["rotation"],
                                        case["mirrorH"], case["mirrorV"], case["scaleMode"])
            corners = [transform.map(QPointF(x, y))
                       for x, y in ((0, 0), (img_w, 0), (img_w, img_h), (0, img_h))]
            with self.subTest(vector=index):
                for point, (x, y) in zip(corners, case["corners"]):
                    self.assertTrue(abs(point.x() - x) <= tolerance and abs(point.y() - y) <= tolerance,
                                    f"vector {index}: {(point.x(), point.y())} != {(x, y)}")


if __name__ == "__main__":
    unittest.main()
