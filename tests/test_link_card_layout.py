"""Link cards (serial, TCP, MQTT) have one 连接 / 断开 button at the end of their last row and are never
shorter than their rows, at runtime and in the designer."""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication

from app.core.mqtt_card import MqttConfigCard
from app.core.project import ProjectManager
from app.core.serial_card import SerialConfigCard
from app.core.tcp_card import TcpConfigCard
from app.core.widget_registry import registry
from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.designer.property_editor import PropertyEditor
from app.widgets.basic import register_basic_widgets
from app.widgets.chart import register_chart_widgets
from app.widgets.comm import register_comm_widgets
from app.widgets.composite import register_composite_widgets
from app.widgets.display import register_display_widgets
from app.widgets.layout import register_layout_widgets

ROOT = Path(__file__).resolve().parents[1]


def last_row(card, mode):
    """The row the button belongs at: the last field row the display mode shows."""
    if isinstance(card, SerialConfigCard):
        return {"完整": card._parser_w, "简洁": card._baud_w, "单行": card._sl_w}[mode]
    if isinstance(card, TcpConfigCard):
        return {"完整": card._parser_combo, "简洁": card._port_spin}[mode].parentWidget()
    return {"完整": card._parser_combo, "简洁": card._publish_edit}[mode].parentWidget()


class LinkCardLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        for register in (register_basic_widgets, register_chart_widgets, register_comm_widgets,
                         register_composite_widgets, register_display_widgets, register_layout_widgets):
            register()

    def test_every_display_mode_fits_its_default_and_never_squeezes_its_rows(self):
        for card_class, modes in ((SerialConfigCard, ("完整", "简洁", "单行")),
                                  (TcpConfigCard, ("完整", "简洁")), (MqttConfigCard, ("完整", "简洁"))):
            meta = registry.get(card_class.__name__)
            for mode in modes:
                with self.subTest(card=card_class.__name__, mode=mode):
                    card = card_class()
                    self.addCleanup(card.deleteLater)
                    card.set_display_mode(mode)
                    height = card.minimumSizeHint().height()
                    self.assertLessEqual(height, meta.default_height)
                    button = card._sl_conn if mode == "单行" else card._connect_btn
                    self.assertIs(button.parentWidget(), last_row(card, mode))
                    self.assertEqual(button.text(), "连接")
                    # A geometry shorter than the rows is held at their height: nothing overlaps.
                    card.resize(meta.default_width, 60)
                    card.show()
                    self.app.processEvents()
                    self.assertEqual(card.height(), max(60, height))
                    rows = [row for row in card._shown_rows()]
                    for upper, lower in zip(rows, rows[1:]):
                        self.assertLess(upper.geometry().bottom(), lower.geometry().top(), (upper, lower))
                    if mode == "完整":  # the button follows the mode to its new last row
                        card.set_display_mode(modes[1])
                        self.assertIs(card._connect_btn.parentWidget(), last_row(card, modes[1]))
                        self.assertLess(card.minimumSizeHint().height(), height)

    def test_the_designer_keeps_link_cards_as_tall_as_their_rows(self):
        scene = DesignScene()
        self.addCleanup(scene.clear)
        item = CanvasItem("TcpConfigCard", registry.get("TcpConfigCard").get_default_props())
        scene.add_canvas_item(item)
        editor = PropertyEditor()
        self.addCleanup(editor.deleteLater)
        editor._load_item(item)
        full = item.min_height()
        self.assertEqual(full, item._inner_widget.minimumSizeHint().height())
        editor._editors["geo_h"].setValue(100)  # the height row stops at what the rows need
        self.assertEqual(item.rect().height(), full)
        editor._on_geo_changed("geo_h", 100)
        self.assertEqual(item.rect().height(), full)
        editor._editors["displayMode"].setCurrentText("简洁")
        self.assertLess(item.min_height(), full, "fewer rows need less height")
        self.assertEqual(item.rect().height(), full, "and the card keeps its height")
        self.assertEqual(editor._editors["geo_h"].minimum(), item.min_height())
        # A card saved shorter than its rows grows when the project opens; 单行 cards stay as they were.
        with tempfile.TemporaryDirectory() as folder:
            squeezed = Path(folder) / "squeezed.uidp"
            squeezed.write_text(json.dumps({"widgets": [
                {"id": "mqtt", "type": "MqttConfigCard", "properties": {},
                 "geometry": {"x": 0, "y": 0, "w": 380, "h": 120}}]}), encoding="utf-8")
            manager = ProjectManager()
            manager.load_to_scene(scene, str(squeezed))
            mqtt = scene.top_level_canvas_items()[0]
            self.assertEqual(mqtt.rect().height(), mqtt._inner_widget.minimumSizeHint().height())
        manager.load_to_scene(scene, str(ROOT / "examples" / "tutorials" / "04-环境监测站.uidp"))
        serial = next(item for item in scene.top_level_canvas_items() if item.type_name == "SerialConfigCard")
        self.assertEqual(serial.rect().height(), 50)
        manager.load_to_scene(scene, str(ROOT / "demo" / "project.uidp"))  # opening grows to the rows only
        serial = next(item for item in scene.top_level_canvas_items() if item.type_name == "SerialConfigCard")
        self.assertEqual(serial.rect().height(), 48)


if __name__ == "__main__":
    unittest.main()
