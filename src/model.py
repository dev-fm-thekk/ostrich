import needle

from tools import (
    open_app,
    list_windows,
    switch_window,
    maximize_window,
    minimize_window,
)

agent = needle.Needle(
    tools=[
        open_app,
        list_windows,
        switch_window,
        maximize_window,   
        minimize_window,
    ]
)
print(agent.run("can you minimize powershell")["results"])
# [{'success': True, 'message': "Launched 'POWERPNT' via Start-Process (PID 1234).", 'pid': 1234}]