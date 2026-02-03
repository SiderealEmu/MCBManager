"""Addon import functionality."""

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from ..config import config
from ..server import get_server_version
from .models import Addon, PackType

# Progress callback type: (current_step, total_steps, message)
ProgressCallback = Callable[[int, int, str], None]


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    message: str
    imported_packs: List[Tuple[str, PackType]] = None
    warnings: List[str] = None

    def __post_init__(self):
        if self.imported_packs is None:
            self.imported_packs = []
        if self.warnings is None:
            self.warnings = []


class AddonImporter:
    """Handles importing addons from various file formats."""

    SUPPORTED_EXTENSIONS = {".mcaddon", ".mcpack", ".zip"}

    @staticmethod
    def compare_versions(version1: List[int], version2: List[int]) -> int:
        """Compare two version lists.

        Args:
            version1: First version as [major, minor, patch]
            version2: Second version as [major, minor, patch]

        Returns:
            -1 if version1 < version2
             0 if version1 == version2
             1 if version1 > version2
        """
        # Pad versions to same length
        v1 = version1 + [0] * (3 - len(version1))
        v2 = version2 + [0] * (3 - len(version2))

        for a, b in zip(v1, v2):
            if a < b:
                return -1
            if a > b:
                return 1
        return 0

    @classmethod
    def check_version_compatibility(
        cls, min_engine_version: List[int]
    ) -> Tuple[bool, Optional[str]]:
        """Check if an addon's minimum engine version is compatible with the server.

        Args:
            min_engine_version: The addon's minimum engine version requirement.

        Returns:
            Tuple of (is_compatible, warning_message).
            If compatible, warning_message is None.
            If server version cannot be determined, returns (True, None) to allow import.
        """
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
            # Can't determine server version, allow import without warning
            return True, None

        if cls.compare_versions(min_engine_version, server_version) > 0:
            min_ver_str = ".".join(str(v) for v in min_engine_version)
            server_ver_str = ".".join(str(v) for v in server_version)
            warning = (
                f"Addon requires Minecraft {min_ver_str} but server is {server_ver_str}. "
                f"The addon may not work correctly."
            )
            return False, warning

        return True, None

    @classmethod
    def can_import(cls, file_path: Path) -> bool:
        """Check if a file can be imported."""
        return file_path.suffix.lower() in cls.SUPPORTED_EXTENSIONS

    @classmethod
    def import_addon(
        cls, file_path: Path, progress_callback: Optional[ProgressCallback] = None
    ) -> ImportResult:
        """Import an addon from a file.

        Args:
            file_path: Path to the addon file
            progress_callback: Optional callback for progress updates (step, total, message)
        """
        file_path = Path(file_path)

        def report_progress(step: int, total: int, message: str) -> None:
            if progress_callback:
                progress_callback(step, total, message)

        report_progress(0, 5, "Validating file...")

        if not file_path.exists():
            return ImportResult(False, f"File not found: {file_path}")

        if not cls.can_import(file_path):
            return ImportResult(
                False,
                f"Unsupported file type: {file_path.suffix}. "
                f"Supported: {', '.join(cls.SUPPORTED_EXTENSIONS)}",
            )

        if not config.is_server_configured():
            return ImportResult(False, "Server path not configured")

        # Get the base name from the file for naming packs with generic names
        base_name = file_path.stem

        # Create temp directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            report_progress(1, 5, "Extracting archive...")

            # Extract or copy the file
            if cls._is_archive(file_path):
                try:
                    cls._extract_archive(file_path, temp_path)
                except Exception as e:
                    return ImportResult(False, f"Failed to extract archive: {e}")
            else:
                return ImportResult(False, "File is not a valid archive")

            # Handle .mcaddon files - they contain .mcpack files that need extraction
            if file_path.suffix.lower() == ".mcaddon":
                report_progress(2, 5, "Extracting nested packs...")
                cls._extract_nested_mcpacks(temp_path, base_name)

            report_progress(3, 5, "Scanning for packs...")

            # Find and process all packs in the extracted content
            packs_found = cls._find_packs(temp_path)

            if not packs_found:
                return ImportResult(False, "No valid addon packs found in the file")

            report_progress(4, 5, f"Installing {len(packs_found)} pack(s)...")

            # Import each pack
            imported = []
            errors = []
            compatibility_warnings = []

            for pack_path, pack_type in packs_found:
                success, result_msg, compat_warning = cls._install_pack(
                    pack_path, pack_type, base_name
                )
                if success:
                    # result_msg contains the actual folder name used
                    imported.append((result_msg, pack_type))
                    if compat_warning:
                        compatibility_warnings.append(compat_warning)
                else:
                    errors.append(result_msg)

            report_progress(5, 5, "Finalizing...")

            if imported:
                pack_names = [f"{name} ({ptype.value})" for name, ptype in imported]
                message = f"Successfully imported: {', '.join(pack_names)}"
                if errors:
                    message += f"\nWarnings: {'; '.join(errors)}"
                return ImportResult(
                    True, message, imported, warnings=compatibility_warnings
                )
            else:
                return ImportResult(False, f"Failed to import: {'; '.join(errors)}")

    @staticmethod
    def _is_archive(file_path: Path) -> bool:
        """Check if a file is a valid zip archive."""
        try:
            return zipfile.is_zipfile(file_path)
        except Exception:
            return False

    @staticmethod
    def _extract_archive(file_path: Path, dest_path: Path) -> None:
        """Extract a zip archive to a destination path."""
        with zipfile.ZipFile(file_path, "r") as zf:
            zf.extractall(dest_path)

    @classmethod
    def _extract_nested_mcpacks(cls, extract_path: Path, base_name: str) -> None:
        """Extract nested .mcpack files found in .mcaddon archives.

        .mcaddon files are zip archives containing .mcpack files, which are also
        zip archives containing the actual pack contents. This method finds and
        extracts all .mcpack files.
        """
        # Generic names that should be replaced with the addon name
        generic_names = {
            "resource",
            "resources",
            "resource_pack",
            "resource pack",
            "behavior",
            "behaviors",
            "behaviour",
            "behaviours",
            "behavior_pack",
            "behavior pack",
            "behaviour_pack",
            "behaviour pack",
            "bp",
            "rp",
            "pack",
        }

        # Find all .mcpack files in the extracted content
        mcpack_files = list(extract_path.rglob("*.mcpack"))

        for mcpack_file in mcpack_files:
            if not cls._is_archive(mcpack_file):
                continue

            # Determine the folder name for extraction
            pack_stem = mcpack_file.stem.lower()

            # Check if this is a generic name that should be renamed
            if pack_stem in generic_names:
                # Determine pack type suffix based on the generic name
                if any(x in pack_stem for x in ["resource", "rp"]):
                    folder_name = f"{base_name}_RP"
                elif any(x in pack_stem for x in ["behavior", "behaviour", "bp"]):
                    folder_name = f"{base_name}_BP"
                else:
                    folder_name = f"{base_name}_{mcpack_file.stem}"
            else:
                folder_name = mcpack_file.stem

            # Create extraction directory
            extract_dest = mcpack_file.parent / folder_name
            extract_dest.mkdir(parents=True, exist_ok=True)

            # Extract the .mcpack
            try:
                cls._extract_archive(mcpack_file, extract_dest)
            except Exception:
                # If extraction fails, skip this pack
                continue

            # Remove the .mcpack file after extraction
            try:
                mcpack_file.unlink()
            except Exception:
                pass

    @classmethod
    def _find_packs(cls, search_path: Path) -> List[Tuple[Path, PackType]]:
        """Find all valid packs in a directory."""
        packs = []

        # Check if search_path itself is a pack
        manifest = search_path / "manifest.json"
        if manifest.exists():
            pack_type = Addon.detect_pack_type_from_manifest(manifest)
            if pack_type != PackType.UNKNOWN:
                packs.append((search_path, pack_type))
                return packs

        # Search subdirectories
        for item in search_path.iterdir():
            if item.is_dir():
                manifest = item / "manifest.json"
                if manifest.exists():
                    pack_type = Addon.detect_pack_type_from_manifest(manifest)
                    if pack_type != PackType.UNKNOWN:
                        packs.append((item, pack_type))
                else:
                    # Recurse one more level (for .mcaddon files that contain nested folders)
                    for subitem in item.iterdir():
                        if subitem.is_dir():
                            sub_manifest = subitem / "manifest.json"
                            if sub_manifest.exists():
                                pack_type = Addon.detect_pack_type_from_manifest(
                                    sub_manifest
                                )
                                if pack_type != PackType.UNKNOWN:
                                    packs.append((subitem, pack_type))

        return packs

    @classmethod
    def _install_pack(
        cls, pack_path: Path, pack_type: PackType, base_name: str = None
    ) -> Tuple[bool, str, Optional[str]]:
        """Install a pack to the appropriate server directory.

        Returns:
            Tuple of (success, message, compatibility_warning).
            - success: Whether the pack was installed
            - message: Pack folder name on success, error message on failure
            - compatibility_warning: Warning if addon may not be compatible, None otherwise
        """
        if pack_type == PackType.BEHAVIOR:
            dest_base = config.get_behavior_packs_path()
        elif pack_type == PackType.RESOURCE:
            dest_base = config.get_resource_packs_path()
        else:
            return False, "Unknown pack type", None

        if not dest_base:
            return False, "Server pack directory not configured", None

        # Ensure destination directory exists
        dest_base.mkdir(parents=True, exist_ok=True)

        # Check version compatibility from manifest
        compatibility_warning = None
        manifest_path = pack_path / "manifest.json"
        if manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                    min_engine_version = manifest.get("header", {}).get(
                        "min_engine_version", [1, 0, 0]
                    )
                    pack_name_from_manifest = manifest.get("header", {}).get(
                        "name", pack_path.name
                    )
                    _, compatibility_warning = cls.check_version_compatibility(
                        min_engine_version
                    )
                    if compatibility_warning:
                        # Prepend pack name to warning
                        compatibility_warning = (
                            f"{pack_name_from_manifest}: {compatibility_warning}"
                        )
            except (json.JSONDecodeError, IOError):
                pass

        # Get pack name for folder, using base_name for generic names
        pack_name = cls._get_pack_folder_name(pack_path, pack_type, base_name)
        dest_path = dest_base / pack_name

        # Handle existing pack
        if dest_path.exists():
            # Check if it's the same pack (by UUID)
            existing_manifest = dest_path / "manifest.json"
            new_manifest = pack_path / "manifest.json"

            if existing_manifest.exists() and new_manifest.exists():
                try:
                    with open(existing_manifest, "r") as f:
                        existing_uuid = json.load(f).get("header", {}).get("uuid", "")
                    with open(new_manifest, "r") as f:
                        new_uuid = json.load(f).get("header", {}).get("uuid", "")

                    if existing_uuid == new_uuid:
                        # Same pack, update it
                        shutil.rmtree(dest_path)
                    else:
                        # Different pack, use unique name
                        counter = 1
                        while dest_path.exists():
                            dest_path = dest_base / f"{pack_name}_{counter}"
                            counter += 1
                except Exception:
                    pass

        # Copy the pack
        try:
            shutil.copytree(pack_path, dest_path)
            # Return the actual folder name used (for display purposes)
            return True, dest_path.name, compatibility_warning
        except Exception as e:
            return False, f"Failed to copy pack: {e}", None

    @staticmethod
    def _get_pack_name(pack_path: Path) -> str:
        """Get the display name of a pack from its manifest."""
        manifest = pack_path / "manifest.json"
        if manifest.exists():
            try:
                with open(manifest, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("header", {}).get("name", pack_path.name)
            except Exception:
                pass
        return pack_path.name

    @staticmethod
    def _is_generic_or_placeholder_name(name: str) -> bool:
        """Check if a pack name is generic or a placeholder that should be replaced."""
        name_lower = name.lower().strip()

        # Generic names that should be replaced
        generic_names = {
            "resource",
            "resources",
            "resource_pack",
            "resource pack",
            "behavior",
            "behaviors",
            "behaviour",
            "behaviours",
            "behavior_pack",
            "behavior pack",
            "behaviour_pack",
            "behaviour pack",
            "bp",
            "rp",
            "pack",
            "unnamed_pack",
        }

        # Check for exact generic name match
        if name_lower in generic_names:
            return True

        # Check for placeholder/localization patterns like "pack.name", "pack.title", etc.
        if name_lower.startswith("pack."):
            return True

        # Check for other common placeholder patterns
        if "%" in name or name.startswith("{{") or name.startswith("$"):
            return True

        return False

    @staticmethod
    def _get_pack_folder_name(
        pack_path: Path, pack_type: PackType = None, base_name: str = None
    ) -> str:
        """Generate a safe folder name for a pack.

        If the pack has a generic name and base_name is provided, use the base_name
        with an appropriate suffix based on pack type.
        """
        name = AddonImporter._get_pack_name(pack_path)

        # Check if this is a generic/placeholder name that should be replaced
        if base_name and AddonImporter._is_generic_or_placeholder_name(name):
            if pack_type == PackType.BEHAVIOR:
                name = f"{base_name}_BP"
            elif pack_type == PackType.RESOURCE:
                name = f"{base_name}_RP"
            else:
                name = base_name

        # Make it filesystem safe
        safe_name = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_" for c in name
        )
        safe_name = safe_name.strip().replace(" ", "_")
        return safe_name or "unnamed_pack"

    @classmethod
    def import_folder(
        cls, folder_path: Path, progress_callback: Optional[ProgressCallback] = None
    ) -> ImportResult:
        """Import addons from a folder.

        This method handles two cases:
        1. A folder that IS a pack (contains manifest.json)
        2. A folder that CONTAINS addon files (.mcaddon, .mcpack, .zip) or pack subfolders

        Args:
            folder_path: Path to the addon folder
            progress_callback: Optional callback for progress updates (step, total, message)
        """
        folder_path = Path(folder_path)

        def report_progress(step: int, total: int, message: str) -> None:
            if progress_callback:
                progress_callback(step, total, message)

        report_progress(0, 4, "Validating folder...")

        if not folder_path.exists() or not folder_path.is_dir():
            return ImportResult(False, "Invalid folder path")

        if not config.is_server_configured():
            return ImportResult(False, "Server path not configured")

        report_progress(1, 4, "Scanning for addon files and packs...")

        # First, check if this folder itself is a pack (has manifest.json)
        packs_found = cls._find_packs(folder_path)

        # Also look for addon files (.mcaddon, .mcpack, .zip) in the folder
        addon_files = []
        for ext in cls.SUPPORTED_EXTENSIONS:
            addon_files.extend(folder_path.glob(f"*{ext}"))

        # If no packs found directly and no addon files, nothing to import
        if not packs_found and not addon_files:
            return ImportResult(
                False, "No valid addon packs or addon files found in the folder"
            )

        imported = []
        errors = []
        compatibility_warnings = []

        # Import any addon files found
        if addon_files:
            total_steps = len(addon_files) + 2
            for i, addon_file in enumerate(addon_files):
                report_progress(2 + i, total_steps, f"Importing {addon_file.name}...")
                # Import each addon file (this handles .mcaddon, .mcpack, .zip)
                result = cls.import_addon(addon_file, progress_callback=None)
                if result.success:
                    imported.extend(result.imported_packs)
                    compatibility_warnings.extend(result.warnings)
                else:
                    errors.append(f"{addon_file.name}: {result.message}")

        # Import any pack folders found directly
        if packs_found:
            base_name = folder_path.name
            report_progress(3, 4, f"Installing {len(packs_found)} pack folder(s)...")

            for pack_path, pack_type in packs_found:
                success, result_msg, compat_warning = cls._install_pack(
                    pack_path, pack_type, base_name
                )
                if success:
                    imported.append((result_msg, pack_type))
                    if compat_warning:
                        compatibility_warnings.append(compat_warning)
                else:
                    errors.append(result_msg)

        report_progress(4, 4, "Finalizing...")

        if imported:
            pack_names = [f"{name} ({ptype.value})" for name, ptype in imported]
            message = f"Successfully imported: {', '.join(pack_names)}"
            if errors:
                message += f"\nWarnings: {'; '.join(errors)}"
            return ImportResult(
                True, message, imported, warnings=compatibility_warnings
            )
        else:
            return ImportResult(False, f"Failed to import: {'; '.join(errors)}")
