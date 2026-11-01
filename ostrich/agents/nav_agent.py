"""Navigation agent: everything the orchestrator needs to act on windows and UI elements.

  NavAgent.run_direct()   hand a short instruction straight to the Needle executor
  NavAgent.run_planned()  planner loop: resolve candidates -> pick -> "click at X, Y"

The orchestrator owns routing (what kind of command is this?). This module owns
execution (how do I carry it out?).
"""

import re
import time
from enum import Enum
from typing import Callable, Literal, Optional

import gi

gi.require_version("Atspi", "2.0")

import needle
from gi.repository import Atspi
from pydantic import BaseModel

from modules.tools.window import (
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,
)
from modules.tools.io import (
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,
    keyboard_press_key,
    keyboard_hotkey,
    keyboard_type_text,
)

from ..context.test import find_active_window, get_candidates
# --------------------------------------------------------------------------
# Needle executor (the micro-instruction runner)
# --------------------------------------------------------------------------
tools = [
    # Application / Window tools
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
    split_screen,

    # Mouse tools
    mouse_move,
    mouse_click,
    mouse_double_click,
    mouse_select,

    # Keyboard tools
    keyboard_type_text,
    keyboard_press_key,
    keyboard_hotkey,
]


def get_nav_agent():
    return needle.Needle(tools=tools, stateless=True)


# --------------------------------------------------------------------------
# Shared schema (the orchestrator imports ActionEnum from here)
# --------------------------------------------------------------------------
class ActionEnum(str, Enum):
    click = "click"
    toggle = "toggle"
    select = "select"
    expand = "expand"
    collapse = "collapse"
    type = "type"
    scroll = "scroll"
    focus = "focus"
    none = "none"  # no UI element operated (native API path)


class PlannerStep(BaseModel):
    step: Literal["resolve", "act", "ask"]
    target: Optional[str] = None  # resolve: element name words
    action: Optional[ActionEnum] = None  # resolve / act
    pick: Optional[int] = None  # act: 1-based number from the list
    question: Optional[str] = None  # ask


# Words in an element label that force a confirmation, whatever the model picked.
RISKY = {"close", "delete", "remove", "send", "shutdown", "quit", "overwrite"}

PLANNER_PROMPT = """You plan one UI step. Reply with JSON only, one step per turn.

Steps:
- {"step":"resolve","target":"<element name words>","action":"<click|toggle|select|expand|collapse|type|scroll|focus>"}
  Ask for candidate elements. Always do this first.
- {"step":"act","action":"<same set>","pick":N}
  After you receive a numbered list, choose the element that performs the command.
- {"step":"ask","question":"<short question>"}
  Only if no listed element plausibly does the command.

Rules:
- Never act before you have received a list. Never invent a number.
- Match meaning, not just exact words. Prefer a control that directly does the action.
- Ignore unrelated controls (Minimize, Close, Restore, Menu) unless the command asks for them.
- If the list says no elements, try one different target wording, then ask.
- Tags show state and position: [selected] is the current one, [2/3] is the 2nd of 3 siblings.
  "other", "next", "previous" mean a sibling that is not [selected].

Example:
Command: "create a new tab"
{"step":"resolve","target":"new tab","action":"click"}
(list: 1. push button:Find  2. push button:New Tab  3. toggle button:Menu)
{"step":"act","action":"click","pick":2}"""

# --------------------------------------------------------------------------
# Chains: dependent steps need observation between them, so they go to the planner.
# --------------------------------------------------------------------------
_CHAIN = re.compile(r"\b(?:and then|then|and|after that|afterwards)\b")


def is_chain(text: str) -> bool:
    return bool(_CHAIN.search(text.lower()))


def _ask_yes_no(label: str) -> bool:
    return input(f"Confirm '{label}'? (y/n) ").strip().lower() == "y"


# --------------------------------------------------------------------------
# Ranking helpers: name first, then type (role), then action fit
# --------------------------------------------------------------------------
_STOP = {"the", "a", "an", "to", "other", "another", "next", "previous", "last",
         "first", "second", "third", "this", "that", "it", "one"}
# type noun in the command -> AT-SPI role names it can mean (extend as needed)
_TYPE_ROLES = {
    "tab": {"page tab"},
    "button": {"push button", "toggle button"},
    "link": {"link"},
    "menu": {"menu", "menu item", "check menu item", "radio menu item"},
    "field": {"text", "entry", "password text", "combo box"},
    "input": {"text", "entry", "password text"},
    "box": {"text", "entry", "check box", "combo box"},
    "checkbox": {"check box"},
    "switch": {"toggle button", "switch"},
    "item": {"list item", "tree item", "table row", "menu item"},
    "row": {"table row", "list item", "tree item"},
}


