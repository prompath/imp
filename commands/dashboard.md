---
description: Open a live local page of every imp idea, grouped by what needs you
argument-hint: "[--port N]"
disable-model-invocation: true
---

Start the dashboard server unless something already listens on the port (default 8765, or the `--port` in `$ARGUMENTS`), then print its URL. Run this in Bash, with the port filled in:

```
PORT=8765
if python3 -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', $PORT)) != 0)"; then
  echo "imp dashboard already running: http://127.0.0.1:$PORT/"
else
  nohup python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" dashboard --port $PORT >/dev/null 2>&1 &
  echo "imp dashboard: http://127.0.0.1:$PORT/"
fi
```

If `${CLAUDE_PLUGIN_ROOT}` is empty, the plugin folder is the one above this command's `commands/` folder. Show the URL and nothing else. It lists ideas from every registered project (`/ideas --all --scan DIR` registers them).
