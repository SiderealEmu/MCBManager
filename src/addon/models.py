"""Data models for Minecraft Bedrock addons."""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import ClassVar, List, Optional, Set


def strip_json_comments(text: str) -> str:
    """Remove JavaScript-style comments from JSON text.

    Handles:
    - Single-line comments: // comment
    - Multi-line comments: /* comment */

    This is needed because some Minecraft addon manifests include comments
    even though they're not valid JSON.
    """
    # Remove multi-line comments /* ... */
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    # Remove single-line comments // ... (but not inside strings)
    # This is a simplified approach that works for most manifest files
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        # Find // that's not inside a string
        # Simple heuristic: if // appears and the quote count before it is even, it's a comment
        idx = line.find("//")
        if idx != -1:
            # Count quotes before the //
            before = line[:idx]
            # If we're not inside a string (even number of unescaped quotes), strip the comment
            quote_count = before.count('"') - before.count('\\"')
            if quote_count % 2 == 0:
                line = before
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def load_json_with_comments(file_path: Path) -> dict:
    """Load a JSON file that may contain JavaScript-style comments."""
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    cleaned = strip_json_comments(content)
    return json.loads(cleaned)


class PackType(Enum):
    """Type of addon pack."""

    BEHAVIOR = "behavior"
    RESOURCE = "resource"
    UNKNOWN = "unknown"


