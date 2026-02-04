"""Addon management functionality."""

import json
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..config import config
from .models import Addon, PackType


class AddonManager:
    """Manages addon discovery, enabling, and disabling."""

    def __init__(self):
        self._behavior_packs: List[Addon] = []
        self._resource_packs: List[Addon] = []

    def refresh(self) -> None:
        """Refresh the list of installed addons."""
        self._behavior_packs = self._scan_packs(PackType.BEHAVIOR)
        self._resource_packs = self._scan_packs(PackType.RESOURCE)
        self._update_enabled_status()

    def _scan_packs(self, pack_type: PackType) -> List[Addon]:
        """Scan a pack directory for installed addons."""
        packs = []

        if pack_type == PackType.BEHAVIOR:
            pack_dir = config.get_behavior_packs_path()
        else:
            pack_dir = config.get_resource_packs_path()

        if not pack_dir or not pack_dir.exists():
            return packs

        for item in pack_dir.iterdir():
            if item.is_dir():
                manifest_path = item / "manifest.json"
                if manifest_path.exists():
                    addon = Addon.from_manifest(manifest_path, pack_type)
                    if addon:
                        packs.append(addon)

        return sorted(packs, key=lambda x: x.name.lower())

    def _update_enabled_status(self) -> None:
        """Update the enabled status of all packs based on world configuration."""
        enabled_behavior_uuids = self._get_enabled_pack_uuids(
            "world_behavior_packs.json"
        )
        enabled_resource_uuids = self._get_enabled_pack_uuids(
            "world_resource_packs.json"
        )

        for pack in self._behavior_packs:
            pack.enabled = pack.uuid in enabled_behavior_uuids

        for pack in self._resource_packs:
            pack.enabled = pack.uuid in enabled_resource_uuids

    def _get_enabled_pack_uuids(self, filename: str) -> Set[str]:
        """Get the set of enabled pack UUIDs from a world pack file."""
        uuids = set()
        worlds_path = config.get_worlds_path()

        if not worlds_path or not worlds_path.exists():
            return uuids

        # Check all worlds for enabled packs
        for world_dir in worlds_path.iterdir():
            if world_dir.is_dir():
                pack_file = world_dir / filename
                if pack_file.exists():
                    try:
                        with open(pack_file, "r", encoding="utf-8") as f:
                            packs = json.load(f)
                            for pack in packs:
                                uuid = pack.get("pack_id", "")
                                if uuid:
                                    uuids.add(uuid)
                    except (json.JSONDecodeError, IOError):
                        pass

        return uuids

    def get_worlds(self) -> List[str]:
        """Get list of available world names."""
        worlds = []
        worlds_path = config.get_worlds_path()

        if not worlds_path or not worlds_path.exists():
            return worlds

        for world_dir in worlds_path.iterdir():
            if world_dir.is_dir():
                worlds.append(world_dir.name)

        return sorted(worlds)

    def get_behavior_packs(self) -> List[Addon]:
        """Get all installed behavior packs."""
        return self._behavior_packs.copy()

    def get_resource_packs(self) -> List[Addon]:
        """Get all installed resource packs."""
        return self._resource_packs.copy()

    def enable_addon(self, addon: Addon, world_name: str) -> bool:
        """Enable an addon for a specific world."""
        if addon.pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        return self._add_pack_to_world(addon, world_name, filename)

    def disable_addon(self, addon: Addon, world_name: str) -> bool:
        """Disable an addon for a specific world."""
        if addon.pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        return self._remove_pack_from_world(addon, world_name, filename)

    def _add_pack_to_world(self, addon: Addon, world_name: str, filename: str) -> bool:
        """Add a pack entry to a world's pack file."""
        worlds_path = config.get_worlds_path()
        if not worlds_path:
            return False

        world_dir = worlds_path / world_name
        if not world_dir.exists():
            return False

        pack_file = world_dir / filename

        # Load existing packs or create empty list
        packs = []
        if pack_file.exists():
            try:
                with open(pack_file, "r", encoding="utf-8") as f:
                    packs = json.load(f)
            except (json.JSONDecodeError, IOError):
                packs = []

        # Check if already enabled
        for pack in packs:
            if pack.get("pack_id") == addon.uuid:
                return True  # Already enabled

        # Add the new pack
        packs.append(addon.to_pack_entry())

        # Save the file
        try:
            with open(pack_file, "w", encoding="utf-8") as f:
                json.dump(packs, f, indent=2)
            addon.enabled = True
            return True
        except IOError:
            return False

    def _remove_pack_from_world(
        self, addon: Addon, world_name: str, filename: str
    ) -> bool:
        """Remove a pack entry from a world's pack file."""
        worlds_path = config.get_worlds_path()
        if not worlds_path:
            return False

        world_dir = worlds_path / world_name
        if not world_dir.exists():
            return False

        pack_file = world_dir / filename

        if not pack_file.exists():
            return True  # No file means not enabled

        try:
            with open(pack_file, "r", encoding="utf-8") as f:
                packs = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        # Remove the pack
        packs = [p for p in packs if p.get("pack_id") != addon.uuid]

        # Save the file
        try:
            with open(pack_file, "w", encoding="utf-8") as f:
                json.dump(packs, f, indent=2)
            addon.enabled = False
            return True
        except IOError:
            return False

    def is_addon_enabled_in_world(self, addon: Addon, world_name: str) -> bool:
        """Check if an addon is enabled in a specific world."""
        if addon.pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        worlds_path = config.get_worlds_path()
        if not worlds_path:
            return False

        pack_file = worlds_path / world_name / filename
        if not pack_file.exists():
            return False

        try:
            with open(pack_file, "r", encoding="utf-8") as f:
                packs = json.load(f)
                for pack in packs:
                    if pack.get("pack_id") == addon.uuid:
                        return True
        except (json.JSONDecodeError, IOError):
            pass

        return False

    def get_addon_position(self, addon: Addon, world_name: str) -> Optional[int]:
        """Get the load order position of an addon in a world.

        Returns 0-indexed position (0 = highest priority), or None if not enabled.
        """
        if addon.pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        worlds_path = config.get_worlds_path()
        if not worlds_path:
            return None

        pack_file = worlds_path / world_name / filename
        if not pack_file.exists():
            return None

        try:
            with open(pack_file, "r", encoding="utf-8") as f:
                packs = json.load(f)
                for i, pack in enumerate(packs):
                    if pack.get("pack_id") == addon.uuid:
                        return i
        except (json.JSONDecodeError, IOError):
            pass

        return None

    def get_enabled_pack_count(self, world_name: str, pack_type: PackType) -> int:
        """Get the total count of enabled packs for a world."""
        if pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        worlds_path = config.get_worlds_path()
        if not worlds_path:
            return 0

        pack_file = worlds_path / world_name / filename
        if not pack_file.exists():
            return 0

        try:
            with open(pack_file, "r", encoding="utf-8") as f:
                packs = json.load(f)
                return len(packs)
        except (json.JSONDecodeError, IOError):
            return 0

    def move_addon_priority(self, addon: Addon, world_name: str, direction: int) -> bool:
        """Move an addon's priority position.

        Args:
            addon: The addon to move
            world_name: The world to modify
            direction: -1 to move up (higher priority), +1 to move down (lower priority)

        Returns:
            True if move was successful, False otherwise
        """
        if addon.pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        worlds_path = config.get_worlds_path()
        if not worlds_path:
            return False

        pack_file = worlds_path / world_name / filename
        if not pack_file.exists():
            return False

        try:
            with open(pack_file, "r", encoding="utf-8") as f:
                packs = json.load(f)
        except (json.JSONDecodeError, IOError):
            return False

        # Find current position
        current_index = None
        for i, pack in enumerate(packs):
            if pack.get("pack_id") == addon.uuid:
                current_index = i
                break

        if current_index is None:
            return False  # Pack not found

        new_index = current_index + direction

        # Bounds check
        if new_index < 0 or new_index >= len(packs):
            return False  # Can't move beyond bounds

        # Swap positions
        packs[current_index], packs[new_index] = packs[new_index], packs[current_index]

        # Save the file
        try:
            with open(pack_file, "w", encoding="utf-8") as f:
                json.dump(packs, f, indent=2)
            return True
        except IOError:
            return False

    def delete_addon(self, addon: Addon) -> bool:
        """Delete an addon from the server."""
        import shutil

        if not addon.path.exists():
            return False

        try:
            shutil.rmtree(addon.path)

            # Remove from internal lists
            if addon.pack_type == PackType.BEHAVIOR:
                self._behavior_packs = [
                    p for p in self._behavior_packs if p.uuid != addon.uuid
                ]
            else:
                self._resource_packs = [
                    p for p in self._resource_packs if p.uuid != addon.uuid
                ]

            return True
        except (IOError, OSError):
            return False
