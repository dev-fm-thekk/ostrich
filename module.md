# Ostrich Codebase Architecture & Module Specification

## 1. Architectural Overview

Ostrich is a cross-platform desktop AI agent designed to execute high-level user instructions on Linux and Windows desktop environments. The architecture separates concerns into distinct layers:

1. **Tools Layer (`modules/tools`)**: Modular, platform-agnostic OS abstraction layer providing primitives for window management, mouse & keyboard I/O, system controls, and filesystem interactions.
2. **Context Layer (`modules/context`)**: Real-time environmental observation layer providing accessibility tree (AT-SPI) inspection, element resolution, and token-efficient state serialization.
3. **Configuration Layer (`config`)**: Model connection factories (local Qwen2.5 1.4B via OpenAI API, Needle executor wrappers) and prompt specifications.
4. **Agents Layer (`modules/agents`)**: Closed-loop orchestration and specialized delegate execution agents.

```
                           +----------------------+
                           |   User Instruction   |
                           +----------+-----------+
                                      |
                                      v
                           +----------------------+
                           |     Orchestrator     |<--------------+
                           |   (Qwen2.5 1.4B)     |               |
                           +----------+-----------+               |
                                      |                           |
                +---------------------+---------------------+     | Feedback
                | Updates State & Dispatches Tasks          |     | Loop
                v                                           v     |
+-------------------------------+           +---------------------+-----+
|       Shared State Pool       |           |     Delegate Agents       |
| (History, Blackboard, Status) |           |  (Powered by Needle)      |
+-------------------------------+           +-------------+-------------+
                ^                                         |
                | Reads / Writes                          v
                |                           +---------------------------+
                +---------------------------| Context | UI | IO | Sys | |
                                            | Agent   | Ag | Ag | Ag  | |
                                            +-------------+-------------+
                                                          |
                                                          v
                                            +---------------------------+
                                            |       modules/tools       |
                                            | (Window, IO, System, File)|
                                            +---------------------------+
```

---

## 2. Module Specifications

### 2.1 `modules/tools` (Tools Layer)

The `modules/tools` package serves as the unified interface to operating system functions. Every subpackage follows the Abstract Base Class (ABC) pattern with platform-specific subclasses for Linux and Windows, unified by OS-detecting factory getters and Needle tool decorators.

#### 2.1.1 `modules.tools.window`
- **Purpose**: Desktop application launching and window state manipulation.
- **Key Features**:
  - Launch applications by name, binary path, or desktop alias with optional command arguments.
  - Enumerate visible windows with normalized titles, process IDs (PID), and geometric window bounds.
  - Switch active window focus by title match, window ID, or PID.
  - Maximize, minimize, and restore windows.
  - Split screen: tile two windows side-by-side (left/right screen split).
- **Major Exports**:
  - Classes: `DesktopNavigator` (ABC), `LinuxDesktopNavigator`, `WindowsDesktopNavigator`
  - Factory: `get_desktop_navigator() -> DesktopNavigator`
  - Tool Functions: `open_app(app_name, args)`, `list_windows()`, `switch_window(title)`, `maximize_window(title)`, `minimize_window(title)`, `split_screen(left_target, right_target)`
- **Dependencies**:
  - *Internal*: `ostrich.context.app_aliases.resolve_app_name` (optional app name alias resolution).
  - *External*: `needle` (optional tool registration).
  - *OS/System*:
    - Linux: `gdbus` (GNOME Shell Introspect / Eval), `wmctrl`, `xdotool`, `xrandr`.
    - Windows: `powershell`, Win32 API (`user32.dll`).

#### 2.1.2 `modules.tools.io`
- **Purpose**: Low-level mouse and keyboard input simulation.
- **Key Features**:
  - Unified input navigator (`IONavigator`) combining mouse and keyboard capabilities.
  - Mouse: absolute cursor movement with smooth ease-in ease-out gliding curve, single/double click (left, right, middle buttons), and drag-selection.
  - Keyboard: text typing with shell escaping, single key pressing, and multi-key hotkey combinations (e.g. `ctrl+c`).
