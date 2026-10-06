#!/usr/bin/env python3
"""
ui_nl.py - control the desktop with natural language (latency-optimized).

    python3 ui_nl.py "open settings and go to displays"
    python3 ui_nl.py --delay 3 "turn on night light"
    python3 ui_nl.py --dry-run "search for sound"
    python3 ui_nl.py                                   # interactive prompt

What makes this version fast:
  * Direct google-genai SDK (no crewai/litellm import + wrapper overhead).
    Falls back to crewai automatically if google-genai is not installed.
  * Minimal thinking (thinking_level="minimal"; thinking_budget=0 on 2.5 models).
  * Output is only {"actions":[...]} - no "thought" -> fewer generated tokens.
  * STREAMING + PIPELINING: actions are parsed out of the token stream and executed
    the moment each one is complete, so execution overlaps with generation.
  * Client import / TLS connection is warmed up in the background while the
    AT-SPI tree is captured.
  * Smaller UI tree (fewer nodes, shorter names, no coordinates by default).

Setup:
    pip install google-genai          # (crewai still works as a fallback)
    export GEMINI_API_KEY=...
Env: UI_LLM_MODEL, UI_LLM_EFFORT (minimal|low|medium|high), UI_TREE_COORDS=1
"""

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import traceback
from typing import Any, Dict, Iterator, List, Optional, Tuple

import pyatspi

from .linux_backend import (AppWindow, LinuxUIManager, children, get_extents,
                              has_state, role_name, safe, text_of)

from config.vars import vars

DEFAULT_MODEL = os.environ.get("UI_LLM_MODEL", "gemini/gemini-3.5-flash")
REASONING_EFFORT = os.environ.get("UI_LLM_EFFORT", "minimal")
TREE_COORDS = os.environ.get("UI_TREE_COORDS", "0") == "1"
MAX_TREE_NODES = int(os.environ.get("UI_TREE_NODES", "250"))
# Per-click wait-for timeout: reduced from 8s CLI default so failed lookups fail fast.
CLICK_TIMEOUT = float(os.environ.get("UI_CLICK_TIMEOUT", "2.5"))

ALLOWED: Dict[str, set] = {
    "open_app":        {"query"},
    "activate_window": {"id"},
    "launch_app":      {"name"},
    "click":           {"name", "role", "nth", "match", "method"},
    "set_text":        {"text", "name", "role", "nth"},
    "click_xy":        {"x", "y"},
    "wait":            {"seconds"},
    "done":            {"message"},
}

# XML prompt: unambiguous structure, fewer tokens, explicit decision tree before action generation.
SYSTEM_PROMPT = """<role>Desktop automation agent for Linux GNOME/Wayland. Emit fewest correct actions to complete TASK.</role>

<inputs>
  TASK         — what to do
  WINDOWS      — id · wm_class · title of every open window
  UI_TREE      — visible/interactive elements of the active window
  ALREADY_DONE — steps already executed (do not repeat)
</inputs>

<decide>
  Classify before planning — pick the first that fits:
  1. Wrong app focused or app not open → open_app(query) or activate_window(id) first, then click
  2. Target element visible in UI_TREE  → click with its EXACT name from UI_TREE
  3. Target not yet visible (appears after navigation) → use known app labels; click() waits automatically
  4. None fit → done(reason)
  State a one-line assumption if you infer anything not explicit in TASK.
</decide>

<actions>
  open_app(query)                  focus/launch: "settings" "firefox" "code" "nautilus" …
  activate_window(id)              focus window by id from WINDOWS
  launch_app(name)                 start app without AT-SPI attach
click(name,role?,nth?,match?)    click by name; case-insensitive prefix default
                                   role  = OMIT unless two elements share the same name;
                                           then copy the role exactly as shown in that
                                           UI_TREE line, e.g. [push button] -> "push button"
  set_text(text,name?,role?,nth?)  type into editable field
  click_xy(x,y)                    last resort: absolute pixel
  wait(seconds)                    only for known-slow transitions
  done(message)                    task complete or impossible
</actions>

<rules>
  - One plan, whole task — you will not be called again.
  - Element names: exact match from UI_TREE only; never invent.
  - Skip every step listed in ALREADY_DONE.
  - Ignore the terminal window if it is focused.
  - role/name must be copied from a UI_TREE line. Never infer a role from how the element looks.
</rules>

<output>JSON only — no markdown, no extra keys:
{"actions":[{"fn":"open_app","query":"settings"},{"fn":"click","name":"Displays"}]}
</output>"""


