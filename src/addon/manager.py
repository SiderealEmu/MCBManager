"""Addon management functionality."""

import json
from typing import List, Optional, Set

from ..server import server_fs
from .models import Addon, PackType, load_json_text_with_comments


class AddonManager:
    """Manages addon discovery, enabling, and disabling."""

    def __init__(self):
        self._behavior_packs: List[Addon] = []
        self._resource_packs: List[Addon] = []
        self._development_behavior_packs: List[Addon] = []
        self._development_resource_packs: List[Addon] = []

    def refresh(self) -> None:
        """Refresh the list of installed addons."""
        self._behavior_packs = self._scan_packs(
            PackType.BEHAVIOR, "behavior_packs"
        )
        self._resource_packs = self._scan_packs(
            PackType.RESOURCE, "resource_packs"
        )
        self._development_behavior_packs = self._scan_packs(
            PackType.BEHAVIOR, "development_behavior_packs"
        )
        self._development_resource_packs = self._scan_packs(
            PackType.RESOURCE, "development_resource_packs"
        )
        self._disable_conflicting_duplicates_in_world_json()
        self._update_enabled_status()

    def _scan_packs(self, pack_type: PackType, pack_dir: str) -> List[Addon]:
        """Scan a pack directory for installed addons."""
        packs = []

        if not server_fs.exists(pack_dir) or not server_fs.is_dir(pack_dir):
            return packs

        for item in server_fs.list_dir(pack_dir):
            if not item.is_dir:
                continue

            manifest_path = server_fs.join(item.path, "manifest.json")
            if not server_fs.exists(manifest_path):
                continue

            try:
                manifest_data = load_json_text_with_comments(server_fs.read_text(manifest_path))
            except (json.JSONDecodeError, Exception):
                continue

            icon_path = None
            for icon_name in ["pack_icon.png", "pack_icon.jpg"]:
                candidate = server_fs.join(item.path, icon_name)
                if server_fs.exists(candidate):
                    icon_path = candidate
                    break

            addon = Addon.from_manifest_data(
                manifest=manifest_data,
                pack_type=pack_type,
                pack_path=item.path,
                icon_path=icon_path,
            )
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

        for pack in self._development_behavior_packs:
            pack.enabled = pack.uuid in enabled_behavior_uuids
        for pack in self._development_resource_packs:
            pack.enabled = pack.uuid in enabled_resource_uuids

    def _disable_conflicting_duplicates_in_world_json(self) -> None:
        """Disable duplicate UUID conflicts by removing them from world pack JSON files."""
        behavior_duplicates = self._get_duplicate_uuid_set(
            self._behavior_packs, self._development_behavior_packs
        )
        resource_duplicates = self._get_duplicate_uuid_set(
            self._resource_packs, self._development_resource_packs
        )

        if not behavior_duplicates and not resource_duplicates:
            return

        worlds_path = "worlds"
        if not server_fs.exists(worlds_path) or not server_fs.is_dir(worlds_path):
            return

        for world_dir in server_fs.list_dir(worlds_path):
            if not world_dir.is_dir:
                continue

            if behavior_duplicates:
                behavior_file = server_fs.join(
                    world_dir.path, "world_behavior_packs.json"
                )
                self._remove_pack_ids_from_world_file(
                    behavior_file, behavior_duplicates
                )

            if resource_duplicates:
                resource_file = server_fs.join(
                    world_dir.path, "world_resource_packs.json"
                )
                self._remove_pack_ids_from_world_file(
                    resource_file, resource_duplicates
                )

    @staticmethod
    def _get_duplicate_uuid_set(
        normal_packs: List[Addon], development_packs: List[Addon]
    ) -> Set[str]:
        """Get UUIDs present in both normal and development pack lists."""
        normal_uuids = {pack.uuid for pack in normal_packs if pack.uuid}
        development_uuids = {pack.uuid for pack in development_packs if pack.uuid}
        return normal_uuids.intersection(development_uuids)

    def _has_dev_normal_uuid_conflict(self, addon: Addon) -> bool:
        """Return True when addon UUID exists in both normal and development dirs."""
        if not addon.uuid:
            return False

        if addon.pack_type == PackType.BEHAVIOR:
            duplicate_uuids = self._get_duplicate_uuid_set(
                self._behavior_packs, self._development_behavior_packs
            )
        else:
            duplicate_uuids = self._get_duplicate_uuid_set(
                self._resource_packs, self._development_resource_packs
            )

        return addon.uuid in duplicate_uuids

    @staticmethod
    def _remove_pack_ids_from_world_file(pack_file: str, blocked_uuids: Set[str]) -> None:
        """Remove blocked UUID entries from a world pack JSON file."""
        if not blocked_uuids or not server_fs.exists(pack_file):
            return

        try:
            packs = server_fs.read_json(pack_file)
        except Exception:
            return

        if not isinstance(packs, list):
            return

        filtered = []
        changed = False
        for pack in packs:
            if isinstance(pack, dict) and pack.get("pack_id") in blocked_uuids:
                changed = True
                continue
            filtered.append(pack)

        if not changed:
            return

        try:
            server_fs.write_json(pack_file, filtered)
        except Exception:
            pass

    def _get_enabled_pack_uuids(self, filename: str) -> Set[str]:
        """Get the set of enabled pack UUIDs from a world pack file."""
        uuids = set()

        worlds_path = "worlds"
        if not server_fs.exists(worlds_path) or not server_fs.is_dir(worlds_path):
            return uuids

        for world_dir in server_fs.list_dir(worlds_path):
            if not world_dir.is_dir:
                continue

            pack_file = server_fs.join(world_dir.path, filename)
            if not server_fs.exists(pack_file):
                continue

            try:
                packs = server_fs.read_json(pack_file)
                for pack in packs:
                    uuid = pack.get("pack_id", "")
                    if uuid:
                        uuids.add(uuid)
            except (json.JSONDecodeError, TypeError, Exception):
                pass

        return uuids

    def get_worlds(self) -> List[str]:
        """Get list of available world names."""
        worlds = []

        if not server_fs.exists("worlds") or not server_fs.is_dir("worlds"):
            return worlds

        for world_dir in server_fs.list_dir("worlds"):
            if world_dir.is_dir:
                worlds.append(world_dir.name)

        return sorted(worlds)

    def get_behavior_packs(self) -> List[Addon]:
        """Get all installed behavior packs."""
        return self._behavior_packs.copy()

    def get_resource_packs(self) -> List[Addon]:
        """Get all installed resource packs."""
        return self._resource_packs.copy()

    def get_development_behavior_packs(self) -> List[Addon]:
        """Get development behavior packs."""
        return self._development_behavior_packs.copy()

    def get_development_resource_packs(self) -> List[Addon]:
        """Get development resource packs."""
        return self._development_resource_packs.copy()

    def enable_addon(self, addon: Addon, world_name: str) -> bool:
        """Enable an addon for a specific world."""
        if self._has_dev_normal_uuid_conflict(addon):
            if addon.pack_type == PackType.BEHAVIOR:
                filename = "world_behavior_packs.json"
            else:
                filename = "world_resource_packs.json"
            removed = self._remove_pack_from_world(addon, world_name, filename)
            addon.enabled = False
            return removed

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
        world_dir = server_fs.join("worlds", world_name)
        if not server_fs.exists(world_dir) or not server_fs.is_dir(world_dir):
            return False

        pack_file = server_fs.join(world_dir, filename)

        packs = []
        if server_fs.exists(pack_file):
            try:
                packs = server_fs.read_json(pack_file)
            except (json.JSONDecodeError, OSError, TypeError):
                packs = []

        for pack in packs:
            if pack.get("pack_id") == addon.uuid:
                return True

        packs.append(addon.to_pack_entry())

        try:
            server_fs.write_json(pack_file, packs)
            addon.enabled = True
            return True
        except Exception:
            return False

    def _remove_pack_from_world(
        self, addon: Addon, world_name: str, filename: str
    ) -> bool:
        """Remove a pack entry from a world's pack file."""
        world_dir = server_fs.join("worlds", world_name)
        if not server_fs.exists(world_dir) or not server_fs.is_dir(world_dir):
            return False

        pack_file = server_fs.join(world_dir, filename)
        if not server_fs.exists(pack_file):
            return True

        try:
            packs = server_fs.read_json(pack_file)
        except (json.JSONDecodeError, OSError, TypeError):
            return False

        packs = [p for p in packs if p.get("pack_id") != addon.uuid]

        try:
            server_fs.write_json(pack_file, packs)
            addon.enabled = False
            return True
        except Exception:
            return False

    def is_addon_enabled_in_world(self, addon: Addon, world_name: str) -> bool:
        """Check if an addon is enabled in a specific world."""
        if addon.pack_type == PackType.BEHAVIOR:
            filename = "world_behavior_packs.json"
        else:
            filename = "world_resource_packs.json"

        pack_file = server_fs.join("worlds", world_name, filename)
        if not server_fs.exists(pack_file):
            return False

        try:
            packs = server_fs.read_json(pack_file)
            for pack in packs:
                if pack.get("pack_id") == addon.uuid:
                    return True
        except (json.JSONDecodeError, TypeError, Exception):
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

        pack_file = server_fs.join("worlds", world_name, filename)
        if not server_fs.exists(pack_file):
            return None

        try:
            packs = server_fs.read_json(pack_file)
            for i, pack in enumerate(packs):
                if pack.get("pack_id") == addon.uuid:
                    return i
        except (json.JSONDecodeError, TypeError, Exception):
            pass

        return None

    def get_enabled_pack_count(self, world_name: str, pack_type: PackType) -> int:
        """Get the total count of enabled packs for a world."""
        filename = (
            "world_behavior_packs.json"
            if pack_type == PackType.BEHAVIOR
            else "world_resource_packs.json"
        )

        pack_file = server_fs.join("worlds", world_name, filename)
        if not server_fs.exists(pack_file):
            return 0

        try:
            packs = server_fs.read_json(pack_file)
            return len(packs)
        except (json.JSONDecodeError, TypeError, Exception):
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
        filename = (
            "world_behavior_packs.json"
            if addon.pack_type == PackType.BEHAVIOR
            else "world_resource_packs.json"
        )

        pack_file = server_fs.join("worlds", world_name, filename)
        if not server_fs.exists(pack_file):
            return False

        try:
            packs = server_fs.read_json(pack_file)
        except (json.JSONDecodeError, TypeError, Exception):
            return False

        current_index = None
        for i, pack in enumerate(packs):
            if pack.get("pack_id") == addon.uuid:
                current_index = i
                break

        if current_index is None:
            return False

        new_index = current_index + direction
        if new_index < 0 or new_index >= len(packs):
            return False

        packs[current_index], packs[new_index] = packs[new_index], packs[current_index]

        try:
            server_fs.write_json(pack_file, packs)
            return True
        except Exception:
            return False

    def delete_addon(self, addon: Addon) -> bool:
        """Delete an addon from the server."""
        success = server_fs.delete_tree(addon.path)
        if not success:
            return False

        if addon.pack_type == PackType.BEHAVIOR:
            if addon.is_development:
                self._development_behavior_packs = [
                    p for p in self._development_behavior_packs if p.path != addon.path
                ]
            else:
                self._behavior_packs = [
                    p for p in self._behavior_packs if p.path != addon.path
                ]
        else:
            if addon.is_development:
                self._development_resource_packs = [
                    p for p in self._development_resource_packs if p.path != addon.path
                ]
            else:
                self._resource_packs = [
                    p for p in self._resource_packs if p.path != addon.path
                ]

        return True
