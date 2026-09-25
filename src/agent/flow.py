from pydantic import BaseModel
from crewai.flow.flow import Flow, listen, start
from agent.crews.code_crew.code_generator import TaskCrew, load_tools_manifest
from crewai.experimental import ConversationState
from crewai.experimental.conversational import ConversationConfig
from agent.core.shared import Window, LastAction, ActionState
import platform
import os
from pathlib import Path
import uuid
import subprocess
import mlflow
import time
import select

mlflow.crewai.autolog()

class DesktopState(ConversationState):
    os: str = ""
    windows: Window = {}
    active_window: str = ""
    last_action: LastAction = {}
    planned_actions: list[ActionState] = {}

   
@ConversationConfig(defer_trace_finalization=True)
class OstrichFlow(Flow[DesktopState]):
    """Flow for execution of User commands"""

    conversational = True

    @start()
    def platform_setup(self):
        """Get user Command for script generation"""
        if not self.state.os:
            self.state.os = platform.system()
        return self.state

    @listen(platform_setup)
    def generate_tasks(self):
        """Generate tasks and update the action items"""
        command = input("Enter command to perform: ")
        tool_registry = load_tools_manifest()

        result = TaskCrew().crew().kickoff(
            inputs={
                'text_command': command,
                'target_os':self.state.os,
                'tools_registry': tool_registry
            }
        )
        data : ActionState = result.pydantic
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

    """@listen(generate_code)
    def execute_task(self):
        pass

    @listen(execute_task)
    def update_state(self):
        pass
    """
        
        
def kickoff():
    """Run Ostrich flow"""
    OstrichFlow().kickoff()


if __name__ == "__main__":
    kickoff()

