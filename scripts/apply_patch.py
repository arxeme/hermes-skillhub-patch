#!/usr/bin/env python3
"""Apply the Garena SkillHub source patch to a Hermes checkout."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


HELPER_MARKER = "# BEGIN Garena SkillHub patch"

HELPERS = r'''
# BEGIN Garena SkillHub patch
DEFAULT_GARENA_SKILLHUB_URL = "https://skillhub.ingarena.net"


def _garena_skillhub_root_url() -> str:
    raw = os.environ.get("SKILLHUB_URL") or DEFAULT_GARENA_SKILLHUB_URL
    base = raw.strip().rstrip("/") or DEFAULT_GARENA_SKILLHUB_URL
    for suffix in ("/api/v1", "/api/event/skill"):
        if base.endswith(suffix):
            return base[: -len(suffix)]
    return base


def _garena_skillhub_api_base_url() -> str:
    return f"{_garena_skillhub_root_url()}/api/v1"


def _garena_skillhub_event_base_url() -> str:
    return f"{_garena_skillhub_root_url()}/api/event/skill"


def _garena_skillhub_auth_headers() -> Dict[str, str]:
    token = (os.environ.get("SKILLHUB_TOKEN") or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _garena_skillhub_event_get_json(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 30,
) -> Optional[Any]:
    try:
        resp = httpx.get(
            f"{_garena_skillhub_event_base_url()}/{path.lstrip('/')}",
            params=params or {},
            headers=_garena_skillhub_auth_headers(),
            timeout=timeout,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict):
        return payload
    if payload.get("code") == 200 and payload.get("status") == "success":
        return payload.get("data")
    return None


def _garena_skillhub_list_skills(query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"page": 1, "size": max(limit, 1)}
    if query:
        params["keyword"] = query
    data = _garena_skillhub_event_get_json("list", params=params)
    if not isinstance(data, dict):
        return []
    skills = data.get("skills", [])
    return skills if isinstance(skills, list) else []


def _garena_skillhub_item_to_meta(item: Dict[str, Any]) -> Optional[Any]:
    slug = item.get("slug")
    if not isinstance(slug, str) or not slug:
        return None
    tags = item.get("tags", [])
    if not isinstance(tags, list):
        tags = []
    return SkillMeta(
        name=item.get("name") or item.get("displayName") or slug,
        description=item.get("description") or item.get("summary") or "",
        source="clawhub",
        identifier=slug,
        trust_level="community",
        tags=[str(tag) for tag in tags],
    )


def _garena_skillhub_find_skill(slug: str) -> Optional[Dict[str, Any]]:
    for item in _garena_skillhub_list_skills(slug, limit=20):
        if isinstance(item, dict) and item.get("slug") == slug:
            return item
    return None


def _garena_skillhub_event_download_zip(slug: str, skill_id: Any) -> Dict[str, str]:
    import io
    import zipfile

    files: Dict[str, str] = {}
    try:
        resp = httpx.get(
            f"{_garena_skillhub_event_base_url()}/download",
            params={"id": skill_id},
            headers=_garena_skillhub_auth_headers(),
            timeout=30,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            logger.debug("Garena SkillHub event API ZIP download for %s returned %s", slug, resp.status_code)
            return files
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                try:
                    name = _validate_bundle_rel_path(info.filename)
                except ValueError:
                    logger.debug("Skipping unsafe ZIP member path: %s", info.filename)
                    continue
                if info.file_size > 500_000:
                    logger.debug("Skipping large file in ZIP: %s (%d bytes)", name, info.file_size)
                    continue
                try:
                    files[name] = zf.read(info.filename).decode("utf-8")
                except (UnicodeDecodeError, KeyError):
                    logger.debug("Skipping non-text file in ZIP: %s", name)
    except zipfile.BadZipFile:
        logger.warning("Garena SkillHub returned invalid ZIP (event API) for %s", slug)
    except httpx.HTTPError as exc:
        logger.debug("Garena SkillHub event API ZIP download failed for %s: %s", slug, exc)
    return files
# END Garena SkillHub patch
'''

CLASS_HEADER = '''class ClawHubSource(SkillSource):
    """
    Fetch skills from Garena SkillHub through the existing ClawHub source id.

    The source id stays "clawhub" so existing CLI flags and lock-file
    provenance keep working while the backend is company-owned.
    """

    BASE_URL = _garena_skillhub_api_base_url()
'''

SEARCH_METHOD = '''    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        query = query.strip()
        skills = _garena_skillhub_list_skills(query, limit=max(limit, 10))
        results: List[SkillMeta] = []
        for item in skills:
            if not isinstance(item, dict):
                continue
            meta = _garena_skillhub_item_to_meta(item)
            if meta is not None:
                results.append(meta)
        return self._finalize_search_results(query, results, limit)
'''

FETCH_METHOD = '''    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        slug = identifier.split("/")[-1]

        skill_data = self._get_json(f"{self.BASE_URL}/skills/{slug}")
        if not isinstance(skill_data, dict):
            return None

        latest_version = self._resolve_latest_version(slug, skill_data)
        if not latest_version:
            logger.warning("Garena SkillHub fetch failed for %s: could not resolve latest version", slug)
            return None

        files = self._download_zip(slug, latest_version)

        # Fallback: event API download via /api/event/skill/download when v1 download fails
        if "SKILL.md" not in files:
            item = _garena_skillhub_find_skill(slug)
            if item is not None:
                skill_id = item.get("id")
                if skill_id is not None:
                    files = _garena_skillhub_event_download_zip(slug, skill_id)

        if "SKILL.md" not in files:
            version_data = self._get_json(f"{self.BASE_URL}/skills/{slug}/versions/{latest_version}")
            if isinstance(version_data, dict):
                files = self._extract_files(version_data) or files
                if "SKILL.md" not in files:
                    nested = version_data.get("version", {})
                    if isinstance(nested, dict):
                        files = self._extract_files(nested) or files

        if "SKILL.md" not in files:
            logger.warning(
                "Garena SkillHub fetch for %s resolved version %s but could not retrieve file content",
                slug,
                latest_version,
            )
            return None

        return SkillBundle(
            name=slug,
            files=files,
            source="clawhub",
            identifier=slug,
            trust_level="community",
        )
'''

INSPECT_METHOD = '''    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        slug = identifier.split("/")[-1]
        item = _garena_skillhub_find_skill(slug)
        if item is None:
            return None
        return _garena_skillhub_item_to_meta(item)
'''

GET_JSON_METHOD = '''    def _get_json(self, url: str, timeout: int = 20) -> Optional[Any]:
        try:
            resp = httpx.get(
                url,
                headers=_garena_skillhub_auth_headers(),
                timeout=timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                return None
            return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError):
            return None
'''

DOWNLOAD_ZIP_METHOD = '''    def _download_zip(self, slug: str, version: str) -> Dict[str, str]:
        """Download skill as a ZIP bundle from Garena SkillHub and extract text files."""
        import io
        import zipfile

        files: Dict[str, str] = {}
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/download",
                params={"slug": slug, "version": version},
                headers=_garena_skillhub_auth_headers(),
                timeout=30,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.debug("Garena SkillHub ZIP download for %s v%s returned %s", slug, version, resp.status_code)
                return files

            with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    try:
                        name = _validate_bundle_rel_path(info.filename)
                    except ValueError:
                        logger.debug("Skipping unsafe ZIP member path: %s", info.filename)
                        continue
                    if info.file_size > 500_000:
                        logger.debug("Skipping large file in ZIP: %s (%d bytes)", name, info.file_size)
                        continue
                    try:
                        raw = zf.read(info.filename)
                        files[name] = raw.decode("utf-8")
                    except (UnicodeDecodeError, KeyError):
                        logger.debug("Skipping non-text file in ZIP: %s", name)
                        continue

            return files

        except zipfile.BadZipFile:
            logger.warning("Garena SkillHub returned invalid ZIP for %s v%s", slug, version)
            return files
        except httpx.HTTPError as exc:
            logger.debug("Garena SkillHub ZIP download failed for %s v%s: %s", slug, version, exc)
            return files
'''

FETCH_TEXT_METHOD = '''    def _fetch_text(self, url: str) -> Optional[str]:
        try:
            resp = httpx.get(
                url,
                headers=_garena_skillhub_auth_headers(),
                timeout=20,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.text
        except httpx.HTTPError:
            return None
        return None
'''

CREATE_ROUTER = '''def create_source_router(auth: Optional[GitHubAuth] = None) -> List[SkillSource]:
    """
    Create company-approved source adapters for search/fetch operations.

    Official optional skills, external public skill hubs, and direct URL/GitHub
    installs are intentionally disabled. The "clawhub" source id is backed by
    Garena SkillHub.
    """
    sources: List[SkillSource] = [
        ClawHubSource(),
    ]

    return sources
'''


def replace_regex(text: str, pattern: str, replacement: str, label: str) -> str:
    new_text, count = re.subn(pattern, replacement, text, count=1, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Could not patch {label}; Hermes source may have changed.")
    return new_text


def patch_text(text: str) -> str:
    if HELPER_MARKER in text:
        raise RuntimeError("Garena SkillHub patch marker already exists; source appears patched.")

    text = text.replace(
        "INDEX_CACHE_TTL = 3600  # 1 hour\n",
        "INDEX_CACHE_TTL = 3600  # 1 hour\n" + HELPERS,
        1,
    )
    text = replace_regex(
        text,
        r'class ClawHubSource\(SkillSource\):\n    """\n    Fetch skills from ClawHub \(clawhub\.ai\).*?\n\n    BASE_URL = "https://clawhub\.ai/api/v1"\n',
        CLASS_HEADER,
        "ClawHubSource header",
    )

    class_start = text.find("class ClawHubSource(SkillSource):")
    class_end_marker = "\n\n\n# ---------------------------------------------------------------------------\n# Claude Code marketplace source adapter"
    class_end = text.find(class_end_marker, class_start)
    if class_start == -1 or class_end == -1:
        raise RuntimeError("Could not isolate ClawHubSource class section.")

    section = text[class_start:class_end]
    section = replace_regex(
        section,
        r"    def search\(self, query: str, limit: int = 10\) -> List\[SkillMeta\]:\n.*?(?=\n    def fetch\(self, identifier: str\) -> Optional\[SkillBundle\]:)",
        SEARCH_METHOD.rstrip(),
        "ClawHubSource.search",
    )
    section = replace_regex(
        section,
        r"    def fetch\(self, identifier: str\) -> Optional\[SkillBundle\]:\n.*?(?=\n    def inspect\(self, identifier: str\) -> Optional\[SkillMeta\]:)",
        FETCH_METHOD.rstrip(),
        "ClawHubSource.fetch",
    )
    section = replace_regex(
        section,
        r"    def inspect\(self, identifier: str\) -> Optional\[SkillMeta\]:\n.*?(?=\n    def _search_catalog\(self, query: str, limit: int = 10\) -> List\[SkillMeta\]:)",
        INSPECT_METHOD.rstrip(),
        "ClawHubSource.inspect",
    )
    section = replace_regex(
        section,
        r"    def _get_json\(self, url: str, timeout: int = 20\) -> Optional\[Any\]:\n.*?(?=\n    def _resolve_latest_version\(self, slug: str, skill_data: Dict\[str, Any\]\) -> Optional\[str\]:)",
        GET_JSON_METHOD.rstrip(),
        "ClawHubSource._get_json",
    )
    section = replace_regex(
        section,
        r"    def _download_zip\(self, slug: str, version: str\) -> Dict\[str, str\]:\n.*?(?=\n    def _fetch_text\(self, url: str\) -> Optional\[str\]:)",
        DOWNLOAD_ZIP_METHOD.rstrip(),
        "ClawHubSource._download_zip",
    )
    section = replace_regex(
        section,
        r"    def _fetch_text\(self, url: str\) -> Optional\[str\]:\n.*?$",
        FETCH_TEXT_METHOD.rstrip(),
        "ClawHubSource._fetch_text",
    )
    text = text[:class_start] + section + text[class_end:]
    text = replace_regex(
        text,
        r"def create_source_router\(auth: Optional\[GitHubAuth\] = None\) -> List\[SkillSource\]:\n.*?(?=\n\n\ndef _search_one_source)",
        CREATE_ROUTER.rstrip(),
        "create_source_router",
    )
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-root", required=True, help="Hermes checkout/install root containing tools/skills_hub.py")
    parser.add_argument("--check", action="store_true", help="Validate patch applicability without writing")
    parser.add_argument("--no-backup", action="store_true", help="Do not create tools/skills_hub.py.bak")
    parser.add_argument("--restore", action="store_true", help="Restore tools/skills_hub.py from backup (.bak)")
    args = parser.parse_args()

    root = Path(args.hermes_root).expanduser().resolve()
    target = root / "tools" / "skills_hub.py"

    if args.restore:
        backup = target.with_suffix(target.suffix + ".bak")
        if not backup.exists():
            print(f"No backup found at {backup}", file=sys.stderr)
            return 1
        shutil.copy2(backup, target)
        print(f"Restored {target} from {backup}")
        return 0

    if not target.exists():
        print(f"tools/skills_hub.py not found under {root}", file=sys.stderr)
        return 2

    original = target.read_text(encoding="utf-8")

    if HELPER_MARKER in original:
        if args.check:
            print(f"{target} is already patched")
            return 0
        backup = target.with_suffix(target.suffix + ".bak")
        if not backup.exists():
            print(
                f"{target} is already patched and no backup (.bak) exists.\n"
                f"Restore the original manually, then re-run the installer.",
                file=sys.stderr,
            )
            return 1
        print(f"{target} is already patched; restoring from backup and re-applying...")
        shutil.copy2(backup, target)
        original = target.read_text(encoding="utf-8")

    try:
        patched = patch_text(original)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.check:
        print(f"Patch can be applied to {target}")
        return 0

    if not args.no_backup:
        backup = target.with_suffix(target.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(target, backup)
    target.write_text(patched, encoding="utf-8")
    print(f"Patched {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
