# OpenClaw: what it is, how it fits, and whether to integrate

Status: investigation only. Nothing was installed or run. All sources were read on 2026-10-31.
Facts carry their source. "Not found" means the source pages did not say it, not that it is false.
Secondary sources (news, vendor blogs) are marked as such.

## 1. Which project

| Item | Finding | Source |
|---|---|---|
| Project | `openclaw/openclaw`, a self-hosted personal AI assistant: "The AI that really does things. Any OS. Any Platform." | [GitHub repo](https://github.com/openclaw/openclaw) |
| Former names | Clawdbot, Moltbot (the CVE record says "OpenClaw (aka clawdbot or Moltbot)") | [OSV CVE-2026-25253](https://api.osv.dev/v1/vulns/CVE-2026-25253) |
| License | MIT | [GitHub repo](https://github.com/openclaw/openclaw) (one listing says Apache-2.0; the repo says MIT) |
| Activity | about 393k stars, 5k+ open issues, 2.9k open pull requests on the repo page | [GitHub repo](https://github.com/openclaw/openclaw) |
| Latest release | `2026.10.9` (marked Latest, 29 Oct); `2026.10.10-beta.5` pre-release on 30 Oct | [Releases](https://github.com/openclaw/openclaw/releases) |
| Release cadence | three releases in two days, each with security fixes (credential masking, allowlists fail closed, dependency patches) | [Releases](https://github.com/openclaw/openclaw/releases) |

Maintained and very active. The cadence also means a pinned version goes stale within days.

## 2. Architecture

| Part | What it is | Source |
|---|---|---|
| Gateway | "local control plane for sessions, tools, events, and channel connections"; Control UI, CLI and TUI connect to it | [GitHub repo](https://github.com/openclaw/openclaw) |
| Default bind | loopback on a host install; **container images bind an exposed address by default** | [Security](https://docs.openclaw.ai/gateway/security) |
| Channels | Telegram, WhatsApp, Discord, Slack, Signal, iMessage, Teams, Google Chat and "20+ more" | [GitHub repo](https://github.com/openclaw/openclaw) |
| Telegram | bot token via `botToken` or `tokenFile` (symlinks rejected); DMs default to `pairing`, groups to `allowlist` | [Telegram channel](https://docs.openclaw.ai/channels/telegram) |
| Skills | directories with `SKILL.md`; follows the AgentSkills spec (section 3) | [Skills](https://docs.openclaw.ai/tools/skills) |
| Skill registry | ClawHub, open upload | [GitHub repo](https://github.com/openclaw/openclaw); upload rule: [The Hacker News](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html) (secondary) |
| Memory | plain Markdown in the workspace (`~/.openclaw/workspace`): `MEMORY.md` loaded at session start, `memory/YYYY-MM-DD.md` daily notes, optional `USER.md`, `DREAMS.md`; hybrid vector + keyword search, OpenAI embeddings by default; a hidden "memory flush" turn before compaction is on by default | [Memory](https://docs.openclaw.ai/concepts/memory) |
| Scheduling | `openclaw automations` (alias `openclaw cron`); jobs persist; output goes to a chat channel, a webhook or nowhere; heartbeat is being migrated into ordinary jobs. Storage location: not found | [Cron jobs](https://docs.openclaw.ai/automation/cron-jobs) |
| Execution | tools "run on the host for the main session unless you configure sandboxing"; "Sandboxing is off by default"; Docker is the default local sandbox backend | [GitHub repo](https://github.com/openclaw/openclaw), [Sandboxing](https://docs.openclaw.ai/gateway/sandboxing) |
| Claude Code backend | `claude-cli` backend drives the installed `claude` over its stdio protocol. Gateway tools reach it through a loopback MCP bridge as `mcp__openclaw__<name>`. **Native `Bash` is disabled on local bundled turns; shell work goes through OpenClaw's `exec`.** Claude Code is launched "with its default permission mode", and OpenClaw answers its permission requests and installs its own `PreToolUse` hook | [CLI backends](https://docs.openclaw.ai/gateway/cli-backends) |
| Telemetry | daily version check by default; `update.checkOnStart: false` turns it off | [GitHub repo](https://github.com/openclaw/openclaw) |

## 3. Skill format compatibility

OpenClaw: "OpenClaw follows the AgentSkills spec" ([Skills](https://docs.openclaw.ai/tools/skills)).
It reads `name` and `description` and adds its own fields (`user-invocable`, `disable-model-invocation`,
`command-dispatch`, and gating under `metadata.openclaw`: `os`, `requires.bins`, `requires.env`, `install`).

The AgentSkills spec ([specification](https://agentskills.io/specification)) defines `name`, `description`, `license`,
`compatibility`, `metadata` (string to string) and the experimental `allowed-tools`.

This kit's 17 `SKILL.md` files use only `name`, `description`, `license`, `compatibility` and `metadata`
(checked with grep on this commit). So **the instruction text loads in OpenClaw as is.** What does not carry over:

| Kit part | In OpenClaw | Why |
|---|---|---|
| `SKILL.md` instructions | loads | same spec |
| Scripts referenced as `<plugin>/scripts/...` or `${CLAUDE_PLUGIN_ROOT}` (6 of 17 skills) | paths must be rewritten | OpenClaw uses `{baseDir}`, and only for the skill folder; our scripts live at the plugin level |
| `rak-discipline` hook (`guard.py`: prereg launch guard, append-only results) | **does not run** | it is a Claude Code `PreToolUse` hook matching `Bash|Edit|MultiEdit|Write`. OpenClaw has no Claude Code hooks; through the `claude-cli` backend, shell work goes through `mcp__openclaw__exec`, which that matcher never sees (inferred from the CLI-backends page, not tested) |
| `rak-team` hook (`git_guard.py`) | does not run | same reason |
| Permission rules in `run_digest.py` (`--tools`, deny lists, `blockReadsOutsideWorkingDirectories`) | do not apply | they are Claude Code CLI flags; OpenClaw's skill allowlists are "not a host shell authorization boundary" ([Skills](https://docs.openclaw.ai/tools/skills)) |

The research discipline in this kit lives in hooks and in the permission system, not in skill text.
A port of the skills alone keeps the advice and loses the enforcement.

## 4. Known security issues

| Issue | Finding | Source |
|---|---|---|
| CVE-2026-25253 (GHSA-g8p2-7wf7-98mq) | before 2026.1.29 the Control UI took `gatewayUrl` from a query string and opened a WebSocket to it with the gateway token: one click leaks the token, then full control. CVSS 3.1 8.8 | [OSV](https://api.osv.dev/v1/vulns/CVE-2026-25253), [NVD](https://nvd.nist.gov/vuln/detail/CVE-2026-25253) |
| Exposed instances | SecurityScorecard STRIKE: "more than 40,000" exposed instances in the first 24 hours of scanning, 35.4% flagged vulnerable (11 Feb 2026). Later press figures reach 135,000 | [SecurityScorecard](https://securityscorecard.com/blog/how-exposed-openclaw-deployments-turn-agentic-ai-into-an-attack-surface/); [The Register](https://theregister.com/2026/02/09/openclaw_instances_exposed_vibe_code) (secondary) |
| Malicious skills | Koi Security audited 2,857 ClawHub skills: 341 malicious, 335 from one campaign ("ClawHavoc") using fake "Prerequisites" to install a macOS stealer; others stole bot credentials from config files or hid reverse shells. Publishing needed only a GitHub account one week old | [The Hacker News](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html) (secondary; Koi's original report not read) |
| Registry response | since 7 Feb 2026 every ClawHub skill is checked with VirusTotal (hash lookup, then LLM-based Code Insight), rescanned daily. The maintainers say it is "not a silver bullet" and "A carefully crafted prompt injection payload won't show up in a threat database" | [OpenClaw blog](https://www.openclaw.ai/blog/virustotal-partnership) |
| Prompt injection | docs say inbound messages are "untrusted input"; agents with message-tool access "can send across conversations and providers by default" | [GitHub repo](https://github.com/openclaw/openclaw), [Security](https://docs.openclaw.ai/gateway/security) |
| Trust model | "One trust boundary per gateway"; "OpenClaw is not a hostile multi-tenant security boundary for mutually adversarial users" | [Security](https://docs.openclaw.ai/gateway/security) |
| Secrets | skill `env` / `apiKey` entries are injected into the host process | [Skills](https://docs.openclaw.ai/tools/skills) |
| Self-check | `openclaw security audit` reports drift from safe defaults | [Security](https://docs.openclaw.ai/gateway/security) |

Other CVE numbers appear in blog lists (for example CVE-2026-24763, CVE-2026-25157). We did not check them against
NVD or the project's advisories, so they are not listed above.

What this means for us. Our use would put three things in one process: a Telegram inbox (untrusted text), host
execution (unsandboxed by default), and research credentials (cloud, Hugging Face, the bot token). That is the
combination the incidents above exploit. Compare the kit's current design: the agent that reads chat messages has no
shell beyond three exact commands (`daily-digest`), and approvals over chat are limited to an allowlist (`notify`,
`docs/security.md`).

## 5. Integration options

### A. Package our skills for OpenClaw

Ship `SKILL.md` files that OpenClaw can load: rewrite script paths to `{baseDir}`, move needed scripts into each skill
folder, add `metadata.openclaw.requires` (python, git).

- Gain: reach OpenClaw users; little code.
- Risk: users get the advice without the enforcement (section 3) and may believe a prereg is guarded when it is not.
  Publishing to ClawHub puts our name in a registry with a malware history, and a look-alike upload is easy.
- Work: about 1–2 days, plus a test that every skill still validates against the AgentSkills spec.
- Must say, in every ported skill: "No launch guard in this environment."

### B. OpenClaw as the messaging and scheduling front end; discipline stays in Claude Code

OpenClaw receives Telegram messages and runs schedules. Experiment work is handed to a separate `claude` process
started in the project, with our plugins and hooks, the same way `run_digest.py` starts it today.

- Gain: one inbox for many channels, scheduling, mobile apps; our hooks still guard the work, because they run inside
  that child process.
- Risk: the front end itself needs `exec` to start the child, and that `exec` runs on the host unless sandboxing is
  configured. A prompt-injected message can then ask the front end to run something other than our command.
  The `claude-cli` backend is not this design: it routes shell through OpenClaw's `exec`, so our `Bash` hook does not see it.
- Work: about 1 week: a dedicated OS user or VM, sandbox on, an `exec` allowlist that admits only fixed launch
  commands, Telegram `dmPolicy: allowlist`, no ClawHub skills, a pinned version and a plan to keep up with releases.
  Each of those settings needs its own test before the first real message.

### C. Do not integrate; document interoperability

Keep the official Claude Code Channels (and the fallback bridge) in `notify`. Add one paragraph to the README: the
skills follow the AgentSkills spec, so other agents can read them, and the hooks are Claude Code only.

- Gain: no new attack surface; no extra upkeep.
- Risk: no WhatsApp/Signal, no OpenClaw apps; users who already run OpenClaw wire it up themselves, unguarded.
- Work: under an hour.

## 6. Recommendation

**C now, with the spec check from A; B only as a sandboxed trial the owner approves.**

Reasons:

1. The kit's value is enforcement. Option A cannot carry it; option B can, but only if the front end is locked down,
   and the most important lock is off by default: sandboxing is off and tools run on the host. (DM pairing is on by
   default; the default for an `exec` allowlist was not found.)
2. Our current notification path already covers the need that was asked about (results to Telegram, replies back).
3. The project changes daily. Any integration needs someone to track releases and advisories; that cost recurs.

If B is approved, run it first in a VM or a separate OS user with no cloud credentials, and treat "a chat message
caused a command outside the allowlist" as the gate that must fail before anything else is connected.

## 7. Not checked

- Koi Security's original report and ClawHub's current malicious-skill counts (only secondary sources read).
- Where scheduled jobs are stored, and whether isolated cron jobs can be confined to a sandbox.
- Whether OpenClaw's own `PreToolUse` hook replaces or runs alongside hooks from plugins installed in Claude Code.
- Behaviour of any of the above in practice: nothing was installed or run.
