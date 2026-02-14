"""Addon import functionality."""

import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..config import config
from ..server import get_server_version, server_fs
from .models import Addon, PackType, load_json_text_with_comments, load_json_with_comments

# Progress callback type: (current_step, total_steps, message, optional_step_progress)
ProgressCallback = Callable[[int, int, str, Optional[Dict[str, object]]], None]


@dataclass
class ImportResult:
    """Result of an import operation."""

    success: bool
    message: str
    imported_packs: List[Tuple[str, PackType]] = None
    warnings: List[str] = None
    details: List[str] = None

    def __post_init__(self):
        if self.imported_packs is None:
            self.imported_packs = []
        if self.warnings is None:
            self.warnings = []
        if self.details is None:
            self.details = []


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
        cls,
        file_path: Path,
        progress_callback: Optional[ProgressCallback] = None,
        install_to_development: bool = False,
    ) -> ImportResult:
        """Import an addon from a file.

        Args:
            file_path: Path to the addon file
            progress_callback: Optional callback for progress updates (step, total, message)
            install_to_development: Install into development_*_packs when True.
        """
        file_path = Path(file_path)

        details: List[str] = []
        emitted_transfer_lines = set()
        progress_total = 6
        progress_step = 0
        current_status_message = "Starting..."

        def add_detail(message: str) -> None:
            details.append(message)

        def update_progress(message: str, advance: bool = True) -> None:
            nonlocal progress_step, current_status_message
            if advance:
                progress_step += 1
            current_status_message = message
            add_detail(message)
            if progress_callback:
                progress_callback(progress_step, progress_total, message, None)

        def set_progress_total(total: int) -> None:
            nonlocal progress_total
            progress_total = max(total, progress_step + 1)

        def emit_step_progress(
            step_name: str, current: int, total: int, label: str
        ) -> None:
            if not progress_callback:
                return
            progress_callback(
                progress_step,
                progress_total,
                current_status_message,
                {
                    "step_name": step_name,
                    "current": int(current),
                    "total": int(total if total > 0 else 1),
                    "label": label,
                },
            )

        def emit_transfer_line(line: str) -> None:
            message = f"Transfer: {line}"
            if message in emitted_transfer_lines:
                return
            emitted_transfer_lines.add(message)
            update_progress(message, advance=False)

        update_progress("Preparing import...", advance=False)
        add_detail(f"Input file: {file_path.name}")
        add_detail(f"File extension: {file_path.suffix.lower()}")
        add_detail(
            "Install target: development directories"
            if install_to_development
            else "Install target: default pack directories"
        )
        update_progress("Validating file...")

        if not file_path.exists():
            add_detail("Validation failed: input file does not exist.")
            return ImportResult(False, f"File not found: {file_path}", details=details)

        if not cls.can_import(file_path):
            add_detail("Validation failed: unsupported file type.")
            return ImportResult(
                False,
                f"Unsupported file type: {file_path.suffix}. "
                f"Supported: {', '.join(cls.SUPPORTED_EXTENSIONS)}",
                details=details,
            )

        if not config.is_server_configured():
            add_detail("Validation failed: server is not configured.")
            return ImportResult(False, "Server path not configured", details=details)

        # Get the base name from the file for naming packs with generic names
        base_name = file_path.stem
        add_detail(f"Using base pack name: {base_name}")

        # Create temp directory for extraction
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            add_detail(f"Temporary extraction directory: {temp_path}")

            update_progress("Extracting archive...")

            # Extract or copy the file
            if cls._is_archive(file_path):
                try:
                    cls._extract_archive(file_path, temp_path)
                    add_detail("Archive extraction completed.")
                except Exception as e:
                    add_detail(f"Archive extraction failed: {e}")
                    return ImportResult(
                        False, f"Failed to extract archive: {e}", details=details
                    )
            else:
                add_detail("Validation failed: file is not a valid archive.")
                return ImportResult(False, "File is not a valid archive", details=details)

            update_progress("Processing nested packs...")

            # Check for any .mcpack files that need extraction
            # This handles .mcaddon files (which contain .mcpack files) as well as
            # .zip files that may contain .mcpack files
            mcpack_files = list(temp_path.rglob("*.mcpack"))
            add_detail(f"Nested .mcpack files found: {len(mcpack_files)}")
            if mcpack_files:
                set_progress_total(progress_total + len(mcpack_files))

                def nested_status(message: str) -> None:
                    set_progress_total(progress_total + 1)
                    update_progress(message)

                success, error_msg = cls._extract_nested_mcpacks(
                    temp_path, base_name, status_callback=nested_status
                )
                if not success:
                    add_detail(f"Nested extraction failed: {error_msg}")
                    return ImportResult(False, error_msg, details=details)
                add_detail("Nested .mcpack extraction completed.")

            update_progress("Scanning for packs...")

            # Find and process all packs in the extracted content
            packs_found = cls._find_packs(temp_path)
            add_detail(f"Pack folders detected: {len(packs_found)}")

            if not packs_found:
                add_detail("No valid packs were detected from extracted content.")
                return ImportResult(
                    False, "No valid addon packs found in the file", details=details
                )

            set_progress_total(progress_total + len(packs_found))
            update_progress(f"Installing {len(packs_found)} pack(s)...")

            # Import each pack
            imported = []
            errors = []
            compatibility_warnings = []

            for index, (pack_path, pack_type) in enumerate(packs_found, 1):
                update_progress(
                    f"Installing pack {index}/{len(packs_found)}: {pack_path.name} ({pack_type.value})"
                )
                success, result_msg, compat_warning, _transfer_log = cls._install_pack(
                    pack_path,
                    pack_type,
                    base_name,
                    install_to_development=install_to_development,
                    detail_callback=emit_transfer_line,
                    transfer_progress_callback=emit_step_progress,
                )
                for transfer_line in _transfer_log:
                    emit_transfer_line(transfer_line)
                if success:
                    # result_msg contains the actual folder name used
                    imported.append((result_msg, pack_type))
                    add_detail(
                        f"Installed {pack_type.value} pack as folder: {result_msg}"
                    )
                    if compat_warning:
                        compatibility_warnings.append(compat_warning)
                        add_detail(f"Compatibility warning: {compat_warning}")
                else:
                    errors.append(result_msg)
                    add_detail(
                        f"Failed to install {pack_type.value} pack ({pack_path.name}): {result_msg}"
                    )

            update_progress("Finalizing import...")

            if imported:
                # Build a clean, organized message
                behavior_packs = [name for name, ptype in imported if ptype == PackType.BEHAVIOR]
                resource_packs = [name for name, ptype in imported if ptype == PackType.RESOURCE]

                lines = [f"Successfully imported {len(imported)} pack(s):\n"]

                if behavior_packs:
                    lines.append("Behavior Packs:")
                    for name in behavior_packs:
                        lines.append(f"  • {name}")

                if resource_packs:
                    if behavior_packs:
                        lines.append("")  # Add spacing
                    lines.append("Resource Packs:")
                    for name in resource_packs:
                        lines.append(f"  • {name}")

                if errors:
                    lines.append(f"\nWarnings: {'; '.join(errors)}")

                message = "\n".join(lines)
                add_detail(
                    f"Import complete: {len(imported)} installed, {len(errors)} failed."
                )
                return ImportResult(
                    True,
                    message,
                    imported,
                    warnings=compatibility_warnings,
                    details=details,
                )
            else:
                add_detail("Import failed: no packs were installed.")
                return ImportResult(
                    False,
                    f"Failed to import: {'; '.join(errors)}",
                    details=details,
                )

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
    def _extract_nested_mcpacks(
        cls,
        extract_path: Path,
        base_name: str,
        max_depth: int = 3,
        status_callback: Optional[Callable[[str], None]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """Extract nested .mcpack files found in .mcaddon archives.

        .mcaddon files are zip archives containing .mcpack files, which are also
        zip archives containing the actual pack contents. This method finds and
        extracts all .mcpack files recursively, handling cases where .mcpack files
        contain other .mcpack files.

        Args:
            extract_path: Path to search for .mcpack files
            base_name: Base name to use for generic pack names
            max_depth: Maximum extraction depth (default 3)

        Returns:
            Tuple of (success, error_message). If nesting is too deep, returns
            (False, error_message).
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

        current_depth = 0

        # Keep extracting until no more .mcpack files are found
        while True:
            # Find all .mcpack files in the extracted content
            mcpack_files = list(extract_path.rglob("*.mcpack"))

            if not mcpack_files:
                break

            # Check depth limit
            current_depth += 1
            if current_depth > max_depth:
                return (
                    False,
                    f"Addon has too many nested layers (>{max_depth}). "
                    f"This file may be corrupted or improperly packaged.",
                )

            for mcpack_file in mcpack_files:
                if status_callback:
                    status_callback(
                        f"Extracting nested .mcpack (depth {current_depth}): {mcpack_file.name}"
                    )
                if not cls._is_archive(mcpack_file):
                    # Not a valid archive, remove it to avoid confusion
                    try:
                        mcpack_file.unlink()
                    except Exception:
                        pass
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

                # Handle case where destination already exists
                if extract_dest.exists():
                    counter = 1
                    while extract_dest.exists():
                        extract_dest = mcpack_file.parent / f"{folder_name}_{counter}"
                        counter += 1

                extract_dest.mkdir(parents=True, exist_ok=True)

                # Extract the .mcpack
                try:
                    cls._extract_archive(mcpack_file, extract_dest)
                except Exception:
                    # If extraction fails, skip this pack
                    pass

                # Remove the .mcpack file after extraction
                try:
                    mcpack_file.unlink()
                except Exception:
                    pass

        return True, None

    @classmethod
    def _find_packs(cls, search_path: Path) -> List[Tuple[Path, PackType]]:
        """Find all valid packs in a directory.

        Recursively searches for manifest.json files and returns the containing
        directories as pack paths. Handles various archive structures including
        nested folders at any depth.
        """
        packs = []
        found_pack_paths = set()  # Avoid duplicates

        # Use rglob to find all manifest.json files at any depth
        for manifest in search_path.rglob("manifest.json"):
            pack_dir = manifest.parent

            # Skip if we've already found this pack
            if pack_dir in found_pack_paths:
                continue

            pack_type = Addon.detect_pack_type_from_manifest(manifest)
            if pack_type != PackType.UNKNOWN:
                packs.append((pack_dir, pack_type))
                found_pack_paths.add(pack_dir)

        return packs

    @classmethod
    def _install_pack(
        cls,
        pack_path: Path,
        pack_type: PackType,
        base_name: str = None,
        install_to_development: bool = False,
        detail_callback: Optional[Callable[[str], None]] = None,
        transfer_progress_callback: Optional[
            Callable[[str, int, int, str], None]
        ] = None,
    ) -> Tuple[bool, str, Optional[str], List[str]]:
        """Install a pack to the appropriate server directory.

        Returns:
            Tuple of (success, message, compatibility_warning, transfer_log).
            - success: Whether the pack was installed
            - message: Pack folder name on success, error message on failure
            - compatibility_warning: Warning if addon may not be compatible, None otherwise
            - transfer_log: Details about copy/compression/upload/extraction steps
        """
        if pack_type == PackType.BEHAVIOR:
            dest_base = (
                "development_behavior_packs"
                if install_to_development
                else "behavior_packs"
            )
        elif pack_type == PackType.RESOURCE:
            dest_base = (
                "development_resource_packs"
                if install_to_development
                else "resource_packs"
            )
        else:
            return False, "Unknown pack type", None, []

        if not server_fs.is_configured():
            return False, "Server pack directory not configured", None, []

        # Ensure destination directory exists
        try:
            server_fs.mkdirs(dest_base)
        except Exception:
            return False, "Failed to create destination pack directory", None, []

        # Check version compatibility from manifest
        compatibility_warning = None
        manifest_path = pack_path / "manifest.json"
        if manifest_path.exists():
            try:
                manifest = load_json_with_comments(manifest_path)
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
        dest_path = server_fs.join(dest_base, pack_name)

        # Handle existing pack
        if server_fs.exists(dest_path):
            # Check if it's the same pack (by UUID)
            existing_manifest = server_fs.join(dest_path, "manifest.json")
            new_manifest = pack_path / "manifest.json"

            if server_fs.exists(existing_manifest) and new_manifest.exists():
                try:
                    existing_uuid = (
                        load_json_text_with_comments(server_fs.read_text(existing_manifest))
                        .get("header", {})
                        .get("uuid", "")
                    )
                    new_uuid = (
                        load_json_with_comments(new_manifest)
                        .get("header", {})
                        .get("uuid", "")
                    )

                    if existing_uuid == new_uuid:
                        # Same pack, update it
                        if not server_fs.delete_tree(dest_path):
                            return False, "Failed to replace existing pack", None, []
                    else:
                        # Different pack, use unique name
                        counter = 1
                        while server_fs.exists(dest_path):
                            dest_path = server_fs.join(dest_base, f"{pack_name}_{counter}")
                            counter += 1
                except Exception:
                    pass

        # Copy the pack
        try:
            threshold = server_fs.SFTP_ARCHIVE_FILE_THRESHOLD
            pack_file_count = cls._count_pack_files(pack_path, stop_after=threshold)
            if detail_callback:
                if server_fs.is_sftp_mode():
                    mode = (
                        "archive upload"
                        if pack_file_count > threshold
                        else "direct SFTP upload"
                    )
                    if pack_file_count > threshold:
                        count_display = f">{threshold}"
                    else:
                        count_display = str(pack_file_count)
                    detail_callback(
                        f"Precheck: pack has {count_display} files (threshold {threshold}) -> {mode}"
                    )
                else:
                    detail_callback(
                        f"Precheck: pack has {pack_file_count} files; local transfer mode (no SFTP compression)."
                    )

            transfer_log = server_fs.copy_dir_from_local(
                pack_path,
                dest_path,
                event_callback=detail_callback,
                progress_callback=transfer_progress_callback,
            )
            # Return the actual folder name used (for display purposes)
            return True, dest_path.split("/")[-1], compatibility_warning, transfer_log
        except Exception as e:
            return False, f"Failed to copy pack: {e}", None, []

    @staticmethod
    def _count_pack_files(pack_path: Path, stop_after: Optional[int] = None) -> int:
        """Count files recursively in a pack directory.

        If `stop_after` is set, counting stops once the count exceeds it.
        """
        count = 0
        for _root, _dirs, files in os.walk(pack_path):
            count += len(files)
            if stop_after is not None and count > stop_after:
                return count
        return count

    @staticmethod
    def _get_pack_name(pack_path: Path) -> str:
        """Get the display name of a pack from its manifest."""
        manifest = pack_path / "manifest.json"
        if manifest.exists():
            try:
                data = load_json_with_comments(manifest)
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
        cls,
        folder_path: Path,
        progress_callback: Optional[ProgressCallback] = None,
        install_to_development: bool = False,
    ) -> ImportResult:
        """Import addons from a folder.

        This method handles two cases:
        1. A folder that IS a pack (contains manifest.json)
        2. A folder that CONTAINS addon files (.mcaddon, .mcpack, .zip) or pack subfolders

        Args:
            folder_path: Path to the addon folder
            progress_callback: Optional callback for progress updates (step, total, message)
            install_to_development: Install into development_*_packs when True.
        """
        folder_path = Path(folder_path)

        details: List[str] = []
        emitted_transfer_lines = set()
        progress_total = 5
        progress_step = 0
        current_status_message = "Starting..."

        def add_detail(message: str) -> None:
            details.append(message)

        def update_progress(message: str, advance: bool = True) -> None:
            nonlocal progress_step, current_status_message
            if advance:
                progress_step += 1
            current_status_message = message
            add_detail(message)
            if progress_callback:
                progress_callback(progress_step, progress_total, message, None)

        def set_progress_total(total: int) -> None:
            nonlocal progress_total
            progress_total = max(total, progress_step + 1)

        def emit_step_progress(
            step_name: str, current: int, total: int, label: str
        ) -> None:
            if not progress_callback:
                return
            progress_callback(
                progress_step,
                progress_total,
                current_status_message,
                {
                    "step_name": step_name,
                    "current": int(current),
                    "total": int(total if total > 0 else 1),
                    "label": label,
                },
            )

        def emit_transfer_line(line: str) -> None:
            message = f"Transfer: {line}"
            if message in emitted_transfer_lines:
                return
            emitted_transfer_lines.add(message)
            update_progress(message, advance=False)

        update_progress("Preparing folder import...", advance=False)
        add_detail(f"Input folder: {folder_path}")
        add_detail(
            "Install target: development directories"
            if install_to_development
            else "Install target: default pack directories"
        )
        update_progress("Validating folder...")

        if not folder_path.exists() or not folder_path.is_dir():
            add_detail("Validation failed: folder path is invalid.")
            return ImportResult(False, "Invalid folder path", details=details)

        if not config.is_server_configured():
            add_detail("Validation failed: server is not configured.")
            return ImportResult(False, "Server path not configured", details=details)

        update_progress("Scanning for addon files and packs...")

        # First, check if this folder itself is a pack (has manifest.json)
        packs_found = cls._find_packs(folder_path)
        add_detail(f"Pack folders detected directly: {len(packs_found)}")

        # Also look for addon files (.mcaddon, .mcpack, .zip) in the folder
        addon_files = []
        for ext in cls.SUPPORTED_EXTENSIONS:
            addon_files.extend(folder_path.glob(f"*{ext}"))
        add_detail(f"Addon archives detected: {len(addon_files)}")
        base_steps = 3 + (1 if addon_files else 0) + (1 if packs_found else 0)
        set_progress_total(base_steps + len(addon_files) + len(packs_found))

        # If no packs found directly and no addon files, nothing to import
        if not packs_found and not addon_files:
            add_detail("No supported files or pack folders were found.")
            return ImportResult(
                False,
                "No valid addon packs or addon files found in the folder",
                details=details,
            )

        imported = []
        errors = []
        compatibility_warnings = []

        # Import any addon files found
        if addon_files:
            update_progress(f"Processing {len(addon_files)} addon archive(s)...")
            for index, addon_file in enumerate(addon_files, 1):
                update_progress(
                    f"Importing archive {index}/{len(addon_files)}: {addon_file.name}"
                )
                # Import each addon file (this handles .mcaddon, .mcpack, .zip)
                result = cls.import_addon(
                    addon_file,
                    progress_callback=lambda _step, _total, message, _step_info, name=addon_file.name: update_progress(
                        f"{name}: {message}", advance=False
                    ),
                    install_to_development=install_to_development,
                )
                details.append(f"Archive report for {addon_file.name}:")
                details.extend([f"  {line}" for line in result.details])
                if result.success:
                    imported.extend(result.imported_packs)
                    if result.warnings:
                        compatibility_warnings.extend(result.warnings)
                    add_detail(
                        f"Archive import succeeded: {addon_file.name} ({len(result.imported_packs)} pack(s))."
                    )
                else:
                    errors.append(f"{addon_file.name}: {result.message}")
                    add_detail(f"Archive import failed: {addon_file.name} ({result.message}).")

        # Import any pack folders found directly
        if packs_found:
            base_name = folder_path.name
            update_progress(f"Installing {len(packs_found)} pack folder(s)...")

            for index, (pack_path, pack_type) in enumerate(packs_found, 1):
                update_progress(
                    f"Installing folder pack {index}/{len(packs_found)}: {pack_path.name} ({pack_type.value})"
                )
                success, result_msg, compat_warning, _transfer_log = cls._install_pack(
                    pack_path,
                    pack_type,
                    base_name,
                    install_to_development=install_to_development,
                    detail_callback=emit_transfer_line,
                    transfer_progress_callback=emit_step_progress,
                )
                for transfer_line in _transfer_log:
                    emit_transfer_line(transfer_line)
                if success:
                    imported.append((result_msg, pack_type))
                    add_detail(
                        f"Installed folder pack {pack_path.name} as {result_msg} ({pack_type.value})."
                    )
                    if compat_warning:
                        compatibility_warnings.append(compat_warning)
                        add_detail(f"Compatibility warning: {compat_warning}")
                else:
                    errors.append(result_msg)
                    add_detail(f"Failed to install folder pack {pack_path.name}: {result_msg}")

        update_progress("Finalizing folder import...")

        if imported:
            # Build a clean, organized message
            behavior_packs = [name for name, ptype in imported if ptype == PackType.BEHAVIOR]
            resource_packs = [name for name, ptype in imported if ptype == PackType.RESOURCE]

            lines = [f"Successfully imported {len(imported)} pack(s):\n"]

            if behavior_packs:
                lines.append("Behavior Packs:")
                for name in behavior_packs:
                    lines.append(f"  • {name}")

            if resource_packs:
                if behavior_packs:
                    lines.append("")  # Add spacing
                lines.append("Resource Packs:")
                for name in resource_packs:
                    lines.append(f"  • {name}")

            if errors:
                lines.append(f"\nWarnings: {'; '.join(errors)}")

            message = "\n".join(lines)
            add_detail(
                f"Folder import complete: {len(imported)} installed, {len(errors)} failed."
            )
            return ImportResult(
                True,
                message,
                imported,
                warnings=compatibility_warnings,
                details=details,
            )
        else:
            add_detail("Folder import failed: no packs were installed.")
            return ImportResult(
                False, f"Failed to import: {'; '.join(errors)}", details=details
            )
