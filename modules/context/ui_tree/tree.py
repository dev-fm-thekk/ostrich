"""
UI Tree Context Extraction and Candidate Resolution
===================================================
Provides efficient AT-SPI accessibility tree traversal, element discovery,
and candidate filtering based on role, name, and action affordance.

Key Features & Optimizations:
- Fast In-Memory State & Role Filters: Checks role enums and bitset states before
  invoking expensive D-Bus IPC calls for action interfaces.
- Smart Subtree Pruning: Prunes defunct, hidden, and non-showing branches early.
- Compact Path Formatting: Omit unnamed layout/filler containers from ancestor paths.
- Search Flexibility: Search and rank elements by role, name, and supported action.
- Serialized String Output: Easily generate formatted, token-efficient lists for
  LLM planning prompts and CLI inspection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import gi

gi.require_version("Atspi", "2.0")
from gi.repository import Atspi, GLib

log = logging.getLogger(__name__)

# Shorthand aliases for Atspi enums
S = Atspi.StateType
R = Atspi.Role


# ===========================================================================
# Safe Exception Handling Helper
# ===========================================================================

def safe(fn: Callable[[], Any] | Any, default: Any = None) -> Any:
    """Execute callable safely, catching GLib / D-Bus and AT-SPI exceptions.

    If `fn` is already a value (non-callable), it is returned directly.
    """
    if not callable(fn):
        return fn
    try:
        return fn()
    except (GLib.Error, Exception):
        return default


# ===========================================================================
# AT-SPI Role Classification Sets
# ===========================================================================

def _roles(*names: str) -> set[Any]:
    """Tolerate role names missing in older or variant libatspi versions."""
    return {getattr(R, name) for name in names if hasattr(R, name)}


# Roles that inherently afford click / activation
CLICKABLE_ROLES: set[Any] = _roles(
    "PUSH_BUTTON",
    "TOGGLE_BUTTON",
    "CHECK_BOX",
    "RADIO_BUTTON",
    "LINK",
    "MENU_ITEM",
    "CHECK_MENU_ITEM",
    "RADIO_MENU_ITEM",
    "PAGE_TAB",
    "LIST_ITEM",
    "TABLE_CELL",
)

# Roles that represent toggleable states (checked / unchecked)
TOGGLE_ROLES: set[Any] = _roles(
    "TOGGLE_BUTTON",
    "CHECK_BOX",
    "RADIO_BUTTON",
    "SWITCH",
    "CHECK_MENU_ITEM",
    "RADIO_MENU_ITEM",
)

# Roles that support text typing / editing
EDITABLE_ROLES: set[Any] = _roles(
    "ENTRY",
    "TEXT",
    "PASSWORD_TEXT",
    "SPIN_BUTTON",
    "COMBO_BOX",
)

# Roles that afford scrolling
SCROLL_ROLES: set[Any] = _roles(
    "SCROLL_PANE",
    "LIST",
    "TREE",
    "TREE_TABLE",
    "TABLE",
    "DOCUMENT_WEB",
    "DOCUMENT_TEXT",
    "DOCUMENT_FRAME",
)

# Informative states to keep in candidate representations (filtered for brevity)
KEEP_STATES: set[str] = {
    "checked",
    "pressed",
    "selected",
    "expanded",
    "collapsed",
    "expandable",
    "editable",
    "focused",
    "enabled",
    "active",
}


# ===========================================================================
# Affordance and Match Helpers
# ===========================================================================

def _has_action(acc: Any) -> bool:
    """Check if accessible element implements Atspi.Action with at least 1 action.

    Performs a D-Bus IPC query; used as a fallback when role/state checks
    are inconclusive.
    """
    iface = safe(lambda: acc.get_action_iface())
    if iface is None:
        return False
    count = safe(lambda: Atspi.Action.get_n_actions(iface), 0) or 0
    return count > 0


def _matches_action(acc: Any, ss: Any, role_val: Any, action: str | None) -> bool:
    """Check if an element satisfies the requested action affordance.

    Optimized to prioritize fast local checks (in-memory state bitsets and role enums)
    before making expensive IPC D-Bus calls via get_action_iface().
    """
    if ss is None:
        return False

    enabled = ss.contains(S.ENABLED) or ss.contains(S.SENSITIVE)
    if not enabled:
        return False

    if action is None or action.lower() in ("any", "none", ""):
        # Match any interactive element
        return (
            role_val in CLICKABLE_ROLES
            or role_val in TOGGLE_ROLES
            or role_val in EDITABLE_ROLES
            or ss.contains(S.FOCUSABLE)
            or ss.contains(S.SELECTABLE)
            or ss.contains(S.CHECKABLE)
            or ss.contains(S.EDITABLE)
            or _has_action(acc)
        )

    act = action.strip().lower()

    if act == "click":
        # Fast path: check role and selectable state before D-Bus query
        if role_val in CLICKABLE_ROLES or ss.contains(S.SELECTABLE):
            return True
        return _has_action(acc)

    if act == "toggle":
        return ss.contains(S.CHECKABLE) or role_val in TOGGLE_ROLES

    if act == "select":
        if ss.contains(S.SELECTABLE) or role_val in CLICKABLE_ROLES:
            return True
        return _has_action(acc)

    if act == "expand":
        return ss.contains(S.EXPANDABLE) and not ss.contains(S.EXPANDED)

    if act == "collapse":
        return ss.contains(S.EXPANDABLE) and ss.contains(S.EXPANDED)

    if act in ("type", "edit"):
        return ss.contains(S.EDITABLE) or role_val in EDITABLE_ROLES

    if act == "scroll":
        return role_val in SCROLL_ROLES

    if act == "focus":
        return ss.contains(S.FOCUSABLE)

    # Fallback for unrecognized or custom action names
    return _has_action(acc) or ss.contains(S.FOCUSABLE)


# ===========================================================================
# Element Geometry & States Inspection
# ===========================================================================

def get_element_bounds(
    acc: Any,
    coord_type: Any = None,
) -> tuple[int, int, int, int] | None:
    """Retrieve bounding box (x, y, width, height) of an accessible element.

    Falls back to Atspi.Component interface if get_extents is not directly on acc.
    """
    if acc is None:
        return None

    if coord_type is None:
        coord_type = Atspi.CoordType.SCREEN

    # Direct extents lookup (newer libatspi)
    rect = safe(lambda: acc.get_extents(coord_type))
    if rect is None:
        comp = safe(acc.get_component_iface)
        rect = safe(lambda: Atspi.Component.get_extents(comp, coord_type)) if comp else None

    if rect and (rect.width > 0 or rect.height > 0):
        return (rect.x, rect.y, rect.width, rect.height)
    return None


def get_element_states(acc: Any) -> list[str]:
    """Retrieve active informative state nicknames for an accessible element."""
    ss = safe(acc.get_state_set)
    if ss is None:
        return []
    states = [
        s.value_nick
        for s in safe(ss.get_states, []) or []
        if hasattr(s, "value_nick") and s.value_nick in KEEP_STATES
    ]
    return sorted(states)


def find_active_window() -> Any | None:
    """Find and return the currently active top-level desktop window."""
    try:
        desktop = Atspi.get_desktop(0)
    except Exception:
        return None

    if desktop is None:
        return None

    app_count = safe(desktop.get_child_count, 0) or 0
    for i in range(app_count):
        app = safe(lambda: desktop.get_child_at_index(i))
        if app is None:
            continue
        win_count = safe(app.get_child_count, 0) or 0
        for j in range(win_count):
            win = safe(lambda: app.get_child_at_index(j))
            if win is None:
                continue
            ss = safe(win.get_state_set)
            if ss and ss.contains(S.ACTIVE):
                return win
    return None


def describe(acc: Any, coord_type: Any = None) -> str:
    """Return a descriptive string of an accessible: (name, role, (x, y, w, h))."""
    if acc is None:
        return "None"
    name = safe(acc.get_name, "") or ""
    role = safe(acc.get_role_name, "") or ""
    bounds = get_element_bounds(acc, coord_type=coord_type)
    return str((name, role, bounds))


# ===========================================================================
# Candidate Data Structure
# ===========================================================================

@dataclass
class Candidate:
    """Represents a matched UI candidate element in the accessibility tree."""

    id: str
    name: str
    role: str
    path: str
    accessible: Any
    states: list[str] = field(default_factory=list)
    bounds: tuple[int, int, int, int] | None = None

    @property
    def node(self) -> Any:
        """Alias for the underlying Accessible node."""
        return self.accessible

    @property
    def key(self) -> str:
        """Standard identifier format '<id> | <path>' matching test.py."""
        return f"{self.id} | {self.path}"

    @property
    def center(self) -> tuple[int, int] | None:
        """Center coordinates (x, y) of the element if bounds are known."""
        if self.bounds and self.bounds[2] > 0 and self.bounds[3] > 0:
            return (self.bounds[0] + self.bounds[2] // 2, self.bounds[1] + self.bounds[3] // 2)
        return None

    def get_bounds(self, coord_type: Any = None) -> tuple[int, int, int, int] | None:
        """Retrieve bounding box, fetching lazily if not already populated."""
        if self.bounds is not None:
            return self.bounds
        self.bounds = get_element_bounds(self.accessible, coord_type=coord_type)
        return self.bounds

    def to_str(self, include_states: bool = True, include_bounds: bool = False) -> str:
        """Return a clean, human-readable string representation of this candidate."""
        parts = [self.key]
        if include_states and self.states:
            parts.append(f"[{','.join(self.states)}]")
        if include_bounds:
            b = self.get_bounds()
            if b:
                parts.append(f"({b[0]}, {b[1]}, {b[2]}, {b[3]})")
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert candidate to a serializable dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "path": self.path,
            "states": self.states,
            "bounds": self.bounds,
            "center": self.center,
        }

    def __getitem__(self, item: str) -> Any:
        """Allow dictionary-style attribute access (e.g. cand['name'])."""
        if hasattr(self, item):
            return getattr(self, item)
        if item in ("node", "element"):
            return self.accessible
        raise KeyError(item)

    def __str__(self) -> str:
        return self.to_str()


# ===========================================================================
# Snapshot Generation Counter
# ===========================================================================

_generation: int = 0


# ===========================================================================
# Major Function 1: get_candidates()
# ===========================================================================

def get_candidates(
    root: Any | None = None,
    action: str | None = None,
    role: str | None = None,
    name: str | None = None,
    depth: int = 50,
    max_nodes: int = 5000,
    *,
    event_name: str | None = None,
    include_bounds: bool = False,
) -> list[Candidate]:
    """Search and return a list of matching UI candidates from an accessibility tree.

    Adopts and optimizes the tree-walking strategy from ostrich/context/test.py:
    - Filters by action affordance, role, and name.
    - Prunes hidden / defunct branches early to minimize D-Bus queries.
    - Omit unnamed layout wrappers from path names for clean, compact output.

    Args:
        root: Root Accessible node to search. If None, resolves the active window.
        action: Affordance / event to match (e.g., 'click', 'toggle', 'select',
            'type', 'scroll', 'expand', 'collapse', 'focus', or None for any).
        role: Substring or exact role name filter (case-insensitive, e.g. 'button').
        name: Substring or exact element name filter (case-insensitive, e.g. 'Save').
        depth: Maximum recursion depth for tree traversal (default: 50).
        max_nodes: Safety limit on total nodes visited (default: 5000).
        event_name: Backwards-compatible alias for `action`.
        include_bounds: If True, pre-fetches coordinates for matched candidates.

    Returns:
        List of `Candidate` objects matching the specified criteria.
    """
    global _generation
    _generation += 1
    gen = _generation

    # Resolve root node (defaults to currently active desktop window)
    if root is None:
        root = find_active_window()
        if root is None:
            return []

    # Support event_name alias
    effective_action = action or event_name

    # Normalise query filters
    norm_role = role.strip().lower() if role else None
    norm_name = name.strip().lower() if name else None

    candidates: list[Candidate] = []
    n = 0  # Sequential element counter for this generation
    visited = 0

    def walk(node: Any, level: int, path: str) -> None:
        nonlocal n, visited
        if level >= depth or visited >= max_nodes:
            return

        child_count = safe(node.get_child_count, 0) or 0
        for i in range(child_count):
            if visited >= max_nodes:
                return

            child = safe(lambda: node.get_child_at_index(i))
            if child is None:
                continue

            visited += 1

            # Fetch state set once for this node
            ss = safe(child.get_state_set)
            if ss is None or ss.contains(S.DEFUNCT):
                continue

            # Prune hidden subtrees early
            is_showing = ss.contains(S.SHOWING) or ss.contains(S.VISIBLE)
            if not is_showing:
                continue

            n += 1
            cid = f"{gen}:{n}"

            # Basic node attributes
            elem_name = safe(child.get_name, "") or ""
            role_name = safe(child.get_role_name, "") or ""
            role_val = safe(child.get_role)

            # Build compact breadcrumb path (omit unnamed intermediate wrappers)
            label = f"{role_name}:{elem_name}" if elem_name else role_name
            child_path = f"{path} > {label}" if path else label

            # Filter 1: Action affordance
            action_ok = _matches_action(child, ss, role_val, effective_action)

            # Filter 2: Role filter (case-insensitive substring match)
            role_ok = True
            if norm_role:
                role_ok = norm_role in role_name.lower()

            # Filter 3: Name filter (case-insensitive substring match)
            name_ok = True
            if norm_name:
                name_ok = norm_name in elem_name.lower()

            # If all filters pass, record candidate
            if action_ok and role_ok and name_ok:
                states = [
                    s.value_nick
                    for s in safe(ss.get_states, []) or []
                    if hasattr(s, "value_nick") and s.value_nick in KEEP_STATES
                ]
                states.sort()

                bounds = get_element_bounds(child) if include_bounds else None

                cand = Candidate(
                    id=cid,
                    name=elem_name,
                    role=role_name,
                    path=child_path,
                    accessible=child,
                    states=states,
                    bounds=bounds,
                )
                candidates.append(cand)

            # Unnamed layout containers stay out of the path for compact hierarchy
            walk(child, level + 1, child_path if elem_name else path)

    walk(root, 0, "")
    return candidates


# ===========================================================================
# Major Function 2: get_candidates_str()
# ===========================================================================

def get_candidates_str(
    root: Any | None = None,
    action: str | None = None,
    role: str | None = None,
    name: str | None = None,
    depth: int = 50,
    max_nodes: int = 5000,
    *,
    candidates: list[Candidate] | dict[str, Any] | None = None,
    event_name: str | None = None,
    include_states: bool = True,
    include_bounds: bool = False,
    numbered: bool = True,
) -> str:
    """Format matching UI candidates into a clean, human-readable string.

    Can either format pre-computed candidates or directly execute a candidate
    search and format the results.

    Args:
        root: Root Accessible node to search (if candidates is not supplied).
        action: Interaction affordance filter ('click', 'toggle', 'type', etc.).
        role: Role name substring filter (e.g. 'button').
        name: Element name substring filter (e.g. 'Save').
        depth: Maximum recursion depth for tree traversal (default: 50).
        max_nodes: Safety limit on total nodes visited (default: 5000).
        candidates: Optional pre-existing list or dictionary of candidates.
            If passed as first positional arg, it is automatically detected.
        event_name: Backwards-compatible alias for `action`.
        include_states: Whether to append relevant state tags (e.g. '[enabled]').
        include_bounds: Whether to append coordinate bounds (x, y, w, h).
        numbered: Whether to prefix each item with a 1-based index (e.g. '1. ').

    Returns:
        Formatted multi-line string of candidates, or 'No matching elements.'.
    """
    # Allow passing candidates list/dict as first positional argument
    if candidates is None and isinstance(root, (list, dict)):
        candidates = root
        root = None

    # Fetch candidates if not already provided
    if candidates is None:
        resolved_cands = get_candidates(
            root=root,
            action=action,
            role=role,
            name=name,
            depth=depth,
            max_nodes=max_nodes,
            event_name=event_name,
            include_bounds=include_bounds,
        )
    elif isinstance(candidates, dict):
        # Convert legacy dict {"<id> | <path>": accessible} to Candidate objects
        resolved_cands = []
        for key, acc in candidates.items():
            parts = key.split(" | ", 1)
            cid = parts[0] if len(parts) > 1 else ""
            path = parts[1] if len(parts) > 1 else key
            states = get_element_states(acc) if include_states else []
            bounds = get_element_bounds(acc) if include_bounds else None
            resolved_cands.append(
                Candidate(
                    id=cid,
                    name=safe(acc.get_name, "") or "",
                    role=safe(acc.get_role_name, "") or "",
                    path=path,
                    accessible=acc,
                    states=states,
                    bounds=bounds,
                )
            )
    else:
        resolved_cands = candidates

    if not resolved_cands:
        return "No matching elements."

    lines: list[str] = []
    for i, cand in enumerate(resolved_cands):
        entry = cand.to_str(include_states=include_states, include_bounds=include_bounds)
        if numbered:
            lines.append(f"{i + 1}. {entry}")
        else:
            lines.append(entry)

    return "\n".join(lines)


# Convenient aliases
get_candidates_string = get_candidates_str
candidates_to_str = get_candidates_str


# ===========================================================================
# Legacy Compatibility Helper: get_candidates_dict()
# ===========================================================================

def get_candidates_dict(
    root: Any | None = None,
    action: str | None = None,
    role: str | None = None,
    name: str | None = None,
    depth: int = 50,
    max_nodes: int = 5000,
    *,
    event_name: str | None = None,
) -> dict[str, Any]:
    """Return dictionary of candidates keyed by '<id> | <path>' -> accessible node.

    Maintains 100% compatibility with the return format of ostrich.context.test.get_candidates.
    """
    cands = get_candidates(
        root=root,
        action=action,
        role=role,
        name=name,
        depth=depth,
        max_nodes=max_nodes,
        event_name=event_name,
    )
    return {c.key: c.accessible for c in cands}


__all__ = [
    "Candidate",
    "get_candidates",
    "get_candidates_str",
    "get_candidates_string",
    "candidates_to_str",
    "get_candidates_dict",
    "find_active_window",
    "describe",
    "get_element_bounds",
    "get_element_states",
    "CLICKABLE_ROLES",
    "TOGGLE_ROLES",
    "EDITABLE_ROLES",
    "SCROLL_ROLES",
    "KEEP_STATES",
]
