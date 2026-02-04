"""Configuration management for the addon manager."""

import json
import os
import threading
from pathlib import Path
from typing import Optional


class Config:
    """Manages application configuration persistence with debounced saves."""

    DEFAULT_CONFIG = {
        "server_path": "",
        "theme": "dark",
        "window_width": 1200,
        "window_height": 800,
        "default_packs_detected": False,
        "default_pack_uuids": [],
        "last_known_server_version": None,
        "auto_enable_after_import": False,
        "check_for_updates": True,
    }

    def __init__(self):
        self.config_dir = Path.home() / ".minecraft_addon_manager"
        self.config_file = self.config_dir / "config.json"
        self._config = self.DEFAULT_CONFIG.copy()
        self._save_timer: Optional[threading.Timer] = None
        self._save_lock = threading.Lock()
        self._dirty = False
        self._load()

    def _load(self) -> None:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    self._config.update(loaded)
            except (json.JSONDecodeError, IOError):
                pass

    def _schedule_save(self) -> None:
        """Schedule a debounced save operation."""
        with self._save_lock:
            self._dirty = True
            # Cancel any pending save
            if self._save_timer is not None:
                self._save_timer.cancel()
            # Schedule a new save after 500ms
            self._save_timer = threading.Timer(0.5, self._do_save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _do_save(self) -> None:
        """Actually perform the save operation."""
        with self._save_lock:
            if not self._dirty:
                return
            self._dirty = False
            self._save_timer = None

        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self._config, f, indent=2)

    def save(self) -> None:
        """Schedule a save of configuration to file (debounced)."""
        self._schedule_save()

    def save_now(self) -> None:
        """Immediately save configuration to file."""
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
                self._save_timer = None
            self._dirty = False

        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self._config, f, indent=2)

    @property
    def server_path(self) -> str:
        """Get the configured server path."""
        return self._config.get("server_path", "")

    @server_path.setter
    def server_path(self, value: str) -> None:
        """Set the server path."""
        self._config["server_path"] = value
        self.save()

    @property
    def theme(self) -> str:
        """Get the UI theme."""
        return self._config.get("theme", "dark")

    @theme.setter
    def theme(self, value: str) -> None:
        """Set the UI theme."""
        self._config["theme"] = value
        self.save()

    @property
    def window_width(self) -> int:
        """Get window width."""
        return self._config.get("window_width", 1200)

    @window_width.setter
    def window_width(self, value: int) -> None:
        """Set window width."""
        self._config["window_width"] = value
        self.save()

    @property
    def window_height(self) -> int:
        """Get window height."""
        return self._config.get("window_height", 800)

    @window_height.setter
    def window_height(self, value: int) -> None:
        """Set window height."""
        self._config["window_height"] = value
        self.save()

    def is_server_configured(self) -> bool:
        """Check if a valid server path is configured."""
        if not self.server_path:
            return False
        server_dir = Path(self.server_path)
        return server_dir.exists() and server_dir.is_dir()

    def get_behavior_packs_path(self) -> Optional[Path]:
        """Get the behavior_packs directory path."""
        if not self.is_server_configured():
            return None
        return Path(self.server_path) / "behavior_packs"

    def get_resource_packs_path(self) -> Optional[Path]:
        """Get the resource_packs directory path."""
        if not self.is_server_configured():
            return None
        return Path(self.server_path) / "resource_packs"

    def get_worlds_path(self) -> Optional[Path]:
        """Get the worlds directory path."""
        if not self.is_server_configured():
            return None
        return Path(self.server_path) / "worlds"

    @property
    def default_packs_detected(self) -> bool:
        """Check if default packs have been detected."""
        return self._config.get("default_packs_detected", False)

    @default_packs_detected.setter
    def default_packs_detected(self, value: bool) -> None:
        """Set whether default packs have been detected."""
        self._config["default_packs_detected"] = value
        self.save()

    @property
    def default_pack_uuids(self) -> list:
        """Get the list of default pack UUIDs."""
        return self._config.get("default_pack_uuids", [])

    @default_pack_uuids.setter
    def default_pack_uuids(self, value: list) -> None:
        """Set the list of default pack UUIDs."""
        self._config["default_pack_uuids"] = value
        self.save()

    def add_default_pack_uuid(self, uuid: str) -> None:
        """Add a UUID to the default pack list."""
        uuids = self.default_pack_uuids
        if uuid not in uuids:
            uuids.append(uuid)
            self.default_pack_uuids = uuids

    def clear_default_pack_uuids(self) -> None:
        """Clear all default pack UUIDs."""
        self._config["default_pack_uuids"] = []
        self._config["default_packs_detected"] = False
        self.save()

    @property
    def last_known_server_version(self) -> Optional[str]:
        """Get the last known server version."""
        return self._config.get("last_known_server_version")

    @last_known_server_version.setter
    def last_known_server_version(self, value: Optional[str]) -> None:
        """Set the last known server version."""
        self._config["last_known_server_version"] = value
        self.save()

    @property
    def auto_enable_after_import(self) -> bool:
        """Get whether to automatically enable addons after import."""
        return self._config.get("auto_enable_after_import", False)

    @auto_enable_after_import.setter
    def auto_enable_after_import(self, value: bool) -> None:
        """Set whether to automatically enable addons after import."""
        self._config["auto_enable_after_import"] = value
        self.save()

    @property
    def check_for_updates(self) -> bool:
        """Get whether to check for updates on startup."""
        return self._config.get("check_for_updates", True)

    @check_for_updates.setter
    def check_for_updates(self, value: bool) -> None:
        """Set whether to check for updates on startup."""
        self._config["check_for_updates"] = value
        self.save()


# Global config instance
config = Config()
