# hermes-skillhub-patch

This directory implements the Garena SkillHub integration by patching Hermes
source code instead of relying on `sitecustomize.py`.

## Goal

- disable other public skill hub adapters in Hermes search/install routing
- keep the existing `clawhub` source id, but send it to `skillhub.ingarena.net`
- keep `SKILLHUB_URL` and `SKILLHUB_TOKEN` in the normal Hermes `.env`

## Install

Primary one-line install from GitHub:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --hermes-root /path/to/hermes-agent --token 'skh_...'
```

Dry-run first:

```bash
curl -fsSL https://raw.githubusercontent.com/arxeme/hermes-skillhub-patch/main/install.sh | bash -s -- --hermes-root /path/to/hermes-agent --check
```

Local clone install:

```bash
./install.sh --hermes-root /path/to/hermes-agent --token 'skh_...'
```

The installer:

- patches `/path/to/hermes-agent/tools/skills_hub.py`
- creates `/path/to/hermes-agent/tools/skills_hub.py.bak` unless `--no-backup`
- writes `SKILLHUB_URL=https://skillhub.ingarena.net` to `~/.hermes/.env`
- writes `SKILLHUB_TOKEN=...` to `~/.hermes/.env` when `--token` is supplied

When `install.sh` is executed through `curl | bash`, it downloads
`scripts/apply_patch.py` from the same GitHub repo/ref before applying the
source patch. Use `--repo OWNER/REPO` or `--ref REF` to install from a fork or
branch.

Hermes already loads `~/.hermes/.env` during CLI startup, before
`tools.skills_hub` is imported by `hermes_cli.skills_hub`, so the patched source
can read `SKILLHUB_URL` and `SKILLHUB_TOKEN` directly from the process
environment.

## Patched Behavior

`create_source_router()` is restricted to:

```text
official, clawhub
```

The disabled adapters are:

```text
url, github, hermes-index, skills-sh, well-known, claude-marketplace, lobehub
```

`ClawHubSource` remains named `clawhub` for CLI compatibility, but:

- search/inspect uses `GET /api/event/skill/list`
- fetch uses `GET /api/v1/skills/{slug}` and `GET /api/v1/download`
- `SKILLHUB_TOKEN` is sent as `Authorization: Bearer <token>`
- `SKILLHUB_URL` defaults to `https://skillhub.ingarena.net`

## Verification

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

Expected:

```text
https://skillhub.ingarena.net/api/v1
['official', 'clawhub']
```

Then validate against the live service:

```bash
hermes skills search gog
hermes skills install gog
```

## Evaluation

Compared with `hermes-skillhub-garena`, this approach is simpler at runtime:
there is no wrapper, no `PYTHONPATH`, and no import hook. Hermes imports its own
patched `tools/skills_hub.py` normally.

The tradeoff is update durability. A Hermes update may replace
`tools/skills_hub.py`, so this patch should be re-applied after every Hermes
upgrade. The installer keeps the change repeatable and fails closed if the
upstream file shape no longer matches the expected source.

Operationally, this is acceptable for controlled VM releases where the Hermes
install tree is managed by deployment scripts. It is worse than the
`sitecustomize.py` approach for ad-hoc user machines because source updates can
erase the patch.

Security posture improves relative to the default Hermes router because public
hub adapters plus direct URL/GitHub install routes are removed from the active
route. After patching, company SkillHub is the only remote registry path left in
the router.
