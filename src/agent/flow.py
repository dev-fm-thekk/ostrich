from crewai.flow.flow import Flow, listen, start
from agent.crews.code_crew.code_generator import TaskCrew, load_tools_manifest
from crewai.experimental import ConversationState
from crewai.experimental.conversational import ConversationConfig
from agent.core.shared import Window, LastAction, ActionState
import platform
import mlflow
import json

from agent.core.ui_tree import UITree, ACTION_NOT_FOUND, WINDOW_NOT_FOUND

mlflow.crewai.autolog()

class DesktopState(ConversationState):
    os: str = ""
    snapshot: str = ""
    active_window: Window = {}
    last_action: LastAction = {}
    planned_actions: list[ActionState] = []
    


@ConversationConfig(defer_trace_finalization=True)
class OstrichFlow(Flow[DesktopState]):
    """Flow for execution of User commands"""

    conversational = True

    @start()
    def platform_setup(self):
        """Get user Command for script generation"""
        if not self.state.os:
            self.state.os = platform.system()
        if not hasattr(self, "_ui_tree"):
            self._ui_tree = UITree()
        return self.state

    @listen(platform_setup)
    def generate_tasks(self):
        """Generate tasks and update the action items"""
        message = (self.state.current_user_message or "").lower()
        tool_registry = load_tools_manifest()

        self.state.snapshot = json.dumps(self._ui_tree.snapshot())

        result = TaskCrew().crew().kickoff(
            inputs={
                'text_command': message,
                'target_os': self.state.os,
                'tools_registry': tool_registry,
                'snapshot': self.state.snapshot
            }
        )
        
        data: ActionState = result.pydantic
        self.state.planned_actions.append(data)

        self.state.last_action = LastAction(
            type=data.type,
            window_id=data.window_id,
            element=data.element
        )
        print(f"[State Updated] Added action '{data.type}' targeting '{data.target}' to planned_actions.")
        return data

    """
    @listen(generate_tasks)
    def check_safety(self):
        pass
    """

    @listen(generate_tasks)
    def execute_task(self):
        execution_log = []

        for action in self.state.planned_actions:
            params = getattr(action, "params", None) or []

            # Disambiguation actions don't touch UITree at all — handle and stop.
            if action.type == "ask_user":
                execution_log.append((action, "asked"))
                self._execution_log = execution_log
                self.state.planned_actions = []
                return execution_log

            try:
                result = self._ui_tree.call_action(action.type, *params)
            except Exception as e:
                print(f"[execute_task] '{action.type}' raised: {e}")
                result = None

            if result == ACTION_NOT_FOUND:
                print(f"[execute_task] Unknown action type: '{action.type}'")
            elif result is WINDOW_NOT_FOUND:
                target = getattr(action, "target", None)
                print(f"[execute_task] '{action.type}' found no matching window (target={target})")
            else:
                print(f"[execute_task] '{action.type}' -> {result}")

            execution_log.append((action, result))

        # Mirror UITree's active-window bookkeeping into serializable Flow
        # state, so it's visible/inspectable and survives if you ever persist
        # DesktopState. _ui_tree itself (with the live _active_acc) still owns
        # the ground truth across turns.
        if self._ui_tree.active_window is not None:
            self.state.active_window = self._ui_tree.active_window

        self._execution_log = execution_log
        self.state.planned_actions = []   # the earlier bug fix — was self.planned_actions
        return execution_log

def kickoff():
    """Run Ostrich flow"""
    flow = OstrichFlow()
    flow.chat()

if __name__ == "__main__":
    kickoff()