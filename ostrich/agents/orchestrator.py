"""
Orchestrator: classify the command, then hand it to the right agent.

  classifier says system_agent / action == none (not a chain)  ->  direct
  everything else (click/toggle/select on an element, chains)  ->  nav.run_planned

Execution details (planner loop, AT-SPI resolution, risk gate) live in nav_agent.py.
Untested paper design: run against real weights and a real AT-SPI session.
"""

from enum import Enum
from typing import Optional

from openai import OpenAI
from pydantic import BaseModel, Field

from .nav_agent import ActionEnum, NavAgent, is_chain
from .system_agent import get_system_agent


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------
class AgentEnum(str, Enum):
    system_agent = "system_agent"
    navigation_agent = "navigation_agent"
    file_agent = "file_agent"


class AgentResolution(BaseModel):
    # Field order matters: the model generates top to bottom.
    agent_type: AgentEnum
    action: ActionEnum
    target: Optional[str] = Field(None, description="element name words only, no articles")
    value: Optional[str] = Field(None, description="number or text to set or type, copied from the command")


class AgentState:
    def __init__(self):
        self.agent_type: Optional[AgentEnum] = None
        self.action: Optional[ActionEnum] = None
        self.target: Optional[str] = None
        self.value: Optional[str] = None
        self.direct: bool = False  # True -> skip the planner


SYSTEM_PROMPT = """
<router>
  <task>
    Classify the user command and return JSON only.
    Never execute the command or explain the classification.
  </task>

  <schema>
    {"agent_type":"system_agent|navigation_agent|file_agent",
     "action":"click|toggle|select|expand|collapse|type|scroll|focus|none",
     "target":"string|null",
     "value":"string|null"}
  </schema>

  <agents>
    <navigation_agent>
      Apps: launch, open, close.
      Windows: minimize, maximize, restore, resize, move,
      split-screen, switch, focus.
      Tabs: create, close, switch, select.
      Input: mouse movement/clicks/scroll, keyboard typing,
      key presses, shortcuts, hotkeys.
      General: interact with application UI.
    </navigation_agent>

    <file_agent>
      Files and directories: create, delete, rename, move,
      copy, find, search, read, write, modify.
      File operations belong here even when the target is a file.
      Clicking a file in a file manager belongs to navigation_agent.
    </file_agent>

    <system_agent>
      Volume, brightness, media playback, Wi-Fi, Bluetooth,
      power, shutdown, restart, suspend, lock, logout.
    </system_agent>
  </agents>

  <actions>
    click: activate UI element; press key; execute shortcut.
    toggle: enable, disable, turn on/off.
    select: choose item, option, tab, or list entry.
    expand: expand menu, section, or tree node.
    collapse: collapse menu, section, or tree node.
    type: enter exact text into an input.
    scroll: scroll a UI region.
    focus: focus an app, window, or UI element.
    none: operation does not act on a UI element.
  </actions>

  <extraction>
    agent_type: choose agent by responsibility.
    action: classify the requested operation.
    target: concise target name; omit articles and action verbs.
    value: exact text, number, key, shortcut, destination,
           or requested setting value.
    Use null for unspecified fields. Never invent values.
    Preserve exact user text when typing.
  </extraction>

  <rules>
    Keyboard typing -> navigation_agent/type.
    Key presses and shortcuts -> navigation_agent/click.
    Mouse operations -> navigation_agent.
    App, window, and tab operations -> navigation_agent.
    File and directory operations -> file_agent/none.
    System controls -> system_agent.
    Do not route based only on keywords; consider the intent.
  </rules>

  <examples>
    <example input="Open Firefox">
      {"agent_type":"navigation_agent","action":"click","target":"Firefox","value":null}
    </example>
    <example input="Create a new tab">
      {"agent_type":"navigation_agent","action":"click","target":"new tab","value":null}
    </example>
    <example input="Switch to the second tab">
      {"agent_type":"navigation_agent","action":"select","target":"second tab","value":null}
    </example>
    <example input="Type echo hello">
      {"agent_type":"navigation_agent","action":"type","target":null,"value":"echo hello"}
    </example>
    <example input="Press Ctrl+C">
      {"agent_type":"navigation_agent","action":"click","target":"keyboard shortcut","value":"Ctrl+C"}
    </example>
    <example input="Minimize this window">
      {"agent_type":"navigation_agent","action":"click","target":"minimize window","value":null}
    </example>
    <example input="Delete report.pdf">
      {"agent_type":"file_agent","action":"none","target":"report.pdf","value":null}
    </example>
    <example input="Rename old.txt to new.txt">
      {"agent_type":"file_agent","action":"none","target":"old.txt","value":"new.txt"}
    </example>
    <example input="Turn off Wi-Fi">
      {"agent_type":"system_agent","action":"toggle","target":"Wi-Fi","value":"off"}
    </example>
    <example input="Set volume to 40">
      {"agent_type":"system_agent","action":"none","target":"volume","value":"40"}
    </example>
    <example input="Pause music">
      {"agent_type":"system_agent","action":"none","target":"media playback","value":"pause"}
    </example>
  </examples>

  <output>
    Return one valid JSON object only.
    No markdown, comments, or additional text.
  </output>
</router>
"""


# --------------------------------------------------------------------------
# Agent
# --------------------------------------------------------------------------
class Agent:
    def __init__(self):
        self.state = AgentState()
        self.client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="not-needed")
        self.nav = NavAgent(self.client)
        self.system_agent = get_system_agent()

    def routing(self, user_input) -> Optional[AgentEnum]:
        """Classify the command and decide direct vs planned.

        Direct (no planner) when:
          1. the classifier says system_agent (native API path), or
          2. the classifier says action == none and the command is not a chain.
        Everything else goes through the planner. Doubt resolves to the planner.
        """
        self.state.direct = False

        completion = self.client.beta.chat.completions.parse(
            model="local",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_input},
            ],
            response_format=AgentResolution,
            temperature=0,
        )
        message = completion.choices[0].message
        if message.parsed is None:
            print(f"Parse failed. Raw: {message.content!r}, refusal: {message.refusal!r}")
            return None

        p = message.parsed
        self.state.agent_type = p.agent_type
        self.state.action = p.action
        self.state.target = p.target
        self.state.value = p.value

        if p.agent_type == AgentEnum.system_agent:
            self.state.direct = True
        elif p.action == ActionEnum.none and not is_chain(user_input):
            self.state.direct = True
        return p.agent_type

    def _handle_navigation(self, user_input):
        if self.state.direct:
            self.nav.run_direct(f"Execute: '{user_input}'")
        else:
            action = self.state.action.value if self.state.action else "click"
            self.nav.run_planned(user_input, action=action, target=self.state.target)

    def _run(self, user_input: str):
        """Route and execute the appropriate agent workflow."""

        if not user_input or not user_input.strip():
            return None

        response = self.routing(user_input)

        route = "direct" if self.state.direct else "planner"
        print(f"Routing response: {response} -> {route}\n")

        if response is None:
            print("Could not classify; ask the user or rephrase.\n")
            return None

        if response == AgentEnum.system_agent:
            out = self.system_agent.run(f"Execute: '{user_input}'")
            print(f"Executed system agent: {out}")
            return out

        elif response == AgentEnum.navigation_agent:
            return self._handle_navigation(user_input)

        else:
            print("Not Implemented\n")
            return None


    def start(self):
        """Interactive terminal interface."""

        while True:
            user_input = input("user> ").strip()

            if user_input.lower() in ("exit", "q", "quit"):
                break

            if not user_input:
                continue

            self._run(user_input)


if __name__ == "__main__":
    Agent().start()