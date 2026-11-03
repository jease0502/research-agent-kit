# Claude Code with rak's MCP tools only

Claude Code gets exactly four tools: `mcp__rak__exec`, `mcp__rak__read`, `mcp__rak__edit` and `mcp__rak__write`.
They are served by `python/rak/mcp_server.py`, and every call goes through the policy engine first. The design
and the threat model are in `docs/mcp-server.md`.

## Use

1. Copy `mcp.json` and fill in three absolute paths:
   - `--root`: your project;
   - `--audit-log`: a file **outside** the project;
   - `PYTHONPATH`: this kit's `python/` folder.
2. Edit `--exec-allow` to list only programs you trust with any arguments. `python` and `git` can do anything the
   OS user can (see the threat model).
3. Start Claude Code in the project:

```
claude --tools "" --settings examples/claude-code-mcp/settings.json --mcp-config /abs/path/your-mcp.json --strict-mcp-config
```

## The two layers

- **`--tools ""` is the allowlist.** It turns off every built-in tool, and only the MCP tools remain. A real run on
  2026-11-01 (Claude Code 2.1.316) listed exactly the four `mcp__rak__*` tools in its `init` event. As far as we
  know, `--tools` is a command-line flag, not a settings key, so it has to be on every launch line.
- **`settings.json` is the second layer.**
  - It denies Bash, PowerShell, Monitor, Read, Edit, MultiEdit, Write, NotebookEdit, Glob, Grep, WebFetch and
    WebSearch, and allows the four MCP tools.
  - On its own it is not enough. The first smoke run with deny rules only found PowerShell, a built-in shell on
    Windows, still in the tool list. Any built-in tool added later would be on as well.
- For a lock the user cannot undo, put the same permission keys in managed settings.

## Windows

`claude` is `claude.cmd`, which runs through `cmd.exe`. An argument that contains a newline is cut there, and every
argument after it is dropped silently. That can include `--tools`, `--settings` and `--mcp-config`.
- Never pass a multi-line prompt as an argument. Send it on stdin (`claude -p` reads it).
- Or call `node_modules/@anthropic-ai/claude-code/bin/claude.exe` directly.
- Before trusting a run, check the `init` event of `--output-format stream-json`:
  - the model;
  - `mcp_servers` shows `rak` as `connected`;
  - the tool list holds only `mcp__rak__*`.
