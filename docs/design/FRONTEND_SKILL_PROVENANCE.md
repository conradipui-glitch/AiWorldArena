# Frontend Design Skill Provenance

## Installed upstream baseline

- **Skill name:** `frontend-design`
- **Official repository:** `https://github.com/anthropics/skills.git`
- **Path in repository:** `skills/frontend-design`
- **Pinned commit:** `2235be7c60b551f5de82ade908fd3816455afcda`
- **Pinned commit message:** `Update frontend-design skill (#1293)`
- **Installation date:** 2026-07-15
- **Local path:** `.agents/skills/frontend-design/`
- **Upstream modification:** none; local Git blob identifiers match the two files at the pinned commit.

## Copied files and SHA-256

| File | SHA-256 |
|---|---|
| `SKILL.md` | `1608ea77fbb6fc30d13a97d12cfa8ebf31358d40f0dd97beed24829d6b3f45dd` |
| `LICENSE.txt` | `0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594` |

The source directory and installed directory contain exactly these two regular files. No scripts,
executables, package manifests, dependencies, assets, references, or other files were present.

## License

`LICENSE.txt` contains the Apache License, Version 2.0.

## Skill validation

- The YAML frontmatter is a valid simple YAML mapping and contains both required fields:
  `name: frontend-design` and a non-empty `description`.
- The document contains no Markdown links to local paths and no references to local scripts,
  assets, package manifests, or dependencies.
- The upstream `SKILL.md` was copied without translation, project-specific additions, or other edits.
- The skill is not specifically developed for GPT-5.6. It uses the compatible Agent Skills
  `SKILL.md` format.

## Codex discovery status

The active Codex session was created before this repository-scoped skill was installed, and its
already-loaded skill catalog does not yet list `frontend-design`. Discovery by a new or restarted
Codex session must be confirmed before using the skill. This checkpoint does not claim activation
and does not invoke the skill for design work.

## Update procedure

To update this vendored baseline, use only the official repository above. Fetch the intended commit,
verify the remote URL, commit identity, and that `skills/frontend-design` contains only `SKILL.md`
and `LICENSE.txt`; check for an active skill-name conflict; then replace the two files unchanged,
recompute SHA-256 hashes, and update this provenance record in a separate reviewed commit.