def _words(text: str) -> set:
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def parse_target(target: Optional[str], app_words: set = frozenset()):
    """Split a target phrase into (name_tokens, type_roles).
    Type nouns ("tab", "button"), position words and the app's own name are not
    element names, so they are removed from the name tokens."""
    name_toks, roles = set(), set()
    for tok in _words(target):
        base = tok[:-1] if tok.endswith("s") and tok[:-1] in _TYPE_ROLES else tok
        if base in _TYPE_ROLES:
            roles |= _TYPE_ROLES[base]
        elif tok in _STOP or tok in app_words:
            continue
        else:
            name_toks.add(tok)
    return name_toks, roles


def action_fit(acc, action: str) -> int:
    """1 if the element natively supports the requested action, else 0."""
    try:
        ss = acc.get_state_set()
        if action == "select":
            return int(ss.contains(Atspi.StateType.SELECTABLE))
        if action == "click":
            iface = acc.get_action_iface()
            return int(iface is not None and Atspi.Action.get_n_actions(iface) > 0)
        if action == "toggle":
            return int(ss.contains(Atspi.StateType.CHECKABLE))
        if action in ("expand", "collapse"):
            return int(ss.contains(Atspi.StateType.EXPANDABLE))
        if action == "type":
            return int(ss.contains(Atspi.StateType.EDITABLE))
    except Exception:
        pass
    return 0


# Every element-operating action is a single left click at the pixel level.
# "select at X, Y" is read by the executor as a drag-select (mouse_select).
_PIXEL_VERB = {"click": "click", "select": "click", "toggle": "click",
               "expand": "click", "collapse": "click", "focus": "click"}


