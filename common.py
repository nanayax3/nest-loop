"""
Shared plumbing for nest-loop. Everything comes from environment variables:
no secrets, ids or names live in code (NESTstack's rule, and a good one).

Required for the hooks:
  NEST_MCP_URL        your NESTeq MCP endpoint, e.g. https://ai-mind.<you>.workers.dev/mcp
  NEST_MCP_TOKEN      the bearer token for it
Required for the miner / standing knowledge (read-only D1 access):
  CF_ACCOUNT_ID, CF_D1_DATABASE_ID, CF_API_TOKEN
Optional:
  LOOP_HUMAN          NESTknow scope for your human (default "human")
  LOOP_COMPANION      NESTknow scope for the companion (default "companion")
  LOOP_MODEL          the model your companion ALREADY runs on, for the headless miner runs
                      (no extra model is needed; default "claude-opus-5-5")
  LOOP_CLAUDE_BIN     path to the claude binary (default: "claude" on PATH)
  LOOP_NOTIFY_CMD     a command that posts one line somewhere your human will see it;
                      the message is passed as its last argument
  LOOP_STATE_DIR      where state and run folders live (default ~/.nest-loop)
  LOOP_SKIP_ENV       if this env var is set, hooks stay silent (e.g. a Discord bridge
                      can set it if you do NOT want recall in public-facing sessions)
"""
import json, os, re, subprocess, urllib.request

HUMAN = os.environ.get("LOOP_HUMAN", "human")
COMPANION = os.environ.get("LOOP_COMPANION", "companion")
MODEL = os.environ.get("LOOP_MODEL", "claude-opus-5-5")
CLAUDE = os.environ.get("LOOP_CLAUDE_BIN", "claude")
STATE_DIR = os.path.expanduser(os.environ.get("LOOP_STATE_DIR", "~/.nest-loop"))
UA = {"User-Agent": "nest-loop/1"}


def mcp(tool, args, timeout=120):
    """Call one NESTeq MCP tool; returns its text output."""
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "Authorization": "Bearer " + os.environ["NEST_MCP_TOKEN"], **UA}
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": args}}).encode()
    raw = urllib.request.urlopen(urllib.request.Request(os.environ["NEST_MCP_URL"], body, h),
                                 timeout=timeout).read().decode()
    if "data:" in raw[:20] or raw.lstrip().startswith("event:"):   # streamable-HTTP answers as SSE
        raw = [l[5:].strip() for l in raw.splitlines() if l.startswith("data:")][-1]
    d = json.loads(raw)
    if "error" in d:
        raise RuntimeError(d["error"])
    return "".join(c.get("text", "") for c in d["result"].get("content", []))


def d1(sql, params=None, timeout=60):
    """Read-only query against the NESTeq D1 database over the Cloudflare API."""
    if not re.match(r"\s*(SELECT|WITH)\b", sql, re.I):
        raise ValueError("nest-loop only ever reads D1 directly; writes go through NESTeq's own tools")
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}/d1/database/"
        f"{os.environ['CF_D1_DATABASE_ID']}/query",
        json.dumps({"sql": sql, "params": params or []}).encode(),
        {"Authorization": "Bearer " + os.environ["CF_API_TOKEN"], "Content-Type": "application/json", **UA})
    d = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    if not d.get("success"):
        raise RuntimeError(d.get("errors"))
    return d["result"][0]["results"]


def notify(text):
    cmd = os.environ.get("LOOP_NOTIFY_CMD")
    if cmd:
        subprocess.run(cmd.split() + [text], check=False, capture_output=True)


def headless(prompt, cwd, tools=("Read", "Write", "Bash(python3 -m json.tool:*)"), turns=60, timeout=3600):
    """Wake the companion headless for one judgement job. It may only read files and write
    its proposal; everything that reaches memory goes through code that checks it."""
    return subprocess.run([CLAUDE, "--model", MODEL, "-p", prompt, "--allowedTools", *tools,
                           "--max-turns", str(turns)], cwd=cwd, capture_output=True, text=True, timeout=timeout)
