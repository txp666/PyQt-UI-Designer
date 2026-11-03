# coding: utf-8
"""Undo/redo for the designer: snapshots of the design document, the way Save writes it."""


class DesignHistory:
    """The states the design went through, the current one and the one last saved.

    A burst of edits (keystrokes in one field, spin box arrows) shares a merge key and becomes one step.
    """

    LIMIT = 100

    def __init__(self):
        self._states = []
        self._index = -1
        self._saved = None
        self._merge_key = None

    def reset(self, state):
        """Start over from ``state``, which counts as saved (a new or just opened project)."""
        self._states = [state]
        self._index = 0
        self._saved = 0
        self._merge_key = None

    @property
    def current(self):
        return self._states[self._index]

    def record(self, state, merge_key=None) -> bool:
        """Make ``state`` the current state; False when it is the current one already."""
        if not self._states:
            self.reset(state)
            return True
        if state == self.current:
            return False
        del self._states[self._index + 1:]  # an edit after an undo drops what could be redone
        if self._saved is not None and self._saved > self._index:
            self._saved = None
        if (merge_key is not None and merge_key == self._merge_key
                and self._index > 0 and self._index != self._saved):
            if state == self._states[self._index - 1]:  # the burst ended where it began
                self._states.pop()
                self._index -= 1
                self._merge_key = None
            else:
                self._states[self._index] = state
            return True
        self._states.append(state)
        self._index += 1
        self._merge_key = merge_key
        if len(self._states) > self.LIMIT:
            del self._states[0]
            self._index -= 1
            self._saved = self._saved - 1 if self._saved else None
        return True

    def replace_current(self, state):
        """The current state as the canvas really holds it after a restore."""
        self._states[self._index] = state

    def can_undo(self) -> bool:
        return self._index > 0

    def can_redo(self) -> bool:
        return 0 <= self._index < len(self._states) - 1

    def undo(self):
        if not self.can_undo():
            return None
        self._index -= 1
        self._merge_key = None
        return self.current

    def redo(self):
        if not self.can_redo():
            return None
        self._index += 1
        self._merge_key = None
        return self.current

    def mark_saved(self):
        self._saved = self._index
        self._merge_key = None

    def is_clean(self) -> bool:
        return self._index == self._saved

    def states(self):
        return list(self._states)
