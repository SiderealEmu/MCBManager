"""Data models for Minecraft Bedrock addons."""

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import ClassVar, List, Optional, Set


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
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            header = manifest.get("header", {})
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
            )
        except (json.JSONDecodeError, IOError, KeyError):
            return None

    @staticmethod
    def detect_pack_type_from_manifest(manifest_path: Path) -> PackType:
        """Detect pack type from manifest.json content."""
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

            modules = manifest.get("modules", [])
            for module in modules:
                module_type = module.get("type", "").lower()
                if module_type in ("data", "script", "client_data"):
                    return PackType.BEHAVIOR
                elif module_type == "resources":
                    return PackType.RESOURCE

            return PackType.UNKNOWN
        except (json.JSONDecodeError, IOError):
            return PackType.UNKNOWN

    def to_pack_entry(self) -> dict:
        """Convert to world pack JSON entry format."""
        return {"pack_id": self.uuid, "version": self.version}

    def __eq__(self, other):
        if not isinstance(other, Addon):
            return False
        return self.uuid == other.uuid and self.pack_type == other.pack_type

    def __hash__(self):
        return hash((self.uuid, self.pack_type))