# --------------------------------------------------------------------------
# NavAgent
# --------------------------------------------------------------------------
class NavAgent:
    def __init__(
        self,
        client,
        executor=None,
        confirm: Optional[Callable[[str], bool]] = None,
        model: str = "local",
    ):
        self.client = client  # OpenAI-compatible client (planner model)
        self.executor = executor or get_nav_agent()  # Needle micro-instruction runner
        self.confirm = confirm or _ask_yes_no
        self.model = model
        self._resolved = []  # [(key, acc, (x, y))] from the latest resolve_context

    # ---- direct path ------------------------------------------------------
    def run_direct(self, instruction: str) -> Optional[str]:
        """Direct path: send the instruction to the executor, no element search."""
        if any(w in instruction.lower().split() for w in RISKY) and not self.confirm(instruction):
            print("Cancelled.")
            return None
        print(f"Direct> {instruction}")
        result = self.executor.run(instruction)
        print(f"Nav Agent> {result}")
        return result

    # ---- context resolution (tool for the planner; code-owned) ------------
    @staticmethod
    def _rank_key(key: str, name_toks: set, roles: set):
        """(name matches, exact name, type match). Uses the element's own "role:name"
        (last path segment) so a child does not inherit its parent's name."""
        label = key.split(" | ", 1)[1].split(" > ")[-1]
        role, _, name = label.partition(":")
        words = _words(name)
        return (
            len(name_toks & words),
            int(bool(name_toks) and words == name_toks),
            int(role.lower() in roles),
        )

    @staticmethod
    def _app_words(win) -> set:
        try:
            return _words(win.get_application().get_name())
        except Exception:
            return set()

    @staticmethod
    def _tags(acc) -> str:
        """'[selected] [2/3]': state and same-role sibling position, so siblings with
        near-identical names (three terminal tabs) can be told apart."""
        tags = []
        try:
            ss = acc.get_state_set()
            for st, label in (
                (Atspi.StateType.SELECTED, "selected"),
                (Atspi.StateType.CHECKED, "checked"),
                (Atspi.StateType.EXPANDED, "expanded"),
            ):
                if ss.contains(st):
                    tags.append(label)
            parent, role = acc.get_parent(), acc.get_role_name()
            if parent is not None:
                n = parent.get_child_count()
                if n <= 30:
                    same = [
                        i for i in range(n)
                        if (c := parent.get_child_at_index(i)) is not None and c.get_role_name() == role
                    ]
                    mine = acc.get_index_in_parent()
                    # position only matters when siblings can't be told apart by name
                    names = [(parent.get_child_at_index(i).get_name() or "").lower()[:20] for i in same]
                    # tag the whole group if any two members collide, so no sibling is left untagged
                    if len(same) > 1 and mine in same and len(set(names)) < len(names):
                        tags.append(f"{same.index(mine) + 1}/{len(same)}")
        except Exception:
            pass
        return " ".join(f"[{t}]" for t in tags)

    @staticmethod
    def _has_state(acc, state) -> bool:
        try:
            return bool(acc.get_state_set().contains(state))
        except Exception:
            return False

    def _click_at(self, acc, x: int, y: int):
        """Click with integers taken straight from code. Going through the text-to-tool-call
        model dropped or mangled them ("click at 1405, 67" became x=140, then no x at all)."""
        selectable = self._has_state(acc, Atspi.StateType.SELECTABLE)
        was_selected = self._has_state(acc, Atspi.StateType.SELECTED)
        result = mouse_click(x=int(x), y=int(y))
        print(f"Click> {result}")
        if selectable and not was_selected:
            time.sleep(0.3)  # let the UI update before re-reading the state
            if not self._has_state(acc, Atspi.StateType.SELECTED):
                print("Click did not select the element; it may have missed.")
        return result

    @staticmethod
    def _center(acc):
        """Screen-space centre of an element, or None if it has no usable extents."""
        try:
            r = acc.get_extents(Atspi.CoordType.SCREEN)
            if r.width <= 0 or r.height <= 0:
                return None
            return (r.x + r.width // 2, r.y + r.height // 2)
        except Exception:
            return None

    def resolve_context(self, target: Optional[str], action: str, limit: int = 15) -> str:
        """Walk the active window, rank candidates by name match, keep those with a
        usable position. Stores (key, acc, centre) in self._resolved and returns a
        numbered text list for the planner."""
        self._resolved = []
        win = find_active_window()
        if win is None:
            return "No active window."

        cands = get_candidates(win, action)
        if not cands:
            return "No matching elements."

        # Rank: name match, then exact name, then type (role), then native action fit.
        # Python's sort is stable, so remaining ties keep tree order.
        name_toks, roles = parse_target(target, self._app_words(win))
        rk = {k: self._rank_key(k, name_toks, roles) for k in cands}
        keys = sorted(cands, key=lambda k: rk[k], reverse=True)
        head = keys[: limit * 3]  # action fit costs D-Bus calls, so only for the head
        head.sort(key=lambda k: rk[k] + (action_fit(cands[k], action),), reverse=True)
        keys = head
        for k in keys:
            c = self._center(cands[k])
            if c is not None:
                self._resolved.append((k, cands[k], c))
            if len(self._resolved) >= limit:
                break

        if not self._resolved:
            return "No matching elements."
        return "\n".join(
            f"{i + 1}. {k.split(' | ', 1)[1]} {self._tags(acc)}".rstrip()
            for i, (k, acc, _) in enumerate(self._resolved)
        )

    # ---- planner loop -----------------------------------------------------
    def _plan(self, messages) -> Optional[PlannerStep]:
        r = self.client.beta.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=PlannerStep,
            temperature=0,
        )
        msg = r.choices[0].message
        if msg.parsed is None:
            print(f"Planner parse failed. Raw: {msg.content!r}")
        return msg.parsed

    def run_planned(
        self,
        user_input: str,
        action: str = "click",
        target: Optional[str] = None,
        max_rounds: int = 4,
    ) -> Optional[str]:
        """Planner loop: resolve candidates, let the model pick a number, build the
        coordinate instruction in code, risk-gate it, then run it."""
        print("Planning ....")
        messages = [
            {"role": "system", "content": PLANNER_PROMPT},
            {"role": "user", "content": f'Command: "{user_input}"\nHint: action={action}, target={target}'},
        ]
        self._resolved = []

        for _ in range(max_rounds):
            step = self._plan(messages)
            if step is None:
                break
            messages.append({"role": "assistant", "content": step.model_dump_json()})

            if step.step == "resolve":
                act = step.action.value if step.action else action
                print(f"Resolving: target={step.target or target!r} action={act}")
                listing = self.resolve_context(step.target or target, act)
                print(f"Candidates:\n{listing}")
                messages.append({"role": "user", "content": f"Elements:\n{listing}"})

            elif step.step == "act":
                if not self._resolved:
                    messages.append({"role": "user", "content": "Resolve first."})
                    continue
                if not step.pick or not (1 <= step.pick <= len(self._resolved)):
                    messages.append({"role": "user", "content": "Invalid number. Pick from the list."})
                    continue

                key, acc, (x, y) = self._resolved[step.pick - 1]
                verb = step.action.value if step.action else action
                verb = _PIXEL_VERB.get(verb, verb)  # "select at X, Y" would be read as a drag-select
                label = key.split(" | ", 1)[1].lower()

                # Risk gate: code-owned, runs regardless of model confidence.
                if any(w in label for w in RISKY) and not self.confirm(label):
                    print("Cancelled.")
                    return None

                instruction = f"{verb} at {x}, {y}"
                print(f"Instruction: {instruction}   [{label}]")
                if verb == "click":
                    return self._click_at(acc, x, y)  # bypass the model: no number copying
                result = self.executor.run(instruction)
                print(f"Nav Agent> {result}")
                if isinstance(result, dict) and not result.get("results"):
                    print("Executor did not act (low confidence or ungrounded arguments).")
                return result

            else:  # ask
                print(f"Agent> {step.question}")
                return None

        print("Could not plan this command; ask the user or rephrase.")
        return None