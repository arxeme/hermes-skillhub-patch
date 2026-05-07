#!/usr/bin/env python3
"""Apply the Garena SkillHub source patch to a Hermes checkout."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path


HELPER_MARKER = "# BEGIN Garena SkillHub patch"
CLAUDE_MARKETPLACE_MARKER = "\n\n\n# ---------------------------------------------------------------------------\n# Claude Code marketplace source adapter"

HELPERS = r'''
# BEGIN Garena SkillHub patch
DEFAULT_GARENA_SKILLHUB_URL = "https://skillhub.ingarena.net"


def _garena_skillhub_root_url() -> str:
    raw = os.environ.get("SKILLHUB_URL") or DEFAULT_GARENA_SKILLHUB_URL
    base = raw.strip().rstrip("/") or DEFAULT_GARENA_SKILLHUB_URL
    if base.endswith("/api/v1"):
        return base[: -len("/api/v1")]
    return base


def _garena_skillhub_api_base_url() -> str:
    return f"{_garena_skillhub_root_url()}/api/v1"


def _garena_skillhub_auth_headers() -> Dict[str, str]:
    token = (os.environ.get("SKILLHUB_TOKEN") or "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}
# END Garena SkillHub patch
'''

GARENA_SOURCE = r'''

class GarenaSkillHubSource(SkillSource):
    """
    Fetch skills from Garena SkillHub using ClawHub's public v1 API contract.

    Hermes exposes this source as "garena-skillhub" while all traffic goes to
    the configured Garena SkillHub endpoint.
    """

    BASE_URL = _garena_skillhub_api_base_url()

    def source_id(self) -> str:
        return "garena-skillhub"

    def trust_level_for(self, identifier: str) -> str:
        return "community"

    def search(self, query: str, limit: int = 10) -> List[SkillMeta]:
        query = query.strip()
        if not query:
            return self._list_skills(limit=limit)

        results = self._search_api(query, limit=limit)
        exact = self.inspect(query)
        if exact:
            results = [exact] + results
        return self._dedupe_results(results)[:limit]

    def inspect(self, identifier: str) -> Optional[SkillMeta]:
        slug = self._identifier_to_slug(identifier)
        data = self._skill_detail(slug)
        skill = data.get("skill") if isinstance(data, dict) else None
        if not isinstance(skill, dict):
            return None
        return self._skill_to_meta(skill, data.get("latestVersion"))

    def fetch(self, identifier: str) -> Optional[SkillBundle]:
        slug = self._identifier_to_slug(identifier)
        data = self._skill_detail(slug)
        if not isinstance(data, dict):
            return None

        skill = data.get("skill")
        if not isinstance(skill, dict):
            return None

        latest_version = self._resolve_latest_version(data)
        if not latest_version:
            logger.warning("Garena SkillHub fetch failed for %s: could not resolve latest version", slug)
            return None

        files = self._download_zip(slug, latest_version)

        if "SKILL.md" not in files:
            version_files = self._fetch_version_files(slug, latest_version)
            if version_files:
                files = version_files

        if "SKILL.md" not in files:
            logger.warning(
                "Garena SkillHub fetch for %s resolved version %s but could not retrieve SKILL.md",
                slug,
                latest_version,
            )
            return None

        return SkillBundle(
            name=slug,
            files=files,
            source=self.source_id(),
            identifier=slug,
            trust_level="community",
            metadata={
                "displayName": skill.get("displayName"),
                "registry": _garena_skillhub_root_url(),
            },
        )

    @staticmethod
    def _identifier_to_slug(identifier: str) -> str:
        return identifier.strip().split("/")[-1]

    @staticmethod
    def _normalize_tags(tags: Any) -> List[str]:
        if isinstance(tags, list):
            return [str(t) for t in tags]
        if isinstance(tags, dict):
            return [str(k) for k in tags if str(k) != "latest"]
        return []

    @staticmethod
    def _latest_version_value(latest_version: Any) -> Optional[str]:
        if isinstance(latest_version, dict):
            version = latest_version.get("version")
            return version if isinstance(version, str) and version else None
        return latest_version if isinstance(latest_version, str) and latest_version else None

    @classmethod
    def _skill_to_meta(cls, skill: Dict[str, Any], latest_version: Any = None) -> SkillMeta:
        slug = skill.get("slug")
        if not isinstance(slug, str) or not slug:
            slug = skill.get("name") if isinstance(skill.get("name"), str) else "unknown"
        display_name = skill.get("displayName") or skill.get("name") or slug
        summary = skill.get("summary") or skill.get("description") or ""
        extra: Dict[str, Any] = {"displayName": display_name}
        version = cls._latest_version_value(latest_version)
        if version:
            extra["version"] = version

        # Hermes short-name install exact-matches SkillMeta.name. ClawHub CLI
        # installs by slug, so expose the slug as the Hermes installable name.
        return SkillMeta(
            name=slug,
            description=summary,
            source="garena-skillhub",
            identifier=slug,
            trust_level="community",
            tags=cls._normalize_tags(skill.get("tags", [])),
            extra=extra,
        )

    @staticmethod
    def _dedupe_results(results: List[SkillMeta]) -> List[SkillMeta]:
        seen: set[str] = set()
        deduped: List[SkillMeta] = []
        for result in results:
            key = (result.identifier or result.name).lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(result)
        return deduped

    def _get_json(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 20,
    ) -> Optional[Any]:
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/{path.lstrip('/')}",
                params=params or {},
                headers=_garena_skillhub_auth_headers(),
                timeout=timeout,
                follow_redirects=True,
            )
            if resp.status_code != 200:
                logger.debug("Garena SkillHub GET %s returned %s", path, resp.status_code)
                return None
            return resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.debug("Garena SkillHub GET %s failed: %s", path, exc)
            return None

    def _search_api(self, query: str, limit: int) -> List[SkillMeta]:
        data = self._get_json("search", params={"q": query, "limit": max(limit, 1)}, timeout=20)
        results = data.get("results", []) if isinstance(data, dict) else []
        if not isinstance(results, list):
            return []

        metas: List[SkillMeta] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug")
            if not isinstance(slug, str) or not slug:
                continue
            metas.append(self._skill_to_meta(
                {
                    "slug": slug,
                    "displayName": item.get("displayName"),
                    "summary": item.get("summary"),
                    "tags": item.get("tags", []),
                },
                item.get("version"),
            ))
        return metas

    def _list_skills(self, limit: int = 10) -> List[SkillMeta]:
        data = self._get_json(
            "skills",
            params={"limit": max(limit, 1), "sort": "updated"},
            timeout=20,
        )
        items = data.get("items", []) if isinstance(data, dict) else []
        if not isinstance(items, list):
            return []

        metas: List[SkillMeta] = []
        for item in items[:limit]:
            if isinstance(item, dict):
                metas.append(self._skill_to_meta(item, item.get("latestVersion")))
        return metas

    def _skill_detail(self, slug: str) -> Dict[str, Any]:
        data = self._get_json(f"skills/{slug}", timeout=20)
        return data if isinstance(data, dict) else {}

    def _resolve_latest_version(self, skill_data: Dict[str, Any]) -> Optional[str]:
        latest = self._latest_version_value(skill_data.get("latestVersion"))
        if latest:
            return latest
        skill = skill_data.get("skill")
        if isinstance(skill, dict):
            tags = skill.get("tags")
            if isinstance(tags, dict):
                latest_tag = tags.get("latest")
                if isinstance(latest_tag, str) and latest_tag:
                    return latest_tag
        return None

    def _download_zip(self, slug: str, version: str) -> Dict[str, str]:
        import io
        import zipfile

        files: Dict[str, str] = {}
        for attempt in range(3):
            try:
                resp = httpx.get(
                    f"{self.BASE_URL}/download",
                    params={"slug": slug, "version": version},
                    headers=_garena_skillhub_auth_headers(),
                    timeout=30,
                    follow_redirects=True,
                )
                if resp.status_code == 429:
                    retry_after = self._retry_after_seconds(resp)
                    logger.debug(
                        "Garena SkillHub download rate-limited for %s, retrying in %ds (attempt %d/3)",
                        slug,
                        retry_after,
                        attempt + 1,
                    )
                    time.sleep(retry_after)
                    continue
                if resp.status_code != 200:
                    logger.debug(
                        "Garena SkillHub ZIP download for %s v%s returned %s",
                        slug,
                        version,
                        resp.status_code,
                    )
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
                    return self._normalize_bundle_files(files)
            except zipfile.BadZipFile:
                logger.warning("Garena SkillHub returned invalid ZIP for %s v%s", slug, version)
                return files
            except httpx.HTTPError as exc:
                logger.debug("Garena SkillHub ZIP download failed for %s v%s: %s", slug, version, exc)
                return files
        return files

    @staticmethod
    def _retry_after_seconds(resp: httpx.Response) -> int:
        try:
            return min(max(int(resp.headers.get("retry-after", "5")), 0), 15)
        except (TypeError, ValueError):
            return 5

    @staticmethod
    def _normalize_bundle_files(files: Dict[str, str]) -> Dict[str, str]:
        if "SKILL.md" in files:
            return files
        prefixes = {
            path.split("/", 1)[0]
            for path in files
            if "/" in path and path.split("/", 1)[0]
        }
        if len(prefixes) != 1:
            return files
        prefix = next(iter(prefixes)) + "/"
        normalized = {
            path[len(prefix):]: content
            for path, content in files.items()
            if path.startswith(prefix) and path[len(prefix):]
        }
        return normalized if "SKILL.md" in normalized else files

    def _fetch_version_files(self, slug: str, version: str) -> Dict[str, str]:
        data = self._get_json(f"skills/{slug}/versions/{version}", timeout=20)
        version_data = data.get("version") if isinstance(data, dict) else None
        file_list = version_data.get("files") if isinstance(version_data, dict) else None
        if not isinstance(file_list, list):
            return {}

        files: Dict[str, str] = {}
        for file_meta in file_list:
            if not isinstance(file_meta, dict):
                continue
            path = file_meta.get("path") or file_meta.get("name")
            if not isinstance(path, str) or not path:
                continue
            try:
                safe_path = _validate_bundle_rel_path(path)
            except ValueError:
                logger.debug("Skipping unsafe file path from version metadata: %s", path)
                continue
            size = file_meta.get("size")
            if isinstance(size, int) and size > 500_000:
                continue
            content = self._fetch_file_text(slug, safe_path, version)
            if content is not None:
                files[safe_path] = content
        return self._normalize_bundle_files(files)

    def _fetch_file_text(self, slug: str, path: str, version: str) -> Optional[str]:
        try:
            resp = httpx.get(
                f"{self.BASE_URL}/skills/{slug}/file",
                params={"path": path, "version": version},
                headers=_garena_skillhub_auth_headers(),
                timeout=20,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                return resp.text
            logger.debug(
                "Garena SkillHub file fetch for %s@%s %s returned %s",
                slug,
                version,
                path,
                resp.status_code,
            )
        except httpx.HTTPError as exc:
            logger.debug("Garena SkillHub file fetch for %s@%s %s failed: %s", slug, version, path, exc)
        return None
'''

CREATE_ROUTER = '''def create_source_router(auth: Optional[GitHubAuth] = None) -> List[SkillSource]:
    """
    Create company-approved source adapters for search/fetch operations.

    Other skill acquisition routes are intentionally disabled. The active
    source uses Garena SkillHub's ClawHub-compatible v1 API.
    """
    sources: List[SkillSource] = [
        GarenaSkillHubSource(),
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

    if "INDEX_CACHE_TTL = 3600  # 1 hour\n" not in text:
        raise RuntimeError("Could not find insertion point for SkillHub helpers.")
    text = text.replace(
        "INDEX_CACHE_TTL = 3600  # 1 hour\n",
        "INDEX_CACHE_TTL = 3600  # 1 hour\n" + HELPERS,
        1,
    )

    marker_pos = text.find(CLAUDE_MARKETPLACE_MARKER)
    if marker_pos == -1:
        raise RuntimeError("Could not find insertion point for GarenaSkillHubSource.")
    text = text[:marker_pos] + GARENA_SOURCE + text[marker_pos:]

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