- **Major Exports**:
  - Classes: `IONavigator` (ABC), `MouseNavigator` (ABC), `KeyboardNavigator` (ABC), `LinuxIONavigator`, `WindowsIONavigator`
  - Aliases: `LinuxMouseNavigator`, `LinuxKeyboardNavigator`, `WindowsMouseNavigator`, `WindowsKeyboardNavigator`
  - Factories: `get_io_navigator() -> IONavigator`, `get_mouse_navigator() -> MouseNavigator`, `get_keyboard_navigator() -> KeyboardNavigator`
  - Tool Functions:
    - Mouse: `mouse_move(x, y)`, `mouse_click(x, y, button)`, `mouse_double_click(x, y, button)`, `mouse_select(start_x, start_y, end_x, end_y)`
    - Keyboard: `keyboard_type_text(text)`, `keyboard_press_key(key)`, `keyboard_hotkey(*keys)`
- **Dependencies**:
  - *External*: `evdev` (Linux virtual input device creation), `needle` (optional tool registration).
  - *OS/System*:
    - Linux: `/dev/uinput` (UInput virtual device), `libX11.so.6` (cursor coordinate queries), `ydotool` (keyboard daemon/cli).
    - Windows: `ctypes.windll.user32` (`SetCursorPos`, `mouse_event`).

#### 2.1.3 `modules.tools.system`
- **Purpose**: Hardware metrics, system environment inspection, and device controls.
- **Key Features**:
  - Hardware info: OS name, kernel, hostname, CPU count & usage, memory utilization, disk usage.
  - Audio: query output volume level, set volume (0-100%), toggle or set mute state.
  - Display: query display brightness (0-100%), set brightness.
  - Network: query Wi-Fi status, toggle Wi-Fi radio, scan nearby SSIDs, connect/disconnect networks.
  - Bluetooth: query adapter status & connected peripherals, toggle power.
  - Power: inspect battery percentage and charging state.
  - Security: lock user session.
- **Major Exports**:
  - Classes: `SystemNavigator` (ABC), `LinuxSystemNavigator`, `WindowsSystemNavigator`
  - Factory: `get_system_navigator() -> SystemNavigator`
  - Tool Functions: `get_system_info()`, `get_volume()`, `set_volume(level)`, `set_mute(mute)`, `mute_volume()`, `get_brightness()`, `set_brightness(level)`, `get_wifi_status()`, `set_wifi(enabled)`, `scan_wifi()`, `connect_wifi(ssid, password)`, `disconnect_wifi(ssid)`, `get_bluetooth_status()`, `set_bluetooth(enabled)`, `get_battery_status()`, `lock_screen()`
- **Dependencies**:
  - *External*: `psutil` (optional metrics), `needle` (optional tool registration).
  - *OS/System*:
    - Linux: `nmcli`, `bluetoothctl`, `rfkill`, `amixer`/`wpctl`, `brightnessctl`, `/sys/class/power_supply`, `loginctl`/`xdg-screensaver`.
    - Windows: `powershell` (CIM/WMI queries), `netsh`, C# inline audio helper.

#### 2.1.4 `modules.tools.file`
- **Purpose**: Local filesystem navigation and file queries.
- **Key Features**: Directory listing with error isolation.
- **Major Exports**:
  - Classes: `FileNavigator` (ABC), `LinuxFileNavigator`, `WindowsFileNavigator`
  - Factory: `get_file_navigator() -> FileNavigator`
  - Tool Functions: `list_files(path)`
- **Dependencies**:
  - *Standard Library*: `os`, `pathlib`
  - *External*: `needle` (optional tool registration).

#### 2.1.5 `modules.tools` (Aggregator Root)
- **Purpose**: Single point of import for agents, bundling subpackage navigators and pre-defined tool suites:
  - `window_tools`: All window management functions.
  - `mouse_tools`: All mouse interaction functions.
  - `keyboard_tools`: All keyboard interaction functions.
  - `io_tools`: Mouse + Keyboard tools combined.
  - `system_tools`: System controls and inspection tools.
  - `file_tools`: Filesystem tools.
  - `all_tools`: Complete registry of all agent-executable tools.

