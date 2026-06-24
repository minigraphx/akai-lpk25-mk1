# `.claude/` — project-level Claude Code configuration

This directory makes a set of development-workflow **skills** available to any
Claude Code session working in this repository (including ephemeral
cloud/web sessions, which clone the repo fresh and would otherwise have no
skills installed).

## `skills/` — vendored Superpowers

A complete copy of the **Superpowers** skill library:

- **Source:** https://github.com/obra/superpowers (`main`, downloaded 2026-06-23)
- **Version:** 6.0.3
- **License:** MIT © Jesse Vincent — see [`skills/LICENSE`](skills/LICENSE)

These are third-party files vendored verbatim so the workflow is durably
available without a network install. Skills included:

`brainstorming`, `writing-plans`, `executing-plans`,
`subagent-driven-development`, `dispatching-parallel-agents`,
`test-driven-development`, `systematic-debugging`,
`requesting-code-review`, `receiving-code-review`,
`verification-before-completion`, `using-git-worktrees`,
`finishing-a-development-branch`, `writing-skills`, `using-superpowers`.

Claude Code discovers each `skills/<name>/SKILL.md` automatically and exposes
it through the `Skill` tool.

### Updating

Re-download the upstream tarball and re-copy `skills/` and `hooks/`:

```sh
curl -sSL https://codeload.github.com/obra/superpowers/tar.gz/refs/heads/main | tar xz
cp -R superpowers-main/skills/. .claude/skills/
cp    superpowers-main/LICENSE   .claude/skills/LICENSE
cp -R superpowers-main/hooks/.   .claude/hooks/
```

## `hooks/` — optional SessionStart injection (NOT wired by default)

Upstream Superpowers ships a `SessionStart` hook that injects the
`using-superpowers` skill into context at the start of every session, so the
agent reaches for skills without being asked. The hook scripts are vendored
here but are **inert** — nothing runs them unless a `.claude/settings.json`
registers them.

To enable it, add a `SessionStart` hook to `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "CLAUDE_PLUGIN_ROOT=\"$CLAUDE_PROJECT_DIR/.claude\" \"$CLAUDE_PROJECT_DIR/.claude/hooks/run-hook.cmd\" session-start",
            "async": false
          }
        ]
      }
    ]
  }
}
```

This is left disabled by default because a startup hook auto-executes a script
on every session and should be enabled deliberately.
