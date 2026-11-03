# Harness landscape: keeping enforcement when the model or the agent changes

Status: investigation only; nothing was installed or run. Sources were read on 2026-10-31.

The goal: pre-registration checks, gates, permission rules, read blocks and git guards must still hold
when the model changes, or when the driving agent changes (Claude Code, OpenClaw, Codex CLI, Gemini CLI).

Notes on sources:
- Facts carry their source. "Not found" means the page did not say it.
- Several quotes passed through a summarising fetch tool. Re-check them against the live page before citing.
- Where a release page showed only day and month, the year (2026) is inferred.

## 0. A finding about this kit first

Claude Code's hook docs: "On `PreToolUse`, a timed-out `command`, `http`, or `mcp_tool` hook doesn't block the
tool call", and any exit code other than 0 or 2 "is a non-blocking error". Only `"onFailure": "block"`
(Claude Code v2.1.295 or later) makes a failed or timed-out hook block the call
([hooks](https://code.claude.com/docs/en/hooks)).

None of our `hooks.json` files sets `onFailure`.

Our hook scripts exit 2 on any Python exception. They still fail open in three cases:
- the hook times out (15–30 s);
- `python` cannot be started;
- the hook prints invalid output.

`docs/security.md` says "It fails closed". That is true only for crashes inside the script. Fixing it means adding
`"onFailure": "block"` to each hook and a minimum Claude Code version. That belongs to the policy-engine work.

## 1. Agent loops and frameworks: where can a tool call be stopped?

| Framework | Pre-tool hook that can block | Covers built-in shell/file tools? | Models | License, latest |
|---|---|---|---|---|
| Claude Agent SDK (reference) | `PreToolUse` (allow / deny / ask, `updatedInput`), `canUseTool`, deny rules; "a hook deny applies even in `bypassPermissions` mode"; an SDK callback hook that times out blocks the call ([permissions](https://code.claude.com/docs/en/agent-sdk/permissions), [hooks](https://code.claude.com/docs/en/agent-sdk/hooks), [hooks](https://code.claude.com/docs/en/hooks)) | yes, built-in and MCP tools | Claude only (Anthropic API, Bedrock, Vertex, Foundry) | repo MIT; use under Anthropic's Commercial Terms ([overview](https://code.claude.com/docs/en/agent-sdk/overview)); v0.2.176, 31 Oct |
| OpenAI Agents SDK | `tool_input_guardrails`: "run before the tool executes and can skip the call" ([guardrails](https://openai.github.io/openai-agents-python/guardrails/)) | **no**: "Tool guardrails wrap FunctionTool instances"; hosted tools, handoffs and `Agent.as_tool()` are outside; local `ShellTool`/`ApplyPatchTool` "default to `needs_approval=False`" ([tools](https://openai.github.io/openai-agents-python/tools/)) | OpenAI; LiteLLM and Any-LLM as "best-effort, beta" ([models](https://openai.github.io/openai-agents-python/models/)) | MIT; v0.24.0, 2026-10-15 |
| LangGraph / LangChain | `ToolNode(wrap_tool_call=...)`; middleware `wrap_tool_call` can call the handler "zero times (short-circuit)" ([middleware](https://docs.langchain.com/oss/python/langchain/middleware/custom)) | only tools routed through that node; any graph node can run side effects outside it (our inference) | LangChain chat models (not verified) | MIT; 1.2.19, 2026-10-30 ([PyPI](https://pypi.org/pypi/langgraph/1.2.19/json)) |
| PydanticAI | `before_tool_execute`; "To skip execution, raise `SkipToolExecution(result)`"; `ApprovalRequiredToolset`, `WrapperToolset.call_tool()` ([hooks](https://pydantic.dev/docs/ai/core-concepts/hooks/), [toolsets](https://pydantic.dev/docs/ai/tools-toolsets/toolsets/)) | "hooks only fire for function tools"; no built-in shell/file tools in core | about 37 providers natively ([models](https://pydantic.dev/docs/ai/models/overview/)) | MIT; v2.64.0, 2026-10-30 |
| smolagents | none found; `step_callbacks` run per step ([reference](https://huggingface.co/docs/smolagents/main/en/reference/agents)) | `CodeAgent` runs model-written Python, so per-tool hooks cannot exist; "no local python sandbox can ever be completely secure" ([secure execution](https://huggingface.co/docs/smolagents/main/en/tutorials/secure_code_execution)) | several (not checked) | Apache-2.0; v1.26.0, 2026-05-29 (no release for 5 months) |
| LiteLLM | not an agent loop. The proxy's `tool_permission` guardrail checks tool calls **in model output** and "rewrites the model response/tool calls after the fact" ([tool_permission](https://docs.litellm.ai/docs/proxy/guardrails/tool_permission)) | it never sees what was executed | "100+ LLMs" ([repo](https://github.com/BerriAI/litellm)) | core open source; some features under a commercial license; v1.106.6, 28 Oct |
| OpenHands SDK | `HookConfig(pre_tool_use=...)`; "Only exit code `2` blocks" ([hooks](https://docs.openhands.dev/sdk/guides/hooks)); the security analyzer "does not prevent execution", and "`conversation.execute_tool()` bypasses the analyzer and confirmation policy" ([security](https://docs.openhands.dev/sdk/guides/security)) | terminal and file-editor tools are attached explicitly; full coverage not stated | through LiteLLM, "100+ providers" ([llm](https://docs.openhands.dev/sdk/arch/llm)) | MIT (LICENSE text not read); v1.34.0, 2026-10-27 |
| Aider | none; no tool-call loop. Edits and git commits are core behaviour; `--git-commit-verify` is "default: False", so git pre-commit hooks are skipped by default ([options](https://aider.chat/docs/config/options.html)) | n/a | most LLMs ([llms](https://aider.chat/docs/llms.html)) | Apache-2.0; v0.86.2, 2026-02-12 (low activity) |
| goose | `PreToolUse` hooks block with exit 2; **fail open**: "By default a hook failure is logged and the tool call proceeds" ([hooks doc source](https://raw.githubusercontent.com/block/goose/main/documentation/docs/guides/context-engineering/hooks.md)) | "Before goose runs a tool"; disabling its shell not confirmed | 15+ providers natively ([repo](https://github.com/block/goose)) | Apache-2.0; v1.57.0, 2026-10-28 |

What follows from the table:

- Only the Claude stack documents a hook that sees every tool and still holds in bypass mode. Every other framework
  hooks **its own function tools**. Hosted, built-in or code-as-action execution passes beside the hook.
- A hook on a shell tool sees command text, not effects. Claude's own docs make this point: a `Write|Edit` matcher
  does not catch a write done through Bash. Real limits on files, network and env must come from the OS.
- LLM-judged gates are classifiers, not enforcement: goose Smart Approval, the OpenHands analyzer, auto modes.

## 2. Sandboxes: what can be limited, and on Windows?

| Option | FS read / write separately | Network egress | Child env | Native Windows 11 | License, latest |
|---|---|---|---|---|---|
| Anthropic sandbox-runtime (srt) | yes: read is "deny-then-allow", write is "allow-only… An empty allow list means no write access" ([repo](https://github.com/anthropic-experimental/sandbox-runtime)) | domain allowlist through a host HTTP/SOCKS5 proxy | Windows: fresh env with only `PATH` and proxy variables; Linux/macOS scrubbing not found | **alpha**: a dedicated `srt-sandbox` user, one elevated install step | Apache-2.0; v0.0.81, 20 Oct |
| Claude Code `/sandbox` | yes (`allowWrite`, `denyWrite`, `denyRead`, `allowRead`); default "read access to the entire computer" ([sandboxing](https://code.claude.com/docs/en/sandboxing)) | domain allowlist via a local proxy, starts empty | "Inherited from Claude Code, including any secrets in its environment" unless denied (`sandbox.credentials.envVars`, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB`) | **no**: "On native Windows, Claude Code runs commands unsandboxed"; use WSL2 | bundled |
| Docker (rootless) / gVisor | per mount, `ro`/`rw`; unmounted paths invisible ([bind mounts](https://docs.docker.com/engine/storage/bind-mounts/)) | `--network none`, or all; no domain list ([none driver](https://docs.docker.com/engine/network/drivers/none/), [gVisor networking](https://gvisor.dev/docs/user_guide/networking/)) | explicit `-e` | Docker Desktop runs Linux containers in WSL2/Hyper-V; gVisor needs Linux 5.6+ | Engine 29.9.2 (2026-10-20); gVisor Apache-2.0, release-20261026.0 |
| bubblewrap | yes: `--ro-bind`, `--bind`; unmounted paths invisible ([bwrap.xml](https://raw.githubusercontent.com/containers/bubblewrap/main/bwrap.xml)) | `--unshare-net` (loopback only); domains need a proxy | `--clearenv` | Linux / WSL2 only | LGPL-2.1; v0.13.1, 2026-10-14 |
| firejail | `--read-only`, `--whitelist`, `--blacklist` ([man](https://man7.org/linux/man-pages/man1/firejail.1.html)) | `--net=none`; `--netfilter` (IP level) | `--env`, `--rmenv` | Linux only; SUID-root | GPL-2.0; 0.9.80 |
| Windows AppContainer | partial: write per file, "Read-only access is less restricted" ([MS Learn](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)) | capabilities (internet, intranet, server); no domains | not found | yes; we would write the launcher | part of Windows |
| Windows Sandbox | mapped folders, optionally `ReadOnly` ([wsb](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)) | on or off | fresh VM | yes (Pro), but a GUI VM, awkward per command | part of Windows |
| WSL2 as the boundary | **weak by default**: `C:` and `D:` are mounted read-write under `/mnt`; `[automount] enabled=false` turns that off ([wsl-config](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)) | `networkingMode=none` or Hyper-V firewall; no domains | `[interop] appendWindowsPath` | it is the Windows answer for bubblewrap and srt | doc updated 2026-10-16 |
| E2B / Modal / Daytona (cloud) | remote VM or container; no host FS | E2B: domain filtering by Host header (HTTP) and SNI (TLS); "Domains are not supported in the deny lists" ([E2B](https://docs.e2b.dev/sandbox/internet-access)); Modal and Daytona have domain or CIDR allowlists ([Modal](https://modal.com/docs/guide/sandbox-networking), [Daytona](https://www.daytona.io/docs/en/network-limits/)) | only what is passed | client only | E2B Apache-2.0 (Firecracker) |
| Codex CLI (reference) | permission profiles; a deny "Denies both reads and writes under the path"; Windows "unelevated" mode "doesn't support denied read paths" ([permissions](https://learn.chatgpt.com/docs/permissions)) | off by default; domain rules need its proxy | `shell_environment_policy`; names containing KEY/SECRET/TOKEN are not removed by default ([config-advanced](https://learn.chatgpt.com/docs/config-file/config-advanced)) | **yes, native** | rust-v0.166.0, 2026-10-29 |

What follows from the table:

- **Sandboxes cover the shell, not the agent.** Claude Code: "The sandbox covers shell commands only. Claude's
  file tools, MCP servers, and hooks run outside it" ([sandboxing](https://code.claude.com/docs/en/sandboxing)).
  Codex says the same about MCP servers. To hold for any agent, wrap the **whole agent process**: srt around the
  CLI, a container, a hardened WSL2 distro, or a VM.
- **Escape hatches are on by default.** Claude may retry a blocked command unsandboxed; set
  `allowUnsandboxedCommands: false` and `failIfUnavailable: true`. Without the second, an unsupported platform runs
  commands unsandboxed silently.
- **A domain allowlist is not "no exfiltration".** Matching is on hostname or SNI. The Claude docs warn about
  domain fronting, and an allowed `github.com` is itself a channel.
- **Defaults read everything and inherit secrets.** Deny lists and env scrubbing must be configured.
  bubblewrap `--clearenv` is the cleanest primitive.
- **On this kit's Windows machines the practical path is WSL2 or Docker Desktop.** Turn off WSL2 automount and
  interop, then run bubblewrap or srt inside. Native srt on Windows is alpha with documented holes, for example
  "Do not rely on `network.allowedDomains`… to cover SMB shares or WSL" ([repo](https://github.com/anthropic-experimental/sandbox-runtime)).
- **On GCP Linux VMs:** containers or gVisor for the kernel boundary, plus srt or a proxy for domain egress.
  The VM itself is already the outer boundary (`docs/security.md`).

## 3. MCP as the enforcement point

The idea: our exec, read, edit and write tools are served by our own MCP server, which applies the policy on every
call. Every agent is configured to use only those tools.

| | Claude Code | OpenClaw | Codex CLI | Gemini CLI |
|---|---|---|---|---|
| Disable native shell | yes: `--tools ""`, or deny `Bash` ("removes the tool from Claude's context entirely") ([cli](https://code.claude.com/docs/en/cli-reference), [permissions](https://code.claude.com/docs/en/permissions)) | yes: `tools.deny: ["group:runtime"]` (`exec`, `process`, `code_execution`) ([tool policy](https://docs.openclaw.ai/gateway/config-tools/tool-policy)) | yes: `[features] shell_tool = false` ([config reference](https://learn.chatgpt.com/docs/config-file/config-reference)) | yes: policy `deny` on `run_shell_command` ([policy engine](https://geminicli.com/docs/reference/policy-engine/)) |
| Disable native file tools | yes: deny `Read`, `Edit`, `Write`, `Glob`, `Grep`, `NotebookEdit`; `--disallowedTools "*"` removes all | yes: `group:fs`; "Denying `write` does not deny `apply_patch`" | **partly**: reads go through the shell; **no documented switch for `apply_patch`** found | yes: deny `read_file`, `read_many_files`, `write_file`, `replace`, `glob`, `grep_search`, `list_directory` ([tools](https://geminicli.com/docs/reference/tools/)) |
| Other paths left | WebFetch/WebSearch (deny them), @-mentions (covered by Read deny), CLAUDE.md and memory loaded directly, hooks and status-line commands, plugin MCP servers | web, browser, media, memory and plugin tool groups; "Elevated `exec` bypasses sandboxing" ([tools](https://docs.openclaw.ai/tools)) | hosted `web_search` (set `"disabled"`), AGENTS.md, `view_image`; whether `exec_command` survives `shell_tool=false` is undocumented | `web_fetch`, `google_web_search`, GEMINI.md, extensions; @file goes through `read_many_files` |
| Own pre-tool hook | `PreToolUse`, blocks; fails open on timeout unless `onFailure: "block"` | plugin `before_tool_call`, "`block: true` is terminal"; fail-closed not stated ([hook policy](https://docs.openclaw.ai/plugins/hooks/tool-policy)) | `PreToolUse`; "a useful guardrail, not a complete enforcement boundary"; errors and timeouts "can fail the hook without blocking the tool" ([hooks](https://learn.chatgpt.com/docs/hooks)) | `BeforeTool`, blocks; covers MCP tools ([hooks](https://geminicli.com/docs/hooks/reference/)) |
| Admin lock | yes: managed settings, "Nothing in your own settings files or `--settings` overrides a managed key"; `allowManagedPermissionRulesOnly`, `allowManagedHooksOnly` ([settings](https://code.claude.com/docs/en/settings)) | **not found** | yes: `requirements.toml`, "admin-enforced constraints that users can't override" ([managed config](https://learn.chatgpt.com/docs/enterprise/managed-configuration.md)); pinning `shell_tool=false` there is not shown | yes: system settings and admin policies "always override User, Workspace, and Default policies" ([configuration](https://geminicli.com/docs/reference/configuration/)) |

Feasibility:

- **Claude Code and Gemini CLI:** MCP-only is feasible and lockable.
- **Codex CLI:** feasible for the shell. `apply_patch` remains an unguarded write path until a switch is documented.
  Its own hooks are not an enforcement boundary.
- **OpenClaw:** the tools can be denied, but there is no admin lock: the agent's operator can undo it.
- **In all four,** context files (CLAUDE.md, AGENTS.md, GEMINI.md) are read directly, not through a tool. An MCP
  server never sees those reads. A file the agent must not read has to be outside its reach (sandbox), not just
  denied to a tool.
- **MCP servers run outside the agent's sandbox** (section 2). Our server is then the one process with real access,
  and it must be small, tested and fail closed.

## 4. Recommendation: no agent loop of our own; enforce at three layers that do not depend on the loop

**Do not write our own agent loop, and do not build on a framework, for enforcement.** Reasons:

1. **The frameworks hook only their own function tools** (section 1). Building on one gives no guarantee for the
   agents people actually use: Claude Code, Codex, Gemini CLI, OpenClaw.
2. **An own loop means owning model adapters, tool-call parsing and context management for every provider.**
   These change monthly. The enforcement would also hold only inside our loop.
3. **The guarantees we need are about effects**, such as files, network, secrets and git history. Effects are
   enforced by the OS and by the service that receives them, not by the loop.

The layers:

| Layer | What it enforces | Holds for any model or agent? |
|---|---|---|
| L1 OS sandbox around the whole agent process (WSL2 or container + bubblewrap/srt locally; container or VM on GCP) | read blocks, write scope, network allowlist, env allowlist | yes; this is the only layer an agent cannot talk its way past |
| L2 our MCP server (exec, read, edit, write) calling one policy engine (`python/rak/policy/`, see `docs/policy-engine.md`) | prereg launch guard, append-only results, tree and frozen-file guards, command rules | yes, where the agent can be limited to MCP tools (Claude Code, Gemini CLI fully; Codex partly; OpenClaw without a lock) |
| L3 git and CI: server-side or pre-receive checks, required CI on the protected branch, freeze hashes verified at job packaging | history, frozen files, private-name scan | yes; it does not run on the agent's machine at all |
| Adapters (per agent): config that disables native tools and registers the MCP server, plus that agent's native pre-tool hook calling the same policy engine | defence in depth; good error messages | no; one small adapter per agent, best effort |

If a headless loop is ever needed, for example a model with no agent CLI, PydanticAI is the best candidate. Reasons:
- `before_tool_execute` can skip a call;
- native multi-provider support;
- MIT license and active releases.

That loop would still get its tools only from our MCP server, so L1–L3 stay the guarantee.

Risks of this plan:

- **L2 is a single point of failure** with real privileges. It must fail closed, have no "debug" bypass, and get
  the same differential tests as the hooks it replaces.
- **Context files and @-mentions bypass tools in every agent.** Only L1 stops them.
- **Codex `apply_patch` and the OpenClaw admin gap.** Until they are closed, those agents get "L1 + L3 only" in our
  docs, not "fully enforced".
- **Windows.** Native sandboxing is alpha (srt) or absent (Claude Code). Our supported local setup would become
  "agent inside WSL2 with automount and interop off". That is a real change for users and needs a migration note.
- **Hook failure modes differ by agent:** Claude Code and Codex hooks fail open on timeout by default (section 0).
  Adapters must set fail-closed where it exists, and must never be described as the guarantee.

## 5. Not checked

- Whether Codex `exec_command` remains with `shell_tool=false`, and whether `requirements.toml` can pin it.
- OpenClaw: whether `before_tool_call` fails closed, whether it covers MCP tools, and auto-loaded workspace files.
- Gemini CLI: subagents, and whether project hooks need folder trust.
- srt environment scrubbing on Linux and macOS.
- Licenses not read from LICENSE files: LiteLLM core, OpenHands, Codex.
- Whether framework guardrails skip parallel tool calls (no source said either way).

## 6. Models and agents from Chinese vendors

Read on 2026-10-31.
- Most vendor pages render with JavaScript. Several clauses were read through search summaries; those are marked
  "secondary" or "not verified".
- Benchmark numbers are vendor-reported (V) unless marked independent (Indep).
- Vendors now quote four Terminal-Bench versions (2.0, 2.1, 3.0, 4.0). Numbers from different versions are not
  comparable.
- Memory sizes are parameter count × bytes per weight, KV cache excluded. They are arithmetic, not vendor figures.

### 6.1 Models

| Vendor | Latest (date) | Agentic benchmarks | Weights, license | Fits one 16 GB GPU? | Anthropic-compatible endpoint, stated limits |
|---|---|---|---|---|---|
| DeepSeek | V4.1-Flash-1017 (2026-10-17, [news](https://api-docs.deepseek.com/news/news261017)); V4-Pro | V: V4-Pro SWE-bench Verified 80.6, Terminal-Bench 2.0 67.9 ([card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro)); V4.1-Flash Terminal-Bench 4.0 42.3 with the Claude Code harness ([card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017)) | open, MIT; V4-Pro 1.6T total / 49B active (~1.6 TB FP8) | no | `https://api.deepseek.com/anthropic`: `tool_choice: any` "treated as auto", `disable_parallel_tool_use` and `tool_result.is_error` ignored, `cache_control` ignored, no `document` or MCP blocks ([guide](https://api-docs.deepseek.com/guides/anthropic_api)) |
| Moonshot Kimi | K3.1 Pro (API 2026-10-23; weights "by Nov 4", [quickstart](https://platform.kimi.ai/docs/guide/kimi-k3-1-pro-quickstart)); K3 | V: K3 Terminal-Bench 2.1 88.3 ([card](https://huggingface.co/moonshotai/Kimi-K3)); no SWE-bench Verified for K3 | open, custom "Kimi K3 License"; 2.8T / 104B active (~1.4 TB, secondary) | no | `https://api.moonshot.ai/anthropic` ([guide](https://platform.kimi.ai/docs/guide/claude-code-kimi)); `kimi-k2.7-code` rejects requests with thinking off |
| Alibaba Qwen | qwen3.8-max / 3.7-plus / 3.8-flash on the API ([models](https://www.alibabacloud.com/help/en/model-studio/models)); open Qwen3.8-27B, 3.8-Flash-Next, 3.8-2.4T-A95B | V: Qwen3.8-Max Terminal-Bench 2.1 86.6; Qwen3.8-27B Terminal-Bench 2.1 73.0, SWE-bench Pro 61.7 ([card](https://huggingface.co/Qwen/Qwen3.8-27B)) | 27B dense **Apache-2.0**; others custom licenses | **only Qwen3.8-27B at INT4 (~14 GB), marginal, short context** | per region, e.g. Singapore `https://{WorkspaceId}.ap-southeast-1.maas.aliyuncs.com/apps/anthropic` ([Claude Code guide](https://www.alibabacloud.com/help/en/model-studio/claude-code)); no model-list endpoint |
| Zhipu GLM (Z.ai) | GLM-5.3 (2026-08-18), GLM-5.3-Flash (2026-08-26) ([release notes](https://docs.z.ai/release-notes/new-released)) | V: GLM-5.3 Terminal-Bench 2.1 88.2, 3.0 28.3 ([card](https://huggingface.co/zai-org/GLM-5.3)) | GLM-5.3 custom; **GLM-5.3-Flash MIT**, 320B / 18B active (~160 GB INT4) | no | `https://api.z.ai/api/anthropic`; "verified compatibility with Claude Code 2.0.14" only ([guide](https://docs.z.ai/devpack/tool/claude)) |
| MiniMax | M3.1 Flash (2026-10-19), M3 ([release notes](https://platform.minimax.io/docs/release-notes/models)) | V: M3 SWE-bench Verified 80.5 ([card](https://huggingface.co/MiniMaxAI/MiniMax-M3)) | open, custom "minimax-community"; M3 ~428B / 23B active | no | `https://api.minimax.io/anthropic`; thinking always on for M3.1-Flash (`disabled` is a 400); `temperature`, `top_k`, `stop_sequences`, `mcp_servers` ignored ([API](https://platform.minimax.io/docs/api-reference/text-anthropic-api)) |
| ByteDance Doubao / Seed | Doubao-Seed-2.1-Pro / Turbo (2026-06-23, secondary) | no vendor agentic numbers found | flagships **closed**; small open ones (Seed-Coder-8B MIT) | small open ones only | Volcengine `https://ark.cn-beijing.volces.com/api/coding` ([guide](https://docs.volcengine.com/docs/82379/1928262)); it also serves GLM, DeepSeek and Kimi models |

Independent numbers: the swebench.com Verified leaderboard ends at 2026-02-17 entries, all run with
mini-SWE-agent:
- MiniMax M2.5 75.8;
- GLM 5 72.8;
- Kimi K2.5 70.8;
- DeepSeek V3.2 70.0.

None of the current flagships above has an independent entry. The tbench.ai leaderboard did not render for us.
No current card lists BFCL.

### 6.2 The cheap route: Claude Code with an Anthropic-compatible endpoint

Claude Code with `ANTHROPIC_BASE_URL` (plus `ANTHROPIC_AUTH_TOKEN` and the `ANTHROPIC_DEFAULT_*_MODEL`
variables) pointed at one of the endpoints above.

**Enforcement is client-side, so it stays.**
- "Permission rules are enforced by Claude Code, not by the model", and "Deny rules block in every mode"
  ([permissions](https://code.claude.com/docs/en/permissions), [permission modes](https://code.claude.com/docs/en/permission-modes)).
- Hooks run in the Claude Code process with its environment ([hooks](https://code.claude.com/docs/en/hooks)).
- Managed settings work with gateways. `allowedProviders: ["customEndpoint"]` pins the base URL
  ([LLM gateway](https://code.claude.com/docs/en/llm-gateway)).
- A tool runs only after the client parses a `tool_use` block, so a different model cannot skip the gate. It can
  only make different calls.
- We found no report of a hook or permission rule being bypassed because of the model. The one "hook did not
  block" report (#31250) was a timeout on a Claude model, which `onFailure: "block"` now closes (commit 11bb8f2).

**What does not stay the same:**

| Issue | Evidence | What to do |
|---|---|---|
| Not supported by Anthropic | "doesn't support routing Claude Code to non-Claude models through any gateway" ([LLM gateway](https://code.claude.com/docs/en/llm-gateway)) | treat each Claude Code upgrade as untested until our smoke test passes |
| Model-judged checks move to the vendor model | auto-mode classifier calls and `type: "prompt"`/`"agent"` hooks run on a model; behind a gateway the classifier uses the model in `ANTHROPIC_DEFAULT_SONNET_MODEL` ([permission modes](https://code.claude.com/docs/en/permission-modes), [hooks](https://code.claude.com/docs/en/hooks)) | our hooks are all `command` hooks, which are deterministic; do not use auto mode, use explicit deny rules |
| New betas and tools cause 400s | thinking and beta fields rejected; DeepSeek broke subagents, WebSearch and WebFetch in #65863; deferred tools in #89211 ([gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol), [#65863](https://github.com/anthropics/claude-code/issues/65863), [#89211](https://github.com/anthropics/claude-code/issues/89211)) | pin the Claude Code version; `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`; `ENABLE_TOOL_SEARCH=false` |
| Fields ignored silently | e.g. DeepSeek ignores `tool_choice: any`, `is_error`, `cache_control` | expect behaviour and cost to shift with no error; count failures per tool |
| Server-side tools missing | WebSearch is available only on Anthropic's API, AWS and Foundry ([tools](https://code.claude.com/docs/en/tools-reference)) | the research skills that search must say so, or use our own fetch tool |
| Many tools confuse small models | with 259 tool definitions an Ollama Qwen model "outputs plain text instead of tool_use blocks" ([#25857](https://github.com/anthropics/claude-code/issues/25857)) | keep the tool set small (`--tools`) |
| Tool-call reliability | V: CC-Bench, built on Claude Code: tool-call success GLM-4.5 90.6%, Kimi-K2 86.2%, Qwen3-Coder 77.1% ([paper](https://arxiv.org/pdf/2508.06471)); secondary: Claude Code + GLM-4.7 on Terminal-Bench 2.0, 33.5% passed, 10.8% errors ([analysis](https://gist.github.com/simonw/3bff274abcbbbf8766e9437a542db248)) | a model that calls tools less is not less enforced, but it is less useful; measure before relying on it |

One note for this kit:
- `run_digest.py` passes `ANTHROPIC_BASE_URL` through its env allowlist, so a runner could be redirected to
  another endpoint.
- That is a feature for multi-model runs.
- The endpoint is a run condition, so it must be written into the run's output.
- In managed setups, pin it with `allowedProviders`.

### 6.3 Agents from Chinese vendors

| Agent | License, latest | Pre-tool hook | Disable native tools (MCP only) | Sandbox | Admin lock | Telemetry default |
|---|---|---|---|---|---|---|
| Qwen Code (Gemini CLI fork) | Apache-2.0; v0.26.4, 2026-10-29 ([repo](https://github.com/QwenLM/qwen-code)) | `PreToolUse`, exit 2 blocks, `permissionDecision`; other exit codes do not block ([docs](https://qwenlm.github.io/qwen-code-docs/), section Features › Hooks) | `permissions.deny`, "Highest priority" ([docs](https://qwenlm.github.io/qwen-code-docs/), section Configuration › Settings) | `QWEN_SANDBOX` docker/podman; seatbelt on macOS; approval mode default `auto` | **yes**: system settings file "override user and project settings" | **on**: "Usage statistics are enabled by default", sent to Alibaba Cloud ([repo](https://github.com/QwenLM/qwen-code), file `tos-privacy.md` under docs, support section) |
| Kimi Code CLI (successor of the archived kimi-cli) | MIT; 2.4.1, 2026-10-30 ([repo](https://github.com/MoonshotAI/kimi-code)) | `PreToolUse`, exit 2 blocks; **fail open**: "a failed hook never blocks an operation" ([hooks](https://moonshotai.github.io/kimi-code/en/customization/hooks.html)) | `[tools] enabled` / `disabled`, MCP tools by glob ([config](https://moonshotai.github.io/kimi-code/en/configuration/config-files)) | not found | not found | `telemetry` default `true`, destination not stated |
| CodeBuddy Code (Tencent) | closed; v2.178.1 ([settings](https://www.codebuddy.ai/docs/cli/settings)) | `PreToolUse` (Beta), exit 2 blocks, others proceed ([hooks](https://www.codebuddy.ai/docs/cli/hooks)) | `permissions.deny`; its docs say Bash patterns "can be bypassed" | bash sandbox, macOS and Linux, default off | "managed settings" mentioned, no path | `DISABLE_TELEMETRY=1`; default and destination not stated |
| Trae Agent (open) / Trae IDE | Agent MIT, `0.1.0`, no releases ([repo](https://github.com/bytedance/trae-agent)); IDE closed | not found | Agent: per-agent tool list (implied) | Agent: Docker mode | not found | IDE: chats "may be stored and used for … model training" unless Privacy Mode is on ([blog](https://www.trae.ai/blog/product_thought_0819)) |
| ZCode (Zhipu) | license not stated; v3.16.3 ([site](https://zcode.z.ai/en)) | not found | not found | not found | not found | not found |
| DeepSeek | no first-party agent found; its docs point to Claude Code or OpenCode ([guide](https://api-docs.deepseek.com/guides/anthropic_api)) | – | – | – | – | – |
| iFlow CLI | shut down 2026-04-17 ([repo](https://github.com/iflow-ai/iflow-cli)) | – | – | – | – | – |
| Manus | hosted SaaS. A 2026-04-27 Chinese security-review order to unwind Meta's acquisition (secondary only, e.g. [law firm note](https://www.dahuilawyers.com/en/news-insights/chinas-first-public-foreign-investment-security-review-prohibition-the-metamanus-decision/)) | not applicable: no local tools we control | – | – | – | – |

Only **Qwen Code** has both a blocking hook and an admin lock. It inherits Gemini CLI's structure, so section 3's
Gemini CLI row largely applies to it, but each setting must be re-checked in Qwen's own docs.

None of these agents documents a fail-closed option for its hooks. Treat them as L2-optional, the same as Codex
in section 3.

### 6.4 Risks

**Data leaving the machine** (from each vendor's terms):

| Platform | Where | Training on API data | Retention | Source |
|---|---|---|---|---|
| DeepSeek | "store your Personal Data in People's Republic of China" | may be used "to train and improve"; opt-out by email | "as long as you have an account" | [privacy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) |
| Moonshot (international, Singapore) | servers in Singapore | **by default**; opt-out only via "enterprise arrangements" | while the account is active | [privacy](https://platform.kimi.ai/docs/agreement/userprivacy.md), [terms](https://platform.kimi.ai/docs/agreement/modeluse) |
| Alibaba Model Studio (international regions) | Singapore, US, Frankfurt, Hong Kong, Tokyo | **not without separate consent** | "no longer than 30 days"; zero retention on approval | [retention](https://www.alibabacloud.com/help/en/model-studio/data-retention-policy) |
| Z.ai | operator in Singapore (secondary) | "will not use … unless you explicitly agree", **printed in brackets**, so possibly a draft | not found (the data processing addendum page returned 404) | [terms](https://docs.z.ai/legal-agreement/terms-of-use) |
| BytePlus (ByteDance, international) | Malaysia, Indonesia, EU | not without prior authorization (read through a search summary) | flagged content 180 days | [data processing](https://docs.byteplus.com/en/docs/ModelArk/BytePlus_ModelArk_Data_Processing) |
| MiniMax | not verified from a primary source | not verified | not verified | – |
| Mainland-China platforms (Volcengine, Beijing region, bigmodel.cn, moonshot.cn) | not checked | not checked | not checked | – |

Other risks:
- **Endpoints and versions move fast.** Model names are retired within months; DeepSeek renamed `deepseek-v4-flash`
  in October. Z.ai has verified its Claude Code setup only against 2.0.14. A run must record the endpoint, the model
  name it was given and the Claude Code version.
- **Local hardware.**
  - On one RTX 5080 16 GB, only Qwen3.8-27B at INT4 fits, marginally and with short context. Everything near
    the frontier needs ≥ 160 GB at INT4: GLM-5.3-Flash, or DeepSeek V4-Flash at ~140 GB.
  - That means two 80 GB GPUs on GCP for the smallest of them, which costs money and needs the usual approval.
- **Licenses.** Custom licenses (Kimi K3, GLM-5.3, Qwen3.8 Max, MiniMax) need reading before any redistribution
  of outputs or fine-tunes. MIT and Apache-2.0: DeepSeek V4, GLM-5.3-Flash, Qwen3.8-27B.

### 6.5 Where this fits, and a minimum viable multi-model setup

These models fit the plan in section 4 without changing it.

- **L1 and L3 do not depend on the model at all.**
- **L2 does not either, as long as the driving agent is Claude Code.** Its hooks and permission rules are client-side.
- The cheapest way to change models without losing enforcement is to change the endpoint, not the agent.
- A Chinese-vendor agent (Qwen Code, Kimi Code, CodeBuddy) can be used where its hook is enough. It counts as
  "L1 + L3 only" until its hook failure modes are tested.

**Minimum viable multi-model setup:**

1. **One agent: Claude Code at a pinned version.**
   - Use our plugins with `onFailure: "block"`.
   - Add managed deny rules for anything a model must never do.
   - Run inside WSL2 (automount and interop off) or the VM, with the sandbox's `failIfUnavailable: true`.
2. **The model is a run condition, chosen per run by environment.**
   - Variables: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_DEFAULT_*_MODEL`, and
     `CLAUDE_CODE_SUBAGENT_MODEL` set explicitly.
   - The run writes the endpoint, model and Claude Code version into its own output.
   - There is no default: a missing value raises.
3. **Compatibility switches:**
   - `CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1`
   - `ENABLE_TOOL_SEARCH=false`
   - no auto mode
   - a small `--tools` set
4. **Endpoint choice, for research code and unpublished results:**
   - Prefer platforms whose terms say "no training without consent" outside mainland China: Alibaba Model Studio
     international (Qwen), BytePlus (Doubao, and other vendors' models it serves).
   - Moonshot trains by default and DeepSeek stores data in the PRC. Use either only for material that is already
     public, and only after the owner decides.
5. **Gate before first use of any endpoint or Claude Code version.** Run a positive-control script with that model:
   - a command our hook must block is blocked;
   - a deny rule holds;
   - Edit, Bash and a subagent each complete one task.
   Record the result. A model that fails the tool smoke test is not used for experiments; that is a usefulness
   failure, not an enforcement one.
   Implemented as `python -m rak.models control <id>`, with one profile per vendor
   ([model-profiles.md](model-profiles.md)).
6. **Local model as an option, not a dependency.** Qwen3.8-27B at INT4 is the only candidate for the RTX 5080. It
   would sit behind an Anthropic-compatible proxy we run, so the proxy becomes part of L2's trusted path. Bigger
   open models go on GCP under the normal budget approval.

Not checked for this section:
- the mainland platforms' terms;
- MiniMax's privacy policy (primary page did not render);
- Trae IDE and ZCode controls;
- Qwen Code hook timeout behaviour;
- independent Terminal-Bench numbers;
- the 220B vs 428B conflict on the MiniMax M3.1-Flash card.