# --------------------------------------------------------------------------- #
# LLM layer
# --------------------------------------------------------------------------- #
class ActionStreamParser:
    """Incrementally pull complete {...} objects out of the "actions":[ ... ] array
    while the JSON is still being generated."""

    def __init__(self):
        self.buf = ""
        self.pos = 0
        self.in_actions = False
        self.depth = 0
        self.in_str = False
        self.esc = False
        self.obj_start: Optional[int] = None

    def feed(self, chunk: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        self.buf += chunk
        i = self.pos
        if not self.in_actions:
            m = re.search(r'"actions"\s*:\s*\[', self.buf)
            if not m:
                return out
            i = m.end()
            self.in_actions = True
        buf = self.buf
        while i < len(buf):
            c = buf[i]
            if self.in_str:
                if self.esc:
                    self.esc = False
                elif c == "\\":
                    self.esc = True
                elif c == '"':
                    self.in_str = False
            elif c == '"':
                self.in_str = True
            elif c == "{":
                if self.depth == 0:
                    self.obj_start = i
                self.depth += 1
            elif c == "}":
                self.depth -= 1
                if self.depth == 0 and self.obj_start is not None:
                    try:
                        out.append(json.loads(buf[self.obj_start:i + 1]))
                    except ValueError:
                        pass
                    self.obj_start = None
            i += 1
        self.pos = i
        return out


_GENAI: Dict[str, Tuple[Any, str, Any]] = {}
_GENAI_LOCK = threading.Lock()
_CREW_CACHE: Dict[str, Any] = {}


def _have_genai() -> bool:
    try:
        import google.genai  # noqa: F401
        return True
    except ImportError:
        return False


def _genai_config(types, name: str):
    kw = dict(system_instruction=SYSTEM_PROMPT, max_output_tokens=768,
              response_mime_type="application/json")
    effort = REASONING_EFFORT.lower()
    try:
        if "2.5" in name:
            tc = types.ThinkingConfig(thinking_budget=0 if effort in ("none", "minimal") else 1024)
        else:
            tc = types.ThinkingConfig(thinking_level=effort.upper())
        return types.GenerateContentConfig(thinking_config=tc, **kw)
    except Exception:  # older SDK without thinking_level
        return types.GenerateContentConfig(**kw)


def _genai_client(model: str):
    with _GENAI_LOCK:
        if model not in _GENAI:
            from google import genai
            from google.genai import types
            name = model.split("/", 1)[-1]
            client = genai.Client(api_key=vars['GEMINI_API_KEY'])
            _GENAI[model] = (client, name, _genai_config(types, name))
        return _GENAI[model]


def _crew_llm(model: str):
    if model not in _CREW_CACHE:
        from crewai import LLM
        _CREW_CACHE[model] = LLM(model=model, reasoning_effort=REASONING_EFFORT, max_tokens=1024)
    return _CREW_CACHE[model]


def prewarm(model: str) -> threading.Thread:
    """Import SDK + open the TLS connection while we capture the UI tree."""
    def work():
        try:
            if _have_genai():
                _genai_client(model)  # imports SDK + creates client; TLS opens on first real call
            else:
                _crew_llm(model)
        except Exception:
            pass
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def parse_plan(raw: str) -> Dict[str, Any]:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"No JSON in model output: {raw[:200]!r}")
    plan = json.loads(raw[start:end + 1])
    if not isinstance(plan.get("actions"), list):
        raise ValueError("Plan has no 'actions' list")
    return plan