---

### 2.2 `modules/context` (Context Layer)

#### 2.2.1 `modules.context.ui_tree.tree`
- **Purpose**: Accessibility tree (AT-SPI) traversal, UI grounding, and candidate element filtering.
- **Key Features**:
  - Traverses the desktop application accessibility tree starting from the active window or target node.
  - Early branch pruning: safely discards defunct, invisible, or non-showing nodes.
  - Fast in-memory affordance matching: evaluates role enum sets and bitset states before making D-Bus IPC calls.
  - Multi-dimensional search: filter candidates by `action` (click, toggle, select, type, scroll, expand, focus), `role` (button, tab, text, etc.), and `name`.
  - Compact path hierarchy: omits intermediate unnamed container wrappers (box, filler, layout).
  - Serialized string output: outputs structured, token-efficient lists for LLM context prompts with state flags (`[enabled,selected]`) and coordinates.
- **Major Exports**:
  - Data Class: `Candidate` (with `id`, `name`, `role`, `path`, `accessible`, `states`, `bounds`, `center`, `key`)
  - Query Functions: `get_candidates(root, action, role, name, depth, max_nodes, include_bounds)`
  - String Formatters: `get_candidates_str(...)`, `get_candidates_string(...)`, `candidates_to_str(...)`
  - Compatibility Dict Getter: `get_candidates_dict(...)`
  - Inspection Helpers: `find_active_window()`, `describe(acc)`, `get_element_bounds(acc)`, `get_element_states(acc)`
  - Role Sets: `CLICKABLE_ROLES`, `TOGGLE_ROLES`, `EDITABLE_ROLES`, `SCROLL_ROLES`, `KEEP_STATES`
- **Dependencies**:
  - *External*: `gi.repository` (`Atspi`, `GLib`).
  - *OS/System*: Linux AT-SPI D-Bus accessibility daemon (`at-spi2-core`).

---

### 2.3 `config` (Configuration Layer)

#### 2.3.1 `config.models`
- **Purpose**: Factory functions for language model clients and Needle execution runtimes.
- **Major Exports**:
  - `get_openai_client() -> OpenAI`: Instantiates OpenAI client pointing to the local inference server (`http://localhost:8080/v1`).
  - `get_needle_model(tools: list) -> needle.Needle`: Instantiates a stateless Needle execution runner with injected tool suites.

#### 2.3.2 `config.prompts`
- **Purpose**: Centralized prompt templates for orchestrator and delegate agents.
- **Major Exports**:
  - `ORCHESTRATION_AGENT_INSTRUCTION`: System instruction and JSON schema definition for the Qwen2.5 1.4B orchestrator.
  - `CONTEXT_AGENT_INSTRUCTION`: System instruction for context resolution and visual element grounding.

---

### 2.4 Dependency Matrix

| Module | Internal Dependencies | External Libraries | System / OS Services |
|---|---|---|---|
| `modules.tools.window` | `ostrich.context.app_aliases` (optional) | `needle` (optional) | `gdbus`, `wmctrl`, `xdotool`, Win32 API |
| `modules.tools.io` | None | `evdev` (Linux), `needle` (optional) | `/dev/uinput`, `libX11`, `ydotool`, Win32 `user32` |
| `modules.tools.system` | None | `psutil` (optional), `needle` (optional) | `nmcli`, `bluetoothctl`, `amixer`, `wpctl`, `brightnessctl`, PowerShell |
| `modules.tools.file` | None | `needle` (optional) | POSIX / Win32 Filesystem |
| `modules.tools` | `window`, `io`, `system`, `file` | `needle` (optional) | Aggregates underlying tool requirements |
| `modules.context.ui_tree` | None | `PyGObject` (`gi.repository.Atspi`) | AT-SPI2 D-Bus daemon (`org.a11y.Bus`) |
| `config.models` | None | `openai`, `needle` | Local model endpoint (`localhost:8080`) |
