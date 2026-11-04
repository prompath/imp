---
description: Open a live local page of every imp idea, grouped by what needs you, and a pixel campus of who works where
argument-hint: "[--port N]"
disable-model-invocation: true
---

Start the dashboard server unless something already listens on the port (default 8765, or the `--port` in `$ARGUMENTS`), then print both URLs. Run this in Bash, with the port filled in:

```
PORT=8765
if python3 -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', $PORT)) != 0)"; then
  echo "imp dashboard already running"
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/api/rooms)" = 404 ]; then
    echo "This server is old and has no /rooms page. To fix it, run:"
    echo "  pkill -f \"impctl.py dashboard --port $PORT\""
    echo "  nohup python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py\" dashboard --port $PORT >/dev/null 2>&1 &"
  fi
else
  nohup python3 "${CLAUDE_PLUGIN_ROOT}/scripts/impctl.py" dashboard --port $PORT >/dev/null 2>&1 &
fi
echo "imp dashboard: http://127.0.0.1:$PORT/"
echo "imp rooms:     http://127.0.0.1:$PORT/rooms"
```

If `${CLAUDE_PLUGIN_ROOT}` is empty, the plugin folder is the one above this command's `commands/` folder. Show the output and nothing else. It lists ideas from every registered project (`/ideas --projects --scan DIR` registers them).