def llm_actions(system: str, user: str, model: str) -> Iterator[Dict[str, Any]]:
    """Yield actions as soon as each one is fully generated."""
    if _have_genai():
        client, name, cfg = _genai_client(model)
        parser = ActionStreamParser()
        got = 0
        try:
            for chunk in client.models.generate_content_stream(model=name, contents=user, config=cfg):
                text = chunk.text
                if text:
                    for act in parser.feed(text):
                        got += 1
                        yield act
        except Exception:
            if got:
                raise
            traceback.print_exc()
            print("  (streaming failed, retrying without streaming)", file=sys.stderr)
            resp = client.models.generate_content(model=name, contents=user, config=cfg)
            yield from parse_plan(resp.text or "")["actions"]
    else:  # crewai fallback (no streaming)
        out = _crew_llm(model).call([{"role": "system", "content": system},
                                     {"role": "user", "content": user}])
        yield from parse_plan(out if isinstance(out, str) else str(out))["actions"]


def start_plan(system: str, user: str, model: str) -> Tuple[Iterator[Dict[str, Any]], Dict[str, float]]:
    """Run the LLM in a thread; return (iterator of actions, timing stats).
    The thread keeps draining the stream while the main thread executes actions,
    so the stats reflect true LLM time."""
    q: "queue.Queue[Any]" = queue.Queue()
    stats: Dict[str, float] = {}

    def worker():
        t0 = time.time()
        try:
            for a in llm_actions(system, user, model):
                stats.setdefault("first", time.time() - t0)
                q.put(a)
        except Exception as e:
            traceback.print_exc()
            q.put(e)
        finally:
            stats["total"] = time.time() - t0
            q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def gen():
        while True:
            item = q.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item
    return gen(), stats


# --------------------------------------------------------------------------- #
# Context capture
# --------------------------------------------------------------------------- #
SKIP_ROLES = {"frame", "window", "filler", "panel", "scroll pane", "viewport", "separator",
              "section", "layered pane", "redundant object", "unknown", "application",
              "split pane", "tool bar", "menu bar", "list", "table", "tree table", "tree"}
INPUT_ROLES = {"text", "entry", "password text", "check box", "toggle button", "combo box",
               "slider", "spin button", "switch", "radio button", "search box"}


def compact_tree(ui: LinuxUIManager, root, max_nodes: int = MAX_TREE_NODES, max_depth: int = 30) -> str:
    """One line per visible, meaningful element:  [role] "name" (flags)"""
    lines: List[str] = []

    def walk(node, depth):
        if len(lines) >= max_nodes or depth > max_depth:
            return
        if depth > 0 and not has_state(node, pyatspi.STATE_SHOWING):
            return
        rn = role_name(node)
        name = " ".join(text_of(node).split())[:45]
        if rn in INPUT_ROLES or (name and rn not in SKIP_ROLES):
            flags = [f for f, s in (("selected", pyatspi.STATE_SELECTED),
                                    ("checked", pyatspi.STATE_CHECKED),
                                    ("focused", pyatspi.STATE_FOCUSED),
                                    ("editable", pyatspi.STATE_EDITABLE)) if has_state(node, s)]
            if not has_state(node, pyatspi.STATE_ENABLED):
                flags.append("disabled")
            pos = ""
            if TREE_COORDS:
                ext = get_extents(node, ui.coord_type)
                pos = f" @{ext[0]},{ext[1]}" if ext else ""
            line = f'[{rn}] "{name}"{pos}' + (f" ({','.join(flags)})" if flags else "")
            if not lines or lines[-1] != line:
                lines.append(line)
        for c in children(node):
            walk(c, depth + 1)

    walk(root, 0)
    return "\n".join(lines) if lines else "(empty)"


def _is_own_terminal(win_pid: Optional[int]) -> bool:
    if not win_pid:
        return False
    pid = os.getpid()
    for _ in range(30):
        try:
            with open(f"/proc/{pid}/stat") as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except Exception:
            return False
        if pid == win_pid:
            return True
        if pid <= 1:
            return False
    return False


