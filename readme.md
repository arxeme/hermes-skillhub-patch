# hermes-skillhub-patch

`hermes-skillhub-patch` is a source patch for
[Hermes Agent](https://github.com/NousResearch/hermes-agent). It changes how
Hermes discovers and installs skills.

The patch is intended for managed environments that need to control where
Hermes can fetch skills from. After installation, Hermes routes the `clawhub`
source id to a company SkillHub endpoint and removes other skill acquisition
routes from the active router.

## Purpose

Hermes supports multiple skill sources by default, including public registries,
GitHub, direct URLs, and marketplace indexes. That is convenient for general
use, but it is not suitable when skill installation must be limited to an
approved registry.

This patch modifies `tools/skills_hub.py` so Hermes uses a restricted source
router:

```text
clawhub
```

The `clawhub` source id is kept for CLI and lock-file compatibility, but the
implementation is redirected to a SkillHub service that supports a
ClawHub-compatible protocol.

## What Changes

The patch updates Hermes behavior in three areas:

- restricts `create_source_router()` to `clawhub`
- disables `official`, `url`, `github`, `hermes-index`, `skills-sh`,
  `well-known`, `claude-marketplace`, and `lobehub` as active skill acquisition
  routes
- changes `ClawHubSource` to use `SKILLHUB_URL` and `SKILLHUB_TOKEN` from the
  Hermes `.env`

Default SkillHub URL:

```text
https://skillhub.ingarena.net
```

Generated API base:

```text
https://skillhub.ingarena.net/api/v1
```

## Supported Protocol

The patched `clawhub` adapter expects a ClawHub-compatible SkillHub protocol:

| Operation | Endpoint |
|---|---|
| Search / inspect | `GET /api/event/skill/list` |
| Skill metadata | `GET /api/v1/skills/{slug}` |
| Skill download | `GET /api/v1/download` |

`SKILLHUB_TOKEN` is sent as:

```text
Authorization: Bearer <token>
```

## Install

Dry-run first:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --hermes-root /path/to/hermes-agent --check
```

Apply the patch:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --hermes-root /path/to/hermes-agent --token 'skh_...'
```

Use a custom SkillHub URL:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --hermes-root /path/to/hermes-agent --skillhub-url https://skillhub.example.com --token 'skh_...'
```

Local clone install:

```bash
./install.sh --hermes-root /path/to/hermes-agent --token 'skh_...'
```

## Installer Behavior

The installer:

- patches `/path/to/hermes-agent/tools/skills_hub.py`
- creates `/path/to/hermes-agent/tools/skills_hub.py.bak` unless `--no-backup`
- writes `SKILLHUB_URL` to `~/.hermes/.env`
- writes `SKILLHUB_TOKEN` to `~/.hermes/.env` when `--token` is supplied

When `install.sh` is executed through `curl | bash`, it downloads
`scripts/apply_patch.py` from the same GitHub repo/ref before applying the
source patch.

Install from a fork or branch:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --repo OWNER/REPO --ref BRANCH --hermes-root /path/to/hermes-agent --check
```

Restore from backup:

```bash
./install.sh --hermes-root /path/to/hermes-agent --restore
```

## Verify

After patching:

```bash
cd /path/to/hermes-agent
python3 -m py_compile tools/skills_hub.py
python3 - <<'PY'
from tools.skills_hub import ClawHubSource, create_source_router
print(ClawHubSource.BASE_URL)
print([source.source_id() for source in create_source_router()])
PY
```

Expected output:

```text
https://skillhub.ingarena.net/api/v1
['clawhub']
```

Then validate against the live SkillHub service:

```bash
hermes skills search <skill-name>
hermes skills install <skill-name>
```

## Operational Notes

This is a source patch. It does not use `sitecustomize.py`, `PYTHONPATH`, or a
Hermes wrapper. Hermes imports its own patched `tools/skills_hub.py` normally.

Because the Hermes source file is modified in place, a Hermes upgrade may
replace `tools/skills_hub.py`. Re-run this installer after upgrading Hermes.

Use this patch when you want a controlled Hermes installation where skill
acquisition is limited to the approved SkillHub path while preserving
`clawhub` source compatibility.
