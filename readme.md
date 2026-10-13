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

This patch adds `tools/skills_hub_garena.py` and edits
`tools/skills_hub_search.py` so Hermes uses a restricted source router:

```text
garena-skillhub
```

The source is implemented by `GarenaSkillHubSource`. It talks to
`skillhub.ingarena.net` using the ClawHub public v1 API contract.

## What Changes

The patch:

- restricts `create_source_router()` to `garena-skillhub`
- disables `official`, `hermes-index`, `skills-sh`, `well-known`, `url`,
  `github`, `clawhub`, `lobehub`, and `browse-sh` as active skill acquisition
  routes
- adds `GarenaSkillHubSource`
- implements search, metadata lookup, version fallback, file fallback, and ZIP
  download against the ClawHub public v1 API contract
- sends `SKILLHUB_TOKEN` as a bearer token on Garena SkillHub HTTP requests

Default SkillHub URL:

```text
https://skillhub.ingarena.net
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

## Requirements

Hermes >= v0.21.6, where the skill source router is `create_source_router()`
in `tools/skills_hub_search.py`, and `python3` >= 3.11 to run the installer.

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

- writes `/path/to/hermes-agent/tools/skills_hub_garena.py`
- adds its import to `/path/to/hermes-agent/tools/skills_hub_search.py` and
  replaces `create_source_router()` there
- fails without writing when `skills_hub_search.py` lacks the `ClawHubSource`
  import or exactly one top-level `create_source_router()`
- writes `SKILLHUB_URL` to `~/.hermes/.env`
- writes `SKILLHUB_TOKEN` to `~/.hermes/.env` when `--token` is supplied

Running it again on a patched tree rewrites `skills_hub_garena.py` and leaves
`skills_hub_search.py` as it is.

When `install.sh` is executed through `curl | bash`, it downloads
`scripts/apply_patch.py` from the same GitHub repo/ref before applying the
source patch.

Install from a fork or branch:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --repo OWNER/REPO --ref BRANCH --hermes-root /path/to/hermes-agent --check
```

## Verify

After patching, ask the installed Hermes which sources its router returns:

```bash
hermes --run-module tools.skills_hub_garena
```

It prints `['garena-skillhub']` and exits 0 when the patch is active, and exits
non-zero otherwise.

Then validate against the live SkillHub service:

```bash
hermes skills search <skill-name>
hermes skills install <skill-name>
```

## Operational Notes

Because the Hermes source tree is modified in place, a Hermes upgrade may
replace these files. Re-run this installer after upgrading Hermes.

To remove the patch, run in the Hermes checkout:

```bash
git checkout -- tools/skills_hub_search.py && rm tools/skills_hub_garena.py
```
