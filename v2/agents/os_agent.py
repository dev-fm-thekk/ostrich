import needle
import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio
import subprocess

@needle.tool
def launch_app(app_id: str):
    try:
        proc = subprocess.run([app_id])

        if proc.stderr:
            print(proc.stderr)
            return proc.stderr

        print(proc.stdout)
        return proc.stdout
    except Exception as e:
        print(e)
        return False

def build_context():
    apps = []

    for app in Gio.AppInfo.get_all():
        if app.should_show():
            apps.append(f"<AppId>{app.get_id()}</AppId>\n<AppName>{app.get_name()}</AppName>")

    context = "\n".join(apps)
    return context

agent = needle.Needle(tools=[launch_app])

context = build_context()

def main():
    while True:
        query = str(input("You: "))
        
        if query in ["quit", "exit", "q"]:
            break

        context = build_context()
        prompt = f"""
        <Context>{context}<Context>
        <Instruction>For parameters always pass the AppId in gnome-convention<Instruction>
        <User>{query}</User>
        """.strip()

        print(prompt)

        result = agent.run(prompt)
        print(f"Agent: {result}")

if __name__ == "__main__":
    main()