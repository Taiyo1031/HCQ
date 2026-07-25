"""Unit tests for Houdini Network Editor navigation."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from hcq.navigation import HoudiniNavigation


class FakeNode:
    def __init__(self, path: str = "/obj/geo1/cache") -> None:
        self._path = path
        self._parent = object()
        self.selected = False
        self.current = False

    def path(self) -> str:
        return self._path

    def parent(self):
        return self._parent

    def setSelected(self, selected: bool, **_kwargs) -> None:
        self.selected = selected

    def setCurrent(self, current: bool, **_kwargs) -> None:
        self.current = current


class FakePane:
    def __init__(self, pane_type: str, *, current: bool = False) -> None:
        self._type = pane_type
        self._current = current
        self.focused = False
        self.pwd = None
        self.current_node = None
        self.framed = False
        self.mutations = 0

    def type(self) -> str:
        return self._type

    def isCurrentTab(self) -> bool:
        return self._current

    def setIsCurrentTab(self) -> None:
        self.focused = True
        self._current = True

    def setPwd(self, value) -> None:
        self.mutations += 1
        self.pwd = value

    def setCurrentNode(self, node) -> None:
        self.mutations += 1
        self.current_node = node

    def frameSelection(self) -> None:
        self.mutations += 1
        self.framed = True


class FakeDesktop:
    def __init__(self, created_pane: FakePane | None = None) -> None:
        self.created_pane = created_pane
        self.calls: list[tuple[tuple, dict]] = []

    def createFloatingPaneTab(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.created_pane


class FakeUI:
    def __init__(self, panes, desktop: FakeDesktop | None = None) -> None:
        self._panes = tuple(panes)
        self._desktop = desktop
        self.parameter_nodes = []

    def paneTabs(self):
        return self._panes

    def curDesktop(self):
        return self._desktop

    def showNodeEditor(self, node) -> None:
        self.parameter_nodes.append(node)


def fake_hou(node: FakeNode | None, ui: FakeUI):
    return SimpleNamespace(
        node=lambda _path: node,
        ui=ui,
        paneTabType=SimpleNamespace(
            NetworkEditor="network",
            Parm="parameters",
            SceneViewer="scene",
        ),
    )


class NavigationTests(unittest.TestCase):
    def test_focuses_existing_network_editor_without_touching_scene_viewer(self):
        node = FakeNode()
        scene = FakePane("scene", current=True)
        network = FakePane("network")
        desktop = FakeDesktop(FakePane("network"))
        ui = FakeUI([scene, network], desktop)

        result = HoudiniNavigation(fake_hou(node, ui)).go_to_node(node.path())

        self.assertTrue(result.success, result.message)
        self.assertTrue(network.focused)
        self.assertIs(network.pwd, node.parent())
        self.assertIs(network.current_node, node)
        self.assertTrue(network.framed)
        self.assertEqual(scene.mutations, 0)
        self.assertEqual(desktop.calls, [])
        self.assertEqual(ui.parameter_nodes, [])
        self.assertTrue(node.selected)
        self.assertTrue(node.current)

    def test_creates_floating_network_editor_when_none_exists(self):
        node = FakeNode()
        scene = FakePane("scene", current=True)
        created = FakePane("network")
        desktop = FakeDesktop(created)
        ui = FakeUI([scene], desktop)

        result = HoudiniNavigation(fake_hou(node, ui)).go_to_node(node.path())

        self.assertTrue(result.success, result.message)
        self.assertEqual(len(desktop.calls), 1)
        self.assertEqual(desktop.calls[0][0][0], "network")
        self.assertTrue(created.focused)
        self.assertIs(created.current_node, node)
        self.assertTrue(created.framed)
        self.assertEqual(scene.mutations, 0)
        self.assertEqual(ui.parameter_nodes, [])

    def test_reports_failure_when_network_editor_cannot_be_opened(self):
        node = FakeNode()
        scene = FakePane("scene", current=True)
        ui = FakeUI([scene], FakeDesktop(None))

        result = HoudiniNavigation(fake_hou(node, ui)).go_to_node(node.path())

        self.assertFalse(result.success)
        self.assertIn("Network Editor", result.message)
        self.assertEqual(scene.mutations, 0)

    def test_reports_missing_node(self):
        result = HoudiniNavigation(
            fake_hou(None, FakeUI([], FakeDesktop()))
        ).go_to_node("/obj/missing")

        self.assertFalse(result.success)
        self.assertIn("Node not found", result.message)


if __name__ == "__main__":
    unittest.main()
