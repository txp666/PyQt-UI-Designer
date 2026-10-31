"""Tab edits and selection tools preserve the editable widget hierarchy."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import sip
from PyQt5.QtCore import QEvent, QRectF, Qt
from PyQt5.QtGui import QFocusEvent
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QWidget

from app.core import modbus_master
from app.core.code_generator import _gen_ui
from app.common.signal_bus import signalBus
from app.core.project import ProjectData, ProjectManager
from app.core.widget_registry import registry
from app.designer import selection_manager as selection
from app.designer.canvas import DesignScene
from app.designer.canvas_item import CanvasItem
from app.designer.property_editor import PropertyEditor
from app.view.preview_interface import PreviewCanvas
from app.widgets.basic import register_basic_widgets
from app.widgets.composite import register_composite_widgets
from app.widgets.layout import TabContainer, register_layout_widgets


TOOLS = Path(__file__).resolve().parents[1] / "tools"


class DesignerEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_basic_widgets()
        register_layout_widgets()

    def setUp(self):
        self.scene = DesignScene()
        self.addCleanup(self.scene.clear)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "edited.uidp"

    def make_item(self, type_name, x=0, y=0, **props):
        properties = registry.get(type_name).get_default_props()
        properties.update(props)
        item = CanvasItem(type_name, properties)
        item.setPos(x, y)
        self.scene.add_canvas_item(item)
        return item

    def roundtrip(self):
        before = {item.widget_id: item.to_dict()
                  for item in self.scene.top_level_canvas_items()}
        manager = ProjectManager()
        manager.save_from_scene(self.scene, str(self.path))
        manager.load_to_scene(self.scene, str(self.path))
        self.assertEqual({item.widget_id: item.to_dict()
                          for item in self.scene.top_level_canvas_items()}, before)

    def test_controls_show_the_binding_and_modbus_settings_they_use(self):
        # Controls that show device state get a 数据绑定 card; a button has nothing to bind.
        for type_name, binds in (("ToggleSwitch", True), ("Slider", True), ("SpinBox", True),
                                 ("Label", True), ("PushButton", False)):
            with self.subTest(type_name=type_name):
                editor = PropertyEditor()
                self.addCleanup(editor.deleteLater)
                editor._load_item(self.make_item(type_name))
                self.assertEqual(hasattr(editor, "_bind_mode_combo"), binds)
        # A Modbus-mode control sends without the send toggle, so its Modbus settings stay visible.
        editor = PropertyEditor()
        self.addCleanup(editor.deleteLater)
        editor.resize(360, 900)
        editor._load_item(self.make_item("LineEdit", commandMode="Modbus", sendOnEnter=False))
        editor.show()
        self.app.processEvents()
        mode, function, template = (editor._prop_rows[name][1] for name in ("commandMode", "mbFunc", "commandTemplate"))
        self.assertTrue(mode.isVisible() and function.isVisible())
        self.assertFalse(template.isVisible())
        editor._on_prop_changed("commandMode", "文本")  # text mode does need the toggle
        self.assertFalse(mode.isVisible() or function.isVisible() or template.isVisible())

    def test_modbus_polling_rows_follow_the_poll_mode_and_binding_mode(self):
        register_composite_widgets()
        editor = PropertyEditor()
        self.addCleanup(editor.deleteLater)
        editor.resize(360, 1400)
        card = self.make_item("ModbusConfigCard")
        editor._load_item(card)
        editor.show()
        self.app.processEvents()
        mode, auto, table = (editor._prop_rows[name] for name in ("pollMode", "autoStart", "pollList"))
        self.assertEqual((mode[0].text(), auto[0].text(), mode[1].currentText(), auto[1].isChecked()),
                         ("轮询方式", "连接后自动轮询", "自动", True))
        self.assertFalse(table[1].isVisible(), "自动 polling needs no poll table")
        mode[1].setCurrentText("轮询表")
        self.assertTrue(table[0].isVisible() and table[1].isVisible())
        self.assertEqual(card.properties["pollMode"], "轮询表")
        # A Modbus binding's 采集周期 row comes last in its section, and only for Modbus.
        editor._load_item(self.make_item("Label"))
        self.app.processEvents()
        self.assertFalse(editor._bind_mb_period_spin.isVisible())
        editor._bind_mode_combo.setCurrentText("Modbus")
        self.assertTrue(editor._bind_mb_period_spin.isVisible())
        self.assertEqual(editor._bind_mb_period_label.text(), "采集周期(ms)")
        self.assertEqual(editor._bind_mb_period_spin.toolTip(), "0 = 用 Modbus 卡片的轮询 ms")
        editor._bind_mb_period_spin.setValue(250)
        self.assertEqual(editor._current_item.binding["mbPeriod"], 250)

    def test_renaming_tabs_preserves_active_page_widgets_and_child_visibility(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
        active = self.make_item("PushButton", 30, 70)
        tabs.add_child(active)
        hidden = self.make_item("PushButton", 40, 80)
        tabs.add_child(hidden, tab_index=0)
        pages = [tabs._inner_widget.widget(i) for i in range(2)]
        tabs.set_property("tabNames", "Renamed A\nRenamed B")
        self.assertEqual(tabs.properties["currentTab"], 1)
        self.assertEqual(tabs._inner_widget.currentIndex(), 1)
        self.assertEqual([tabs._inner_widget.widget(i) for i in range(2)], pages)
        self.assertTrue(active.isVisible())
        self.assertFalse(hidden.isVisible())
        self.assertEqual(tabs._inner_widget.tabText(1), "Renamed B")
        self.roundtrip()

    def test_page_reduction_preserves_contents_and_updates_property_editor(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB\nC", currentTab=2)
        children = []
        for page in range(3):
            child = self.make_item("PushButton", 20 + page * 30, 50 + page * 40)
            tabs.add_child(child, tab_index=page)
            children.append(child)
        original_positions = [child.pos() for child in children]
        tabs.properties["_tabLayout_2"] = "垂直"
        editor = PropertyEditor()
        self.addCleanup(lambda: sip.delete(editor))
        editor._load_item(tabs)
        self.assertEqual(editor._editors["currentTab"].maximum(), 2)
        editor._editors["tabNames"].setPlainText("A\nB")
        self.app.sendEvent(editor._editors["tabNames"], QFocusEvent(QEvent.FocusOut))
        self.assertEqual([child.tab_index for child in children], [0, 1, 1])
        self.assertEqual(tabs.properties["currentTab"], 1)
        self.assertEqual(tabs._inner_widget.currentIndex(), 1)
        self.assertEqual(editor._editors["currentTab"].value(), 1)
        self.assertEqual(editor._editors["currentTab"].maximum(), 1)
        self.assertEqual(editor._editors["tabLayout"].currentText(), "自由")
        self.assertNotIn("_tabLayout_2", tabs.properties)
        editor._editors["currentTab"].setValue(19)
        self.assertEqual(tabs.properties["currentTab"], 1)
        editor._editors["tabNames"].setPlainText("")
        self.app.sendEvent(editor._editors["tabNames"], QFocusEvent(QEvent.FocusOut))
        self.assertEqual(tabs._inner_widget.count(), 1)
        self.assertEqual(tabs._inner_widget.tabText(0), "标签1")
        self.assertEqual(editor._editors["currentTab"].maximum(), 0)
        self.assertEqual([child.tab_index for child in children], [0, 0, 0])
        self.assertEqual([child.pos() for child in children], original_positions)
        self.assertTrue(all(child.isVisible() for child in children))
        self.roundtrip()

    def test_typing_names_does_not_move_children_and_save_commits_without_focus_loss(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
        child = self.make_item("PushButton", 30, 70)
        tabs.add_child(child)
        editor = PropertyEditor()
        self.addCleanup(lambda: sip.delete(editor))
        editor.set_scene(self.scene)
        editor._load_item(tabs)
        editor.show()
        names = editor._editors["tabNames"]
        names.setFocus()
        self.app.processEvents()
        manager = ProjectManager()
        signalBus.canvasChanged.connect(manager.mark_dirty)
        self.addCleanup(lambda: signalBus.canvasChanged.disconnect(manager.mark_dirty))
        names.selectAll()
        QTest.keyClicks(names, "First")
        self.assertEqual(child.tab_index, 1)
        self.assertEqual(tabs._inner_widget.count(), 2)
        self.assertTrue(manager.is_dirty)
        QTest.keyClick(names, Qt.Key_Return)
        QTest.keyClicks(names, "Second")
        self.assertTrue(names.hasFocus())
        manager.save_from_scene(self.scene, str(self.path))
        self.assertTrue(names.hasFocus())
        saved = json.loads(self.path.read_text(encoding="utf-8"))["widgets"][0]
        self.assertEqual(saved["properties"]["tabNames"], "First\nSecond")
        self.assertEqual(saved["properties"]["currentTab"], 1)
        self.assertEqual(saved["children"][0]["tabIndex"], 1)
        self.assertFalse(manager.is_dirty)
        self.roundtrip()

    def test_export_capture_and_changing_selection_commit_pending_names(self):
        tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
        child = self.make_item("PushButton", 30, 70)
        tabs.add_child(child)
        editor = PropertyEditor()
        self.addCleanup(lambda: sip.delete(editor))
        editor.set_scene(self.scene)
        editor._load_item(tabs)
        editor._editors["tabNames"].setPlainText("Changed A\nChanged B")
        project = ProjectManager().export_scene_data(self.scene)
        self.assertEqual(project.widgets[0]["properties"]["tabNames"], "Changed A\nChanged B")
        self.assertEqual(child.tab_index, 1)
        editor._editors["tabNames"].setPlainText("Only page")
        editor._load_item(child)
        self.assertEqual(child.tab_index, 0)
        self.assertEqual(tabs.properties["currentTab"], 0)
        self.assertEqual(tabs._inner_widget.count(), 1)
        self.roundtrip()

    def test_replacing_project_discards_pending_edits_to_removed_items(self):
        for operation in ("load", "new"):
            with self.subTest(operation=operation):
                self.scene.clear()
                tabs = self.make_item("TabWidget", tabNames="A\nB", currentTab=1)
                child = self.make_item("PushButton", 30, 70)
                tabs.add_child(child)
                original = tabs.to_dict()
                editor = PropertyEditor()
                editor.set_scene(self.scene)
                editor._load_item(tabs)
                names = editor._editors["tabNames"]
                manager = ProjectManager()
                signalBus.canvasChanged.connect(manager.mark_dirty)
                try:
                    names.setPlainText("Uncommitted replacement")
                    self.assertTrue(manager.is_dirty)
                    self.assertEqual(tabs.to_dict(), original)
                    if operation == "load":
                        self.path.write_text(json.dumps({
                            "appName": "Replacement",
                            "widgets": [{"id": "replacement", "type": "PushButton"}],
                        }), encoding="utf-8")
                        manager.load_to_scene(self.scene, str(self.path))
                        self.assertEqual(manager.current.app_name, "Replacement")
                        self.assertIsNotNone(self.scene.get_item_by_id("replacement"))
                    else:
                        self.scene.clear_all()
                        manager.new_project()
                        signalBus.widgetDeselected.emit()
                        self.assertEqual(self.scene.top_level_canvas_items(), [])
                    self.assertIsNone(editor._current_item)
                    self.assertFalse(manager.is_dirty)
                    self.assertEqual(tabs.to_dict(), original)
                    # A delayed focus event from the old editor must also do nothing.
                    self.app.sendEvent(names, QFocusEvent(QEvent.FocusOut))
                    self.assertFalse(manager.is_dirty)
                    self.assertEqual(tabs.to_dict(), original)
                finally:
                    signalBus.canvasChanged.disconnect(manager.mark_dirty)
                    sip.delete(editor)
                    sip.delete(tabs)

    def test_native_tab_page_reduction_reparents_contents_without_losing_geometry(self):
        tabs = TabContainer()
        self.addCleanup(lambda: sip.delete(tabs))
        tabs.set_tab_names("A\nB\nC")
        children = [QWidget(tabs.widget(i)) for i in range(3)]
        for index, child in enumerate(children):
            child.setGeometry(20 + index * 10, 40, 90, 30)
        geometry = [child.geometry() for child in children]
        tabs.setCurrentIndex(2)
        tabs.set_tab_names("A")
        self.assertEqual(tabs.count(), 1)
        self.assertEqual(tabs.currentIndex(), 0)
        self.assertTrue(all(child.parentWidget() is tabs.widget(0) for child in children))
        self.assertEqual([child.geometry() for child in children], geometry)

    def test_legacy_tab_indices_are_safe_in_designer_preview_and_generated_widgets(self):
        for names, expected_count in (("A\nB", 2), ("", 1)):
            with self.subTest(names=names):
                document = {
                    "type": "TabWidget", "id": "tabs",
                    "geometry": {"x": 20, "y": 30, "w": 350, "h": 250},
                    "properties": {"tabNames": names, "currentTab": 19},
                    "children": [{
                        "type": "PushButton", "id": "button", "tabIndex": 19,
                        "properties": {"text": "Keep me"},
                        "geometry": {"x": 30, "y": 70, "w": 120, "h": 36},
                    }],
                }
                original = copy.deepcopy(document)
                item = CanvasItem.from_dict(document)
                self.scene.add_canvas_item(item)
                self.assertEqual(item.properties["currentTab"], expected_count - 1)
                self.assertEqual(item._container_children[0].tab_index, expected_count - 1)
                self.assertTrue(item._container_children[0].isVisible())
                self.roundtrip()
                self.scene.clear()

                preview = PreviewCanvas()
                try:
                    project = ProjectData.from_dict({"widgets": [document]})
                    preview.build_from_project(project)
                    tabs, button = preview._widgets
                    self.assertEqual(tabs.count(), expected_count)
                    self.assertEqual(tabs.currentIndex(), expected_count - 1)
                    self.assertIs(button.parentWidget(), tabs.widget(expected_count - 1))
                    self.assertFalse(button.isWindow())
                finally:
                    preview.clear()
                    sip.delete(preview)

                # Execute the exported creation method with real Qt widgets.
                # A QWidget host avoids requiring native frameless-window APIs.
                serial_module = ModuleType("serial_handler")
                serial_module._list_all_ports = lambda: []
                vars(serial_module).update(  # the exported serial_handler holds the Modbus master
                    (name, value) for name, value in vars(modbus_master).items() if not name.startswith("__"))
                namespace = {"__file__": str(Path(self.temp.name) / "ui.py")}
                with patch.dict("sys.modules", {"serial_handler": serial_module}):
                    exec(_gen_ui([document], 500, 350), namespace)
                host = SimpleNamespace(_page=QWidget(), widgets={}, _theme_containers=[])
                try:
                    namespace["MainUI"]._create_widgets(host)
                    tabs, button = host.widgets["tabs"], host.widgets["button"]
                    self.assertEqual(tabs.count(), expected_count)
                    self.assertEqual(tabs.currentIndex(), expected_count - 1)
                    self.assertIs(button.parentWidget(), tabs.widget(expected_count - 1))
                    self.assertFalse(button.isWindow())
                finally:
                    sip.delete(host._page)
                self.assertEqual(document, original)

    def test_alignment_uses_scene_edges_across_nested_free_containers(self):
        for action, edge in (
                (selection.align_left, "left"), (selection.align_right, "right"),
                (selection.align_top, "top"), (selection.align_bottom, "bottom")):
            with self.subTest(edge=edge):
                self.scene.clear()
                outer = self.make_item("CardContainer", 200, 100)
                inner = self.make_item("CardContainer", 250, 150)
                outer.add_child(inner)
                nested = self.make_item("PushButton", 290, 210)
                inner.add_child(nested)
                standalone = self.make_item("PushButton", 20, 400)
                standalone.set_rect(QRectF(0, 0, 160, 50))
                nested.setSelected(True)
                standalone.setSelected(True)
                before = [getattr(item.mapRectToScene(item.rect()), edge)()
                          for item in (nested, standalone)]
                expected = max(before) if edge in ("right", "bottom") else min(before)
                action(self.scene)
                for item in (nested, standalone):
                    self.assertEqual(getattr(item.mapRectToScene(item.rect()), edge)(),
                                     expected)
                self.roundtrip()

    def test_distribution_uses_scene_positions_across_container_boundaries(self):
        for action, axis in ((selection.distribute_horizontal, "x"),
                             (selection.distribute_vertical, "y")):
            with self.subTest(axis=axis):
                self.scene.clear()
                parent = self.make_item("CardContainer", 200, 150)
                nested = self.make_item("PushButton", 270, 210)
                parent.add_child(nested)
                first = self.make_item("PushButton", 20, 50)
                last = self.make_item("PushButton", 500, 600)
                for item in (first, nested, last):
                    item.setSelected(True)
                action(self.scene)
                positions = [getattr(item.scenePos(), axis)() for item in (first, nested, last)]
                self.assertEqual(positions[1], (positions[0] + positions[2]) / 2)
                self.roundtrip()

    def test_selection_tools_skip_managed_children_and_selected_descendants(self):
        automatic = self.make_item("VBoxLayout", 600, 200)
        managed = self.make_item("PushButton")
        automatic.add_child(managed)
        managed_before = managed.pos()
        card = self.make_item("CardContainer", 250, 300)
        nested = self.make_item("PushButton", 280, 350)
        card.add_child(nested)
        local_before = nested.pos()
        other = self.make_item("PushButton", 50, 50)
        for item in (managed, card, nested, other):
            item.setSelected(True)
        selection.align_left(self.scene)
        self.assertEqual(card.scenePos().x(), other.scenePos().x())
        self.assertEqual(nested.pos(), local_before)
        self.assertEqual(managed.pos(), managed_before)
        selection.align_top(self.scene)
        self.assertEqual(card.scenePos().y(), other.scenePos().y())
        self.assertEqual(nested.pos(), local_before)
        self.assertEqual(managed.pos(), managed_before)
        self.roundtrip()



# The rows of the frame-format sections, in the order FluentHMI Studio shows them too.
HEX_ROWS = ["帧头(HEX)", "帧尾(HEX)", "长度字段偏移", "长度字节数", "长度字节序", "长度含义",
            "固定帧长", "校验", "校验起点", "校验字节序", "空闲超时(ms)", "字段表"]
LINE_ROWS = ["分隔符", "行结束符", "键值分隔符", "编码"]


class FrameFormatEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        register_basic_widgets()
        register_composite_widgets()

    def setUp(self):
        self.scene = DesignScene()
        self.addCleanup(self.scene.clear)
        self.manager = ProjectManager()
        self.editor = PropertyEditor()
        self.addCleanup(self.editor.deleteLater)
        self.editor.set_scene(self.scene)
        self.editor.set_project_source(lambda: self.manager.current)
        self.changes = []
        record = lambda: self.changes.append(True)  # noqa: E731
        signalBus.canvasChanged.connect(record)
        self.addCleanup(signalBus.canvasChanged.disconnect, record)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "frames.uidp"

    @staticmethod
    def shown(rows):
        return [label.text() for label, _editor in rows.values() if not label.isHidden()]

    def test_project_section_shows_its_modes_rows_and_writes_the_project(self):
        rows = self.editor._project_frame_rows
        serial = lambda: self.manager.current.serial  # noqa: E731
        parser = rows["parser"][1]
        self.assertEqual([parser.itemText(i) for i in range(parser.count())],
                         ["line", "hex", "modbus", "modbus_tcp", "modbus_ascii"])
        self.assertEqual(self.shown(rows), ["解析模式", *LINE_ROWS])

        # Line rows: the terminator is typed with backslash escapes and stored as the real characters.
        terminator = rows["terminator"][1]
        self.assertEqual([terminator.itemText(i) for i in range(terminator.count())], ["\\n", "\\r\\n", "\\r", ";"])
        self.assertEqual((terminator.currentText(), rows["kvSeparator"][1].currentText(),
                          rows["encoding"][1].currentText()), ("\\n", "=", "utf-8"))
        terminator.setCurrentIndex(1)
        self.assertEqual(serial()["parserConfig"]["terminator"], "\r\n")
        self.assertTrue(self.changes, "editing the frame format modifies the project")
        for typed, stored in (("\\t;", "\t;"), ("END", "END"), ("a\\\\b", "a\\b"), ("\\x", "\\x"), (";", ";")):
            terminator.setText(typed)
            self.assertEqual(serial()["parserConfig"]["terminator"], stored, typed)
        terminator.setText("")
        self.assertEqual(serial()["parserConfig"]["terminator"], ";", "an emptied box is not stored")
        rows["kvSeparator"][1].setCurrentText(":")
        rows["encoding"][1].setCurrentText("gbk")
        self.assertEqual(serial()["parserConfig"],
                         {"separator": ",", "terminator": ";", "kvSeparator": ":", "encoding": "gbk"})
        rows["separator"][1].setText(" ")  # a separator is kept as typed, even a single space
        terminator.setText("\\r\\n")
        self.manager.save_from_scene(self.scene, str(self.path))
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((saved["serial"]["parserConfig"]["separator"],
                          saved["serial"]["parserConfig"]["terminator"]), (" ", "\r\n"))
        self.manager.load_to_scene(self.scene, str(self.path))
        rows = self.editor._project_frame_rows  # loading rebuilds the section
        self.assertEqual((rows["separator"][1].text(), rows["terminator"][1].currentText(),
                          rows["kvSeparator"][1].currentText(), rows["encoding"][1].currentText()),
                         (" ", "\\r\\n", ":", "gbk"))
        serial()["parserConfig"]["encoding"] = "GBK"  # the parser ignores case
        self.editor._clear()
        rows = self.editor._project_frame_rows
        self.assertEqual(rows["encoding"][1].currentText(), "gbk")

        for mode in ("modbus", "modbus_tcp", "modbus_ascii"):
            rows["parser"][1].setCurrentText(mode)
            self.assertEqual((serial()["parser"], self.shown(rows)), (mode, ["解析模式"]), "nothing to set for Modbus")

        # Hex rows: the field table takes either comma, skips comments and points out a bad line.
        rows["parser"][1].setCurrentText("hex")
        self.assertEqual(self.shown(rows), ["解析模式", *HEX_ROWS])
        self.assertEqual((rows["header"][1].text(), rows["footer"][1].text()), ("AA55", "55AA"))
        rows["header"][1].setText(" AA 55 ")
        self.assertEqual(serial()["parserConfig"]["header"], "AA 55", "HEX text loses its outer spaces")
        rows["footer"][1].setText("")
        rows["lengthOffset"][1].setValue(2)
        rows["checksum"][1].setCurrentText("和校验")
        rows["lengthSize"][1].setCurrentText("2")
        rows["lengthSize"][1].setCurrentText("1")
        fields = rows["fields"][1]
        fields.text_edit.setPlainText("# 名字,偏移,长度,类型[,字节序]\ncmd,1,1,uint8\n\ntemp，2，2，int16，小端(LE)")
        self.assertTrue(fields.hint.isHidden())
        config = serial()["parserConfig"]
        self.assertEqual(config["fields"], [["cmd", 1, 1, "uint8"], ["temp", 2, 2, "int16", "小端(LE)"]])
        self.assertEqual((config["footer"], config["lengthOffset"], config["lengthSize"], config["checksum"]),
                         ("", 2, 1, "和校验"))
        for text, hint in (("cmd,1,1,uint8\ntemp,2,2,int16,LE", "第 2 行格式错误"),
                           ("cmd,1,1,uint8\n# ok\nx,one,1,uint8", "第 3 行格式错误")):
            fields.text_edit.setPlainText(text)
            self.assertEqual((fields.hint.isHidden(), fields.hint.text()), (False, hint))
        self.assertEqual(serial()["parserConfig"]["fields"], config["fields"], "the last good table is kept")

        # Saving replaces the project object; the section keeps writing to the open one.
        self.manager.save_from_scene(self.scene, str(self.path))
        rows["idleTimeout"][1].setValue(20)
        self.assertEqual(serial()["parserConfig"]["idleTimeout"], 20)
        self.manager.save_from_scene(self.scene, str(self.path))
        self.manager.load_to_scene(self.scene, str(self.path))
        rows = self.editor._project_frame_rows
        self.assertEqual((rows["parser"][1].currentText(), rows["lengthOffset"][1].value()), ("hex", 2))
        self.assertEqual(rows["fields"][1].text_edit.toPlainText(), "cmd,1,1,uint8\ntemp,2,2,int16,小端(LE)")

    def load_card(self, type_name):
        item = CanvasItem(type_name, registry.get(type_name).get_default_props())
        self.scene.add_canvas_item(item)
        self.editor._load_item(item)
        return item, self.editor._editors["defaultParser"]

    def test_card_section_follows_the_cards_own_mode_and_writes_the_card(self):
        for type_name in ("SerialConfigCard", "TcpConfigCard", "MqttConfigCard"):
            with self.subTest(type_name=type_name):
                self.assertIn("modbus_ascii", registry.get(type_name).get_prop_def("defaultParser").options)
                item, mode = self.load_card(type_name)
                self.assertEqual(item.properties["parserConfig"], {})
                self.assertNotIn("parserConfig", self.editor._prop_rows, "an object gets no ordinary row")
                self.assertTrue(self.editor._card_frame_section.isHidden(), "项目设置 uses the project's")
                for parser_type in ("modbus", "modbus_ascii"):
                    mode.setCurrentText(parser_type)
                    self.assertFalse(self.editor._card_frame_section.isHidden())
                    self.assertEqual(self.shown(self.editor._card_frame_rows), [], "nothing to set for Modbus")
                    self.assertEqual(item._inner_widget.parser_type, parser_type)
                mode.setCurrentText("line")
                rows = self.editor._card_frame_rows
                self.assertEqual(self.shown(rows), LINE_ROWS)
                rows["terminator"][1].setCurrentIndex(2)
                rows["encoding"][1].setCurrentText("ascii")
                self.assertEqual(item.properties["parserConfig"],
                                 {"separator": ",", "terminator": "\r", "encoding": "ascii"})
                self.scene.clear_all()

                item, mode = self.load_card(type_name)
                mode.setCurrentText("hex")
                rows = self.editor._card_frame_rows
                self.assertEqual(self.shown(rows), HEX_ROWS)
                rows["header"][1].setText("7E")
                rows["footer"][1].setText("")
                rows["idleTimeout"][1].setValue(20)
                rows["fields"][1].text_edit.setPlainText("a,0,1,uint8")
                expected = {"header": "7E", "footer": "", "idleTimeout": 20, "fields": [["a", 0, 1, "uint8"]]}
                self.assertEqual(item.properties["parserConfig"], expected)
                self.assertEqual(item._inner_widget._parser_config, expected)
                self.assertEqual(self.manager.current.serial["parserConfig"], {"separator": ","},
                                 "the project's frame format is untouched")
                mode.setCurrentText("项目设置")
                self.assertTrue(self.editor._card_frame_section.isHidden())
                mode.setCurrentText("hex")
                self.assertEqual(self.editor._card_frame_rows["header"][1].text(), "7E")
                self.manager.save_from_scene(self.scene, str(self.path))
                self.manager.load_to_scene(self.scene, str(self.path))
                loaded = self.scene.get_item_by_id(item.widget_id)
                self.assertEqual(loaded.properties["parserConfig"], expected)
                self.editor._load_item(loaded)
                self.assertEqual(self.editor._card_frame_rows["idleTimeout"][1].value(), 20)
                self.scene.clear_all()

        # A card switched to the project's mode starts from the project's frame format.
        serial = self.manager.current.serial
        serial.update(parser="hex", parserConfig={"header": "7E", "footer": "", "idleTimeout": 20})
        item, mode = self.load_card("TcpConfigCard")
        mode.setCurrentText("hex")
        rows = self.editor._card_frame_rows
        self.assertEqual((rows["header"][1].text(), rows["idleTimeout"][1].value()), ("7E", 20))
        rows["fields"][1].text_edit.setPlainText("a,0,1,uint8")
        self.assertEqual(item.properties["parserConfig"],
                         {"header": "7E", "footer": "", "idleTimeout": 20, "fields": [["a", 0, 1, "uint8"]]})
        self.assertEqual(serial["parserConfig"], {"header": "7E", "footer": "", "idleTimeout": 20})

    def test_projects_reject_bad_card_frame_formats(self):
        def project(properties, parser="line"):
            return {"serial": {"parser": parser}, "widgets": [
                {"type": "MqttConfigCard", "id": "link", "properties": properties}]}
        for document, message in (
            (project({"parserConfig": [1]}), "卡片 link 的 parserConfig 必须是对象"),
            (project({"defaultParser": "hex", "parserConfig": {"footer": ""}}),
             "卡片 link: HEX 帧需要帧尾、长度字段、固定帧长或空闲超时之一来分帧"),
            (project({"parserConfig": {"header": "XYZ"}}, parser="hex"), "卡片 link: HEX 帧头或帧尾不是十六进制"),
            (project({"defaultParser": "line", "parserConfig": {"separator": ""}}, parser="hex"),
             "卡片 link: 行分隔符不能为空"),
            (project({"parserConfig": {"terminator": ""}}), "卡片 link: 行结束符不能为空"),
            (project({"defaultParser": "line", "parserConfig": {"kvSeparator": "-"}}), "卡片 link: 键值分隔符只能是 = 或 :"),
            (project({"parserConfig": {"encoding": "big5"}}), "卡片 link: 编码只能是 utf-8、gbk 或 ascii"),
            ({"serial": {"parser": "line", "parserConfig": {"encoding": "utf8"}}}, "编码只能是 utf-8、gbk 或 ascii"),
            (project({"parserConfig": None}), "卡片 link 的 parserConfig 必须是对象"),
            (project({"defaultParser": "udp", "parserConfig": {}}), "卡片 link: 未知解析模式: udp"),
            ({"widgets": [{"type": "SerialConfigCard", "properties": {"parserConfig": "AA55"}}]},
             "卡片  的 parserConfig 必须是对象"),
        ):
            with self.subTest(message=message):
                with self.assertRaises(ValueError) as caught:
                    ProjectData.validate(document)
                self.assertEqual(str(caught.exception), message)
        for document in (
            project({"defaultParser": "hex", "parserConfig": {"header": "7E", "idleTimeout": 5}}),
            project({"defaultParser": "modbus_ascii", "parserConfig": {}}),
            project({"parserConfig": {"terminator": ";", "kvSeparator": ":", "encoding": "GBK"}}, parser="line"),
            project({"parserConfig": {}}),
            project({"defaultParser": "udp"}),  # without parserConfig: the old checks only
            {"widgets": [{"type": "Label", "properties": {"parserConfig": 1}}]},
        ):
            with self.subTest(valid=document):
                ProjectData.validate(document)
        # The check tool prints the same message, readable even where a pipe's code page has no Chinese.
        path = Path(self.temp.name) / "bad.uidp"
        path.write_text(json.dumps(project({"parserConfig": [1]}), ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([sys.executable, str(TOOLS / "check_uidp.py"), str(path)],
                                capture_output=True, text=True, encoding="utf-8",
                                env={**os.environ, "PYTHONIOENCODING": "cp1252"})
        self.assertEqual((result.returncode, result.stdout.strip()), (1, "卡片 link 的 parserConfig 必须是对象"),
                         result.stderr)


if __name__ == "__main__":
    unittest.main()
