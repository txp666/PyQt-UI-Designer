"""Industrial catalog registration, feedback and standalone binding contracts."""
import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt5.QtWidgets import QApplication
from PyQt5 import sip
from app.core.industrial_runtime import INDUSTRIAL_CATALOG
from app.core.data_binding import BIND_PROPERTIES
from app.core.widget_registry import registry
from app.widgets.industrial import register_industrial_widgets
from tests import test_preview_export_parity as parity


class IndustrialTests(unittest.TestCase):
    run_both = parity.PreviewExportParityTests.run_both

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_industrial_widgets()

    def test_all_catalog_types_register_and_validate_feedback(self):
        from app.designer.canvas_item import CanvasItem
        self.assertEqual(len({spec["type"] for spec in INDUSTRIAL_CATALOG}), len(INDUSTRIAL_CATALOG))
        from app.widgets.industrial import ALL_INDUSTRIAL
        categories = list(dict.fromkeys(meta.category.value for meta in ALL_INDUSTRIAL))
        self.assertEqual(categories[-3:], ["汽车电子", "电子 DIY", "嵌入式"])
        for spec in INDUSTRIAL_CATALOG:
            with self.subTest(kind=spec["type"]):
                meta = registry.get(spec["type"])
                self.assertIsNotNone(meta)
                self.assertEqual(BIND_PROPERTIES[spec["type"]], "value")
                item = CanvasItem(spec["type"], meta.get_default_props())
                widget = item._inner_widget
                self.assertEqual(item.to_dict()["type"], spec["type"])
                widget.set_bound(True)
                self.assertEqual(widget._feedback, "pending")
                widget.set_value(spec["value"])
                self.assertEqual(widget._feedback, "normal")
                widget.set_value("bad")
                self.assertEqual(widget._feedback, "abnormal")
                widget.set_value(float("nan"))
                self.assertEqual(widget._feedback, "abnormal")
                sip.delete(item)

    def test_key_json_and_hex_feedback_and_expression_parity(self):
        widgets = [
            {"id": "key", "type": "FlowMeter", "binding": {
                "parseMode": "键值匹配", "key": "flow", "expression": "value / 2"}},
            {"id": "json", "type": "Thermometer", "binding": {
                "parseMode": "JSON路径", "jsonPath": "sensor.temp", "expression": "value + 1"}},
            {"id": "hex", "type": "Tank", "binding": {
                "parseMode": "HEX字节提取", "dataType": "uint8", "expression": "value * 2"}},
        ]
        self.run_both(widgets, '''
            if 'app.core.data_binding' in sys.modules:
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(json.loads(os.environ['PROJECT_WIDGETS']))
                bindingEngine.start()
            assert all(w._feedback == 'pending' for w in widgets.values())
            serial.dataReceived.emit({'flow': 64, 'sensor': {'temp': 24}})
            serial.rawReceived.emit(bytes([30]))
            assert [widgets[k]._value for k in ('key', 'json', 'hex')] == [32, 25, 60]
            serial.dataReceived.emit({'flow': 'bad', 'sensor': {'temp': float('nan')}})
            assert widgets['key']._feedback == 'abnormal'
            assert widgets['json']._feedback == 'abnormal'
        ''')

    def test_boolean_coils_and_unbound_runtime_wait_for_data(self):
        widgets = [{"id": "coil", "type": "Pump", "binding": {
            "parseMode": "Modbus", "mbArea": "线圈", "mbRegIndex": 0, "mbSlaveFilter": 1}},
            {"id": "unbound", "type": "PressureGauge"}]
        self.run_both(widgets, '''
            if 'app.core.data_binding' in sys.modules:
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(json.loads(os.environ['PROJECT_WIDGETS']))
                bindingEngine.start()
            assert widgets['unbound']._feedback == 'pending'
            assert widgets['unbound']._value is None
            for bit in (True, False):
                serial.dataReceived.emit({'fc': 1, 'slave': 1, 'co0': bit})
                assert widgets['coil']._feedback == 'normal'
                assert widgets['coil']._value == int(bit)
            assert widgets['unbound']._feedback == 'pending'
        ''')

    def test_discrete_validation_in_preview_and_export(self):
        widgets = [
            {"id": "motor", "type": "Motor", "properties": {"feedbackMode": "运行位"},
                "binding": {"parseMode": "键值匹配", "key": "run"}},
            {"id": "cylinder", "type": "Cylinder", "properties": {"feedbackMode": "端位状态"},
                "binding": {"parseMode": "键值匹配", "key": "position"}},
            {"id": "lights", "type": "StackLight", "properties": {"minimum": 100, "maximum": 200},
                "binding": {"parseMode": "键值匹配", "key": "lights"}},
        ]
        self.run_both(widgets, '''
            if 'app.core.data_binding' in sys.modules:
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(json.loads(os.environ['PROJECT_WIDGETS']))
                bindingEngine.start()
            serial.dataReceived.emit({'run': True, 'position': 0, 'lights': 7})
            assert widgets['motor']._feedback == 'normal'
            assert widgets['lights']._feedback == 'normal'
            serial.dataReceived.emit({'run': 2, 'position': 3, 'lights': 8})
            for key in ('motor', 'cylinder', 'lights'):
                assert widgets[key]._feedback == 'abnormal'
        ''')

    def test_shared_bit_profile_edit_rename_undo_and_project_roundtrip(self):
        import json
        import tempfile
        from pathlib import Path
        from app.core.project import ProjectManager
        from app.designer.canvas_item import CanvasItem
        from app.view.designer_interface import DesignerInterface
        editor = DesignerInterface()
        self.addCleanup(lambda: sip.delete(editor) if not sip.isdeleted(editor) else None)
        manager = ProjectManager()
        editor.set_project_source(lambda: manager.current)
        for identity, kind in (("word", "StatusWordPanel"), ("timing", "DigitalTimingChart")):
            editor.scene.add_canvas_item(CanvasItem(kind, {}, widget_id=identity))
        editor._record()
        panel = editor._prop_editor
        panel._load_item(editor.scene.get_item_by_id("word"))
        card = panel._bit_profile_editor
        card.width_combo.setCurrentText("16")
        card.table.item(3, 0).setText("Ready & fault")
        card.table.item(3, 1).setText("#12aBcD")
        editor.scene.get_item_by_id("word").set_property("value", 0x9000)
        card.name_edit.setText("plc")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bits.uidp"
            manager.save_from_scene(editor.scene, str(path))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(set(data["bitProfiles"]), {"plc"})
            self.assertEqual(data["bitProfiles"]["plc"]["width"], 16)
            self.assertEqual(data["bitProfiles"]["plc"]["bits"][3], {"name": "Ready & fault", "color": "#12aBcD"})
            self.assertTrue(all(item.properties["bitProfile"] == "plc" for item in editor.scene.all_canvas_items()))
            editor._record()
            editor.undo()
            self.assertEqual(editor.scene.bit_profiles, {})
            editor.redo()
            self.assertEqual(editor.scene.get_item_by_id("word")._inner_widget._value, 0x9000)
            manager.load_to_scene(editor.scene, str(path))
            self.assertEqual(manager.current.bit_profiles, data["bitProfiles"])
        panel._load_item(editor.scene.get_item_by_id("word"))
        card = panel._bit_profile_editor
        card._add()
        keys = set(manager.current.bit_profiles)
        panel._editors["bitProfile"].setCurrentText("plc")
        self.assertEqual(set(manager.current.bit_profiles), keys)
        self.assertEqual(editor.scene.get_item_by_id("word").properties["bitProfile"], "plc")

    def test_signal_structured_feedback_and_sampling_in_real_preview_and_export(self):
        from app.core.bit_profiles import default_bit_profile
        profile = default_bit_profile(16)
        definitions = [
            ("word", "StatusWordPanel", {"bitProfile": "plc"}, {"parseMode": "键值匹配", "key": "word"}),
            ("timing", "DigitalTimingChart", {"bitProfile": "plc"}, {"parseMode": "JSON路径", "jsonPath": "sensor.word"}),
            ("encoder", "RotaryEncoder", {"pulsesPerTurn": 4}, {"parseMode": "键值匹配", "key": "count"}),
            ("cells", "BmsCellMatrix", {}, {"parseMode": "键值匹配", "key": "cells"}),
            ("supply", "DcPowerSupply", {}, {"parseMode": "JSON路径", "jsonPath": "bench.power"}),
            ("valve", "DirectionalValve", {}, {"parseMode": "键值匹配", "key": "valve"}),
        ]
        widgets = [{"id": identity, "type": kind, "properties": props, "binding": binding,
                    "geometry": {"x": (index%3)*350, "y": (index//3)*230, "w": 340, "h": 220}}
                   for index, (identity, kind, props, binding) in enumerate(definitions)]
        self.run_both(widgets, '''
            if 'app.core.data_binding' in sys.modules:
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(json.loads(os.environ['PROJECT_WIDGETS']))
                bindingEngine.start()
            timing, encoder = widgets['timing'], widgets['encoder']
            assert timing._history == []
            serial.dataReceived.emit({'word': 0xA500, 'sensor': {'word': 0xA500}, 'count': -1,
                'cells': [3.6, 3.7, -0.1], 'bench': {'power': {'voltage': -12, 'current': .125, 'mode': ' cc '}}, 'valve': 1})
            assert widgets['word']._profile()['width'] == 16
            assert widgets['word']._value == 0xA500
            assert timing._history == [0xA500]
            assert encoder._value == -1 and encoder._encoder_direction is None
            assert widgets['cells']._value == [3.6, 3.7, -0.1]
            assert widgets['supply']._value['mode'] == 'CC'
            for count, direction in ((3, 1), (3, 0), (-2, -1)):
                serial.dataReceived.emit({'count': count})
                assert encoder._encoder_direction == direction
            serial.dataReceived.emit({'count': None, 'sensor': {'word': None}})
            assert encoder._feedback == 'abnormal' and encoder._encoder_previous is None
            assert timing._history == [0xA500, None]
            serial.dataReceived.emit({'count': 5, 'sensor': {'word': 0xA500}})
            assert encoder._encoder_direction is None
            serial.dataReceived.emit({'sensor': {'word': 0xA500}})
            assert timing._history == [0xA500, None, 0xA500, 0xA500]
            before = list(timing._history)
            timing.hide()
            timing.show()
            timing._refresh()
            timing.set_bit_profiles(timing._bit_profiles)
            assert timing._history == before
            for value in range(40):serial.dataReceived.emit({'sensor': {'word': value}})
            assert timing._history == list(range(8, 40))
            serial.dataReceived.emit({'cells': [], 'bench': {'power': {'voltage': True, 'current': 1, 'mode': 'CV'}}})
            assert widgets['cells']._feedback == widgets['supply']._feedback == 'abnormal'
            serial.dataReceived.emit({'cells': [1, float('nan')], 'count': 2**53})
            assert widgets['cells']._feedback == encoder._feedback == 'abnormal'
            serial.dataReceived.emit({'cells': [4.0]*100, 'bench': {'power': {'voltage': 2, 'current': -1, 'mode': 'cv'}}, 'count': -(2**53-1), 'valve': 2})
            assert len(widgets['cells']._value) == 100
            assert encoder._value == -(2**53-1)
            assert widgets['supply']._value['mode'] == 'CV'
            assert widgets['valve']._value == 2
        ''', bit_profiles={"plc": profile})

    def test_all_types_bind_and_poll_in_real_preview_and_standalone(self):
        widgets = []
        for index, spec in enumerate(INDUSTRIAL_CATALOG):
            widgets.append({"id": f"i{index}", "type": spec["type"],
                "geometry": {"x": (index % 6) * 180, "y": (index // 6) * 125, "w": 175, "h": 120},
                "binding": ({"parseMode": "JSON路径", "jsonPath": spec["type"]} if spec['mode'] in ('cells','supply') else
                            {"parseMode": "Modbus", "mbRegIndex": index,
                             "mbSlaveFilter": 1, "expression": "value * 0.5"})})
        self.run_both(widgets, '''
            if 'app.core.data_binding' in sys.modules:
                from app.core.data_binding import bindingEngine
                bindingEngine.load_bindings_from_project(json.loads(os.environ['PROJECT_WIDGETS']))
                bindingEngine.start()
            count = len(widgets)
            industrial = [widgets['i' + str(i)] for i in range(count)]
            assert all(w._feedback == 'pending' for w in industrial)
            data = {'fc': 3, 'slave': 1}
            data.update({'hr' + str(i): 2 for i in range(count)})
            data.update({w.spec['type']: w.spec['value'] for w in industrial if w.spec['mode'] in ('cells','supply')})
            serial.dataReceived.emit(data)
            assert all(w._value == 1 for w in industrial if w.spec['mode'] not in ('cells','supply'))
            assert all(w._value == w.spec['value'] for w in industrial if w.spec['mode'] in ('cells','supply'))
            needs = window._modbus_poller._needs()
            assert {entry[0] for entry in needs} == {'i' + str(i) for i,w in enumerate(industrial) if w.spec['mode'] not in ('cells','supply')}, needs
            gpio_index = next(i for i, w in enumerate(industrial) if w.spec['type'] == 'GpioBank')
            serial.dataReceived.emit({'fc': 3, 'slave': 1, 'hr' + str(gpio_index): 2 * 0x96})
            gpio = industrial[gpio_index]
            assert [gpio._drivers()['bit' + str(bit)] for bit in range(8)] == [0, 1, 1, 0, 1, 0, 0, 1]
            for index, w in enumerate(industrial):
                address = 'hr' + str(index)
                if w.spec['mode'] == 'byte':
                    maximum = w.spec['maximum']
                    serial.dataReceived.emit({'fc': 3, 'slave': 1, address: (maximum + 1) * 2})
                    assert w._feedback == 'abnormal'
                if w.spec['mode'] == 'flags':
                    serial.dataReceived.emit({'fc': 3, 'slave': 1, address: 20})
                    assert [w._drivers()['bit' + str(bit)] for bit in range(4)] == [0, 1, 0, 1]
                    serial.dataReceived.emit({'fc': 3, 'slave': 1, address: 32})
                    assert w._feedback == 'abnormal'
                    assert not any(w._drivers()['bit' + str(bit)] for bit in range(8))
            for w in industrial:
                w.set_value('not numeric')
                assert w._feedback == 'abnormal'
        ''')