def attach(ui: LinuxUIManager, win: Dict[str, Any]) -> Optional[AppWindow]:
    title = win.get("title") or ui.get_title(win["id"])
    root = ui._find_atspi_window(win, title, timeout=1)
    if root is None:
        return None
    return AppWindow(id=win["id"], title=title, pid=win.get("pid"), info=win,
                     root=root, coord_type=ui.coord_type)


def capture_context(ui: LinuxUIManager, fallback_app: Optional[AppWindow]
                    ) -> Tuple[str, Optional[AppWindow]]:
    windows = ui.list_windows()
    focused = next((w for w in windows if w.get("focus")), None)

    app = None
    if focused and not _is_own_terminal(focused.get("pid")):
        app = attach(ui, focused)
    if app is None:
        app = fallback_app

    win_lines = [f'  id={w["id"]} class={w.get("wm_class")!r} title={(w.get("title") or ui.get_title(w["id"]))!r}'
                 + (" [FOCUSED]" if w.get("focus") else "") for w in windows]
    tree = compact_tree(ui, app.root) if app else "(no accessible active window)"
    active = f'{app.title!r} (class {app.info.get("wm_class")!r})' if app else "none"
    ctx = ("WINDOWS:\n" + "\n".join(win_lines)
           + f"\n\nACTIVE WINDOW: {active}\nUI TREE:\n{tree}")
    return ctx, app

def print_tree(ui: LinuxUIManager, app: Optional[AppWindow], label: str) -> None:
    if app is None:
        print(f"--- tree ({label}): no accessible window ---")
        return
    print(f"--- tree ({label}): {app.title!r} class={app.info.get('wm_class')!r} ---")
    print(compact_tree(ui, app.root))
    print("---------------")


# --------------------------------------------------------------------------- #
# Executor: JSON action -> LinuxUIManager call (accepts a lazy iterator)
# --------------------------------------------------------------------------- #
def _fmt(a: Dict[str, Any]) -> str:
    return f'{a.get("fn")}(' + ", ".join(f"{k}={v!r}" for k, v in a.items() if k != "fn") + ")"


def execute(ui: LinuxUIManager, app: Optional[AppWindow], actions: Iterator[Dict[str, Any]],
            done_log: List[str]) -> Tuple[bool, Optional[AppWindow]]:
    it = iter(actions)
    i = 0
    while True:
        try:
            a = next(it)
        except StopIteration:
            break
        except Exception as e:
            print(f"  LLM error: {e}")
            return False, app
        i += 1
        fn = a.get("fn")
        args = {k: v for k, v in a.items() if k != "fn"}
        print(f"  {i}. {_fmt(a)}", flush=True)
        if fn not in ALLOWED or not set(args) <= ALLOWED[fn]:
            print("     rejected: unknown action or parameters")
            return False, app
        try:
            ok = True
            if fn == "open_app":
                app = ui.open_app(args["query"])
                print_tree(ui, app, "after open_app")
            elif fn == "activate_window":
                ok = ui.activate_window(args["id"])
                win = next((w for w in ui.list_windows() if w["id"] == args["id"]), None)
                app = attach(ui, win) if win else app
                print_tree(ui, app, "after activate_window")
            elif fn == "launch_app":
                ok = ui.launch_app(args["name"])
                time.sleep(1)
            elif fn == "wait":
                time.sleep(float(args.get("seconds", 1)))
            elif fn == "click_xy":
                ok = ui.click(int(args["x"]), int(args["y"]))
            elif fn in ("click", "set_text") and app is None:
                print("     no app attached; use open_app first")
                return False, app
            elif fn == "click":
                kw = dict(match=args.get("match", "startswith"),
                        nth=int(args.get("nth", 0)),
                        timeout=CLICK_TIMEOUT,
                        method=args.get("method", "auto"))
                ok = ui.click_by_name(app, args["name"], role=args.get("role"), **kw)
                if not ok and args.get("role"):
                    print("     retrying without role")
                    ok = ui.click_by_name(app, args["name"], role=None, **kw)
            elif fn == "set_text":
                hits = ui.find_elements(app.root, args.get("name"), args.get("role"), climb=False)
                nth = int(args.get("nth", 0))
                ok = len(hits) > nth and ui.set_text(app, hits[nth], args["text"])
            elif fn == "done":
                print(f"     {args.get('message', '')}")
        except Exception as e:
            print(f"     error: {e}")
            ok = False
        if not ok:
            print("     FAILED, stopping.")
            return False, app
        done_log.append(_fmt(a))
    if i == 0:
        print("  (model returned an empty plan)")
        return False, app
    return True, app