@dataclass
class Addon:
    """Represents a Minecraft Bedrock addon (behavior or resource pack)."""

    # Default pack UUIDs - populated from config at runtime (ClassVar excludes from dataclass fields)
    _default_pack_uuids: ClassVar[Optional[Set[str]]] = None

    uuid: str
    name: str
    description: str
    version: List[int]
    pack_type: PackType
    path: Path
    enabled: bool = False
    icon_path: Optional[Path] = None
    min_engine_version: List[int] = field(default_factory=lambda: [1, 0, 0])
    # Additional manifest fields
    author: str = ""
    url: str = ""
    license: str = ""
    dependencies: List[dict] = field(default_factory=list)
    subpacks: List[dict] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    format_version: str = ""

    @property
    def version_string(self) -> str:
        """Get version as a string (e.g., '1.0.0')."""
        return ".".join(str(v) for v in self.version)

    @property
    def min_engine_version_string(self) -> str:
        """Get minimum engine version as a string."""
        return ".".join(str(v) for v in self.min_engine_version)

    @classmethod
    def set_default_pack_uuids(cls, uuids: Set[str]) -> None:
        """Set the default pack UUIDs from config."""
        cls._default_pack_uuids = uuids

    @classmethod
    def get_default_pack_uuids(cls) -> Set[str]:
        """Get the default pack UUIDs."""
        return cls._default_pack_uuids or set()

    @property
    def is_default(self) -> bool:
        """Check if this is a default Minecraft pack.

        Checks the UUID against the list of default pack UUIDs stored in config.
        This list is populated on first launch by asking the user if they have
        already installed any custom packs.
        """
        default_uuids = self.get_default_pack_uuids()
        return self.uuid in default_uuids

    @property
    def is_compatible(self) -> bool:
        """Check if this addon is compatible with the server version.

        Returns True if compatible or if server version cannot be determined.
        Returns False if addon's min_engine_version exceeds server version.
        """
        from ..server import get_server_version
        from ..config import config

        # Try to get live server version first
        server_version = get_server_version()

        # If server is offline, try to use cached version from config
        if server_version is None:
            cached_version = config.last_known_server_version
            if cached_version:
                try:
                    server_version = [int(p) for p in cached_version.split(".")[:3]]
                except (ValueError, AttributeError):
                    server_version = None

        if server_version is None:
            # Can't determine server version, assume compatible
            return True

        # Compare versions
        min_ver = self.min_engine_version + [0] * (3 - len(self.min_engine_version))
        srv_ver = server_version + [0] * (3 - len(server_version))

        for a, b in zip(min_ver, srv_ver):
            if a < b:
                return True
            if a > b:
                return False
        return True

    @staticmethod
    def _is_placeholder_name(name: str) -> bool:
        """Check if a name is a placeholder that should be replaced with folder name."""
        name_lower = name.lower().strip()

        # Check for placeholder/localization patterns like "pack.name", "pack.title"
        if name_lower.startswith("pack."):
            return True

        # Check for other common placeholder patterns
        if "%" in name or name.startswith("{{") or name.startswith("$"):
            return True

        # Check for generic/unknown names
        if name_lower in ("unknown pack", "unknown", ""):
            return True

        return False

    @classmethod
    def from_manifest(
        cls, manifest_path: Path, pack_type: PackType, enabled: bool = False
    ) -> Optional["Addon"]:
        """Create an Addon instance from a manifest.json file."""
        try:
            manifest = load_json_with_comments(manifest_path)

            header = manifest.get("header", {})
            metadata = manifest.get("metadata", {})
            pack_dir = manifest_path.parent

            uuid = header.get("uuid", "")
            name = header.get("name", "Unknown Pack")
            description = header.get("description", "")
            version = header.get("version", [1, 0, 0])
            min_engine_version = header.get("min_engine_version", [1, 0, 0])

            # Use folder name if manifest name is a placeholder
            if cls._is_placeholder_name(name):
                name = pack_dir.name

            # Ensure version is a list
            if isinstance(version, str):
                version = [int(v) for v in version.split(".")]

            # Check for pack icon
            icon_path = None
            for icon_name in ["pack_icon.png", "pack_icon.jpg"]:
                potential_icon = pack_dir / icon_name
                if potential_icon.exists():
                    icon_path = potential_icon
                    break

            # Extract additional manifest fields
            # Author: try header.author, then metadata.authors[0]
            author = header.get("author", "")
            if not author:
                authors = metadata.get("authors", [])
                if authors and isinstance(authors, list) and len(authors) > 0:
                    # Authors can be strings or dicts with "name" field
                    first_author = authors[0]
                    if isinstance(first_author, str):
                        author = first_author
                    elif isinstance(first_author, dict):
                        author = first_author.get("name", "")

            # URL: try header.url, then metadata.url
            url = header.get("url", "") or metadata.get("url", "")

            # License: try header.license, then metadata.license
            license_str = header.get("license", "") or metadata.get("license", "")

            # Dependencies, subpacks, capabilities from root
            dependencies = manifest.get("dependencies", [])
            subpacks = manifest.get("subpacks", [])
            capabilities = manifest.get("capabilities", [])

            # Format version from root
            format_version = manifest.get("format_version", "")
            if isinstance(format_version, (int, float)):
                format_version = str(format_version)

            return cls(
                uuid=uuid,
                name=name,
                description=description,
                version=version,
                pack_type=pack_type,
                path=pack_dir,
                enabled=enabled,
                icon_path=icon_path,
                min_engine_version=min_engine_version,
                author=author,
                url=url,
                license=license_str,
                dependencies=dependencies,
                subpacks=subpacks,
                capabilities=capabilities,
                format_version=format_version,
            )
        except (json.JSONDecodeError, IOError, KeyError):
            return None

    @staticmethod
    def detect_pack_type_from_manifest(manifest_path: Path) -> PackType:
        """Detect pack type from manifest.json content."""
        try:
            manifest = load_json_with_comments(manifest_path)

            modules = manifest.get("modules", [])
            for module in modules:
                module_type = module.get("type", "").lower()
                # Behavior pack module types
                if module_type in ("data", "script", "client_data", "javascript"):
                    return PackType.BEHAVIOR
                # Resource pack module types
                elif module_type in ("resources", "interface"):
                    return PackType.RESOURCE

            # Fallback: try to detect from folder name or path
            pack_dir = manifest_path.parent
            dir_name_lower = pack_dir.name.lower()

            # Check for common naming patterns
            if any(
                pattern in dir_name_lower
                for pattern in ("bp", "behavior", "behaviour", "_bp", "(bp)")
            ):
                return PackType.BEHAVIOR
            if any(
                pattern in dir_name_lower
                for pattern in ("rp", "resource", "_rp", "(rp)")
            ):
                return PackType.RESOURCE

            # Fallback: check for characteristic files/folders
            # Behavior packs typically have: functions/, scripts/, entities/, loot_tables/
            behavior_indicators = [
                "functions",
                "scripts",
                "entities",
                "loot_tables",
                "trading",
                "recipes",
            ]
            for indicator in behavior_indicators:
                if (pack_dir / indicator).exists():
                    return PackType.BEHAVIOR

            # Resource packs typically have: textures/, sounds/, models/, font/
            resource_indicators = ["textures", "sounds", "models", "font", "particles"]
            for indicator in resource_indicators:
                if (pack_dir / indicator).exists():
                    return PackType.RESOURCE

            return PackType.UNKNOWN
        except (json.JSONDecodeError, IOError):
            return PackType.UNKNOWN

    def get_missing_dependencies(self, installed_uuids: Set[str]) -> List[str]:
        """Get list of missing dependency UUIDs.

        Args:
            installed_uuids: Set of UUIDs of all installed addons.

        Returns:
            List of dependency UUIDs that are not installed.
            Excludes @minecraft/* script module dependencies.
        """
        missing = []
        for dep in self.dependencies:
            dep_uuid = dep.get("uuid", "")
            module_name = dep.get("module_name", "")

            # Skip @minecraft/* script module dependencies
            if module_name.startswith("@minecraft/") or dep_uuid.startswith("@minecraft/"):
                continue

            # Check if this dependency is installed
            if dep_uuid and dep_uuid not in installed_uuids:
                missing.append(dep_uuid)

        return missing

    def has_missing_dependencies(self, installed_uuids: Set[str]) -> bool:
        """Check if this addon has any missing dependencies.

        Args:
            installed_uuids: Set of UUIDs of all installed addons.

        Returns:
            True if any dependencies are missing, False otherwise.
        """
        return len(self.get_missing_dependencies(installed_uuids)) > 0

    def to_pack_entry(self) -> dict:
        """Convert to world pack JSON entry format."""
        return {"pack_id": self.uuid, "version": self.version}

    def __eq__(self, other):
        if not isinstance(other, Addon):
            return False
        return self.uuid == other.uuid and self.pack_type == other.pack_type

    def __hash__(self):
        return hash((self.uuid, self.pack_type))
