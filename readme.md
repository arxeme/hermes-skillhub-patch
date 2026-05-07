# hermes-skillhub-patch

`hermes-skillhub-patch` is a source patch for
[Hermes Agent](https://github.com/NousResearch/hermes-agent). It changes how
Hermes discovers and installs skills.

The patch is intended for managed environments that need to control where
Hermes can fetch skills from. After installation, Hermes routes skill discovery
and installation through the `garena-skillhub` source and removes other skill
acquisition routes from the active router.

## Purpose

Hermes supports multiple skill sources by default, including public registries,
GitHub, direct URLs, and marketplace indexes. That is convenient for general
use, but it is not suitable when skill installation must be limited to an
approved registry.

This patch modifies `tools/skills_hub.py` so Hermes uses a restricted source
router:

```text
garena-skillhub
```

The source is implemented by `GarenaSkillHubSource`. It talks to
`skillhub.ingarena.net` using the ClawHub public v1 API contract.

## What Changes

The patch updates Hermes behavior in three areas:

- restricts `create_source_router()` to `garena-skillhub`
- disables `official`, `url`, `github`, `hermes-index`, `skills-sh`,
  `well-known`, `claude-marketplace`, and `lobehub` as active skill acquisition
  routes
- adds `GarenaSkillHubSource`
- implements search, metadata lookup, version fallback, file fallback, and ZIP
  download against the ClawHub public v1 API contract
- sends `SKILLHUB_TOKEN` as a bearer token on Garena SkillHub HTTP requests

Default SkillHub URL:

```text
https://skillhub.ingarena.net
```

Generated API base:

```text
https://skillhub.ingarena.net/api/v1
```

## Supported Protocol

The patched adapter follows the ClawHub CLI/API contract. The default API base
is:

```text
https://skillhub.ingarena.net/api/v1
```

The source uses the endpoints exercised by the ClawHub CLI and API handlers:

- `GET /api/v1/search?q=<query>&limit=<n>`
- `GET /api/v1/skills?limit=<n>&sort=updated`
- `GET /api/v1/skills/{slug}`
- `GET /api/v1/skills/{slug}/versions/{version}`
- `GET /api/v1/skills/{slug}/file?path=<path>&version=<version>`
- `GET /api/v1/download`

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

If Hermes is already patched and a `.bak` file exists, the installer restores
from `.bak` first and then reapplies the patch. This keeps repeat installs
working after the patch script changes.

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
from tools.skills_hub import GarenaSkillHubSource, create_source_router
print(GarenaSkillHubSource.BASE_URL)
print([type(source).__name__ for source in create_source_router()])
print([source.source_id() for source in create_source_router()])
PY
```

Expected output:

```text
https://skillhub.ingarena.net/api/v1
['GarenaSkillHubSource']
['garena-skillhub']
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
acquisition is limited to the approved Garena SkillHub path.
