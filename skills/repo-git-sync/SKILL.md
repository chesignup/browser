---
name: repo-git-sync
description: >-
  Push local browser-stack changes to GitHub with a cheap subagent: git status,
  commit, README/DEPLOY updates, and git push. Use whenever files in the
  chesignup/browser repo (or /home/s/opt/browser) changed, after scrape dumps,
  research outputs, skills, qemu-browser, or when the user says commit, push,
  update github, or keep the repo current.
---

# Repo git sync (cheap subagent)

After material work on this stack, **do not** hand-commit in the parent agent.
Launch one **cheap, low-effort** subagent to git + README + push.

## How

Use the Task tool:

- `subagent_type`: `generalPurpose`
- `model`: `composer-2.5-fast` (cheap). If that slug is rejected, `cursor-grok-4.6-medium`.
- `run_in_background`: `false`
- `description`: `GitHub sync browser`

Prompt the subagent with this (fill in the actual change summary):

```
Repo: /home/s/opt/browser  (GitHub https://github.com/chesignup/browser)
Remote: origin main. Do NOT git config, force-push, or --no-verify.

1. git status, git diff, git log -5 --oneline
2. Stage only product files (code, skills, scrape, qemu-browser, data/yad2 dumps,
   FINDINGS/README). Do not stage secrets (.env, vnc_pass, id_ed25519, tokens).
3. Update README.md and/or DEPLOY.md if user-visible paths/commands changed.
4. Commit with a 1–2 sentence message (why, not file list) via HEREDOC.
5. git push origin HEAD
6. Return: commit hash, PR/repo URL, list of files committed.

Commit rules: only commit when this sync is the job (the parent already decided
to publish). Never amend pushed commits. Never git -i.
```

If GitHub already has the same tree, return “nothing to push”.

## When the parent still commits itself

Only if Task is unavailable. Then follow the same safety rules in-process.