# --------------------------------------------------------------------------- #
# Main loop
# --------------------------------------------------------------------------- #
def run_task(task: str, ui: LinuxUIManager, model: str, dry_run: bool, confirm: bool,
             show_context: bool, replan: bool) -> bool:
    t_start = time.time()
    warm = prewarm(model)            # SDK import + TLS handshake, in parallel with capture
    if not dry_run:
        ui.warm_up()
    app: Optional[AppWindow] = None
    history: List[str] = []
    for attempt in range(2 if replan else 1):
        t_ctx = time.time()
        ctx, app = capture_context(ui, app)
        t_ctx = time.time() - t_ctx
        if show_context:
            print(f"--- context ---\n{ctx}\n---------------")
        user = f"TASK: {task}\n\n{ctx}"
        if history:
            user += ("\n\nALREADY DONE:\n" + "\n".join(f"  {h}" for h in history)
                     + "\nThe next step failed. Plan the remaining steps.")

        warm.join(timeout=3)
        gen, stats = start_plan(SYSTEM_PROMPT, user, model)

        if dry_run or confirm:
            try:
                actions = list(gen)
            except Exception as e:
                print(f"LLM error: {e}")
                return False
            print(f"\nplan: {len(actions)} actions (context {t_ctx:.1f}s, LLM {stats.get('total', 0):.1f}s)")
            for a in actions:
                print(f"    -> {_fmt(a)}")
            if dry_run:
                return True
            if input("Run these actions? [y/N] ").strip().lower() != "y":
                return False
            gen = iter(actions)

        t1 = time.time()
        print(f"\n(context {t_ctx:.1f}s) executing as the plan streams in...")
        ok, app = execute(ui, app, gen, history)
        print(f"Finished in {time.time() - t_start:.1f}s "
              f"(context {t_ctx:.1f}s, LLM first action {stats.get('first', 0):.1f}s / "
              f"total {stats.get('total', 0):.1f}s, execution wall {time.time() - t1:.1f}s)")
        if ok:
            return True
    return False


def main():
    p = argparse.ArgumentParser(description="Natural-language desktop control.")
    p.add_argument("task", nargs="*", help="what to do (omit for interactive mode)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--delay", type=float, default=0, help="seconds to wait before capturing (focus your target app)")
    p.add_argument("--replan", action="store_true", help="if a step fails, plan the rest once more")
    p.add_argument("--dry-run", action="store_true", help="print the plan only")
    p.add_argument("--confirm", action="store_true", help="ask before executing each plan")
    p.add_argument("--show-context", action="store_true", help="print what the LLM sees")
    p.add_argument("--debug", action="store_true")
    a = p.parse_args()

    prewarm(a.model)  # start importing the SDK immediately, even during --delay
    if a.delay:
        print(f"Capturing in {a.delay:g}s...")
        time.sleep(a.delay)

    with LinuxUIManager(debug=a.debug) as ui:
        if a.task:
            sys.exit(0 if run_task(" ".join(a.task), ui, a.model, a.dry_run,
                                   a.confirm, a.show_context, a.replan) else 1)
        while True:
            try:
                task = input("\nui> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if task in ("", "q", "quit", "exit"):
                break
            run_task(task, ui, a.model, a.dry_run, a.confirm, a.show_context, a.replan)


if __name__ == "__main__":
    main()