import os
import platform
from crewai import LLM, Agent, Task, Crew, Process
from crewai.project import CrewBase, agent, task, crew
from ...core.shared import ActionState
import mlflow
from pathlib import Path
#from agent.config import vars


def load_tools_manifest() -> str:
    manifest_path = Path(__file__).parent / "config"/ "tools.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as f:
            return f.read()
    return "[]"

llm = LLM(
    model="gemini/gemini-3.5-flash",          # "openai/" prefix = OpenAI-compatible route; the name after it is arbitrary
    api_key=os.environ["GEMINI_API_KEY"],          # must be non-empty, llama.cpp ignores it
    temperature=0.4
)

@CrewBase
class TaskCrew:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    @agent
    def tasks_generator(self) -> Agent:
        return Agent(
            config=self.agents_config['tasks_generator'],
            llm=llm
        )
    @task
    def tasks_generator_task(self) -> Task:
        return Task(
            config=self.tasks_config['generate_script_task'],
            agent=self.tasks_generator(),
            output_pydantic=ActionState
        )
    @crew 
    def crew(self) -> Crew:
        return Crew(
            agents = self.agents,
            tasks = self.tasks,
            process = Process.sequential,
            verbose = True,
        )
