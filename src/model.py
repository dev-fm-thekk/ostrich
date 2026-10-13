import needle

from tools import open_app

agent = needle.Needle(tools=[open_app])
print(agent.run("can you open power point")["results"])
# [{'success': True, 'message': "Launched 'notepad' (PID 1234).", 'pid': 1234}]