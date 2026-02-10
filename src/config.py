"""Configuration management for the addon manager."""

import json
import threading
from pathlib import Path
from typing import Optional

try:
    import keyring
except Exception:  # pragma: no cover - import-time environment differences
    keyring = None


KEYRING_SERVICE_NAME = "MCBManager"
SFTP_PASSWORD_KEYRING_ACCOUNT = "sftp_password"


class Config:
    """Manages application configuration persistence with debounced saves."""

    DEFAULT_CONFIG = {
        "connection_type": "local",
        "server_path": "",
        "sftp_host": "",
        "sftp_port": 22,
        "sftp_username": "",
        "sftp_password": "",
        "sftp_key_file": "",
        "sftp_remote_path": "",
        "sftp_timeout": 10,
        "sftp_status_host": "",
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
        self._migrate_legacy_sftp_password()

    def _load(self) -> None:
        """Load configuration from file."""
        if self.config_file.exists():
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    self._config.update(loaded)
            except (json.JSONDecodeError, IOError):
                pass

    @staticmethod
    def _is_keyring_available() -> bool:
        """Return True if keyring is importable in this environment."""
        return keyring is not None

    def _get_sftp_password_from_keyring(self) -> Optional[str]:
        """Read SFTP password from the OS credential store."""
        if not self._is_keyring_available():
            return None

        try:
            value = keyring.get_password(
                KEYRING_SERVICE_NAME, SFTP_PASSWORD_KEYRING_ACCOUNT
            )
            return value or ""
        except Exception:
            return None

    def _set_sftp_password_in_keyring(self, password: str) -> bool:
        """Write/delete SFTP password in the OS credential store."""
        if not self._is_keyring_available():
            return False

        try:
            if password:
                keyring.set_password(
                    KEYRING_SERVICE_NAME, SFTP_PASSWORD_KEYRING_ACCOUNT, password
                )
            else:
                try:
                    keyring.delete_password(
                        KEYRING_SERVICE_NAME, SFTP_PASSWORD_KEYRING_ACCOUNT
                    )
                except Exception:
                    pass
            return True
        except Exception:
            return False

    def _migrate_legacy_sftp_password(self) -> None:
        """Move any legacy plaintext SFTP password to keyring if possible."""
        legacy_password = self._config.get("sftp_password", "") or ""
        if not legacy_password:
            return

        if self._set_sftp_password_in_keyring(legacy_password):
            self._config.pop("sftp_password", None)
            self.save_now()

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
    def connection_type(self) -> str:
        """Get active server connection type ('local' or 'sftp')."""
        value = str(self._config.get("connection_type", "local")).lower().strip()
        return value if value in {"local", "sftp"} else "local"

    @connection_type.setter
    def connection_type(self, value: str) -> None:
        """Set active server connection type."""
        normalized = str(value).lower().strip()
        self._config["connection_type"] = "sftp" if normalized == "sftp" else "local"
        self.save()

    @property
    def sftp_host(self) -> str:
        """Get configured SFTP host."""
        return self._config.get("sftp_host", "")

    @sftp_host.setter
    def sftp_host(self, value: str) -> None:
        """Set SFTP host."""
        self._config["sftp_host"] = value.strip()
        self.save()

    @property
    def sftp_port(self) -> int:
        """Get configured SFTP port."""
        try:
            return int(self._config.get("sftp_port", 22))
        except (TypeError, ValueError):
            return 22

    @sftp_port.setter
    def sftp_port(self, value: int) -> None:
        """Set SFTP port."""
        try:
            port = int(value)
        except (TypeError, ValueError):
            port = 22
        self._config["sftp_port"] = max(1, min(65535, port))
        self.save()

    @property
    def sftp_username(self) -> str:
        """Get configured SFTP username."""
        return self._config.get("sftp_username", "")

    @sftp_username.setter
    def sftp_username(self, value: str) -> None:
        """Set SFTP username."""
        self._config["sftp_username"] = value.strip()
        self.save()

    @property
    def sftp_password(self) -> str:
        """Get configured SFTP password."""
        password = self._get_sftp_password_from_keyring()
        if password is not None:
            return password
        return self._config.get("sftp_password", "")

    @sftp_password.setter
    def sftp_password(self, value: str) -> None:
        """Set SFTP password."""
        password = value or ""
        if self._set_sftp_password_in_keyring(password):
            if "sftp_password" in self._config:
                self._config.pop("sftp_password", None)
                self.save()
            return

        # Fallback for environments without keyring support.
        self._config["sftp_password"] = password
        self.save()

    @property
    def sftp_key_file(self) -> str:
        """Get configured SFTP private key file path."""
        return self._config.get("sftp_key_file", "")

    @sftp_key_file.setter
    def sftp_key_file(self, value: str) -> None:
        """Set SFTP private key file path."""
        self._config["sftp_key_file"] = value.strip()
        self.save()

    @property
    def sftp_remote_path(self) -> str:
        """Get configured SFTP server root path."""
        return self._config.get("sftp_remote_path", "")

    @sftp_remote_path.setter
    def sftp_remote_path(self, value: str) -> None:
        """Set SFTP server root path."""
        self._config["sftp_remote_path"] = (value or "").strip()
        self.save()

    @property
    def sftp_timeout(self) -> int:
        """Get SFTP connection timeout (seconds)."""
        try:
            timeout = int(self._config.get("sftp_timeout", 10))
            return max(3, min(60, timeout))
        except (TypeError, ValueError):
            return 10

    @sftp_timeout.setter
    def sftp_timeout(self, value: int) -> None:
        """Set SFTP connection timeout (seconds)."""
        try:
            timeout = int(value)
        except (TypeError, ValueError):
            timeout = 10
        self._config["sftp_timeout"] = max(3, min(60, timeout))
        self.save()

    @property
    def sftp_status_host(self) -> str:
        """Get optional status query host override for SFTP mode."""
        return self._config.get("sftp_status_host", "")

    @sftp_status_host.setter
    def sftp_status_host(self, value: str) -> None:
        """Set optional status query host override for SFTP mode."""
        self._config["sftp_status_host"] = (value or "").strip()
        self.save()

    @property
    def server_status_host(self) -> str:
        """Get host to use for Bedrock status queries."""
        if self.connection_type == "sftp":
            return self.sftp_status_host or self.sftp_host or "localhost"
        return "localhost"

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
        if self.connection_type == "sftp":
            return bool(self.sftp_host and self.sftp_username and self.sftp_remote_path)

        if not self.server_path:
            return False
        server_dir = Path(self.server_path)
        return server_dir.exists() and server_dir.is_dir()

    def get_behavior_packs_path(self) -> Optional[Path]:
        """Get the behavior_packs directory path."""
        if self.connection_type == "sftp":
            return None
        if not self.is_server_configured():
            return None
        return Path(self.server_path) / "behavior_packs"

    def get_resource_packs_path(self) -> Optional[Path]:
        """Get the resource_packs directory path."""
        if self.connection_type == "sftp":
            return None
        if not self.is_server_configured():
            return None
        return Path(self.server_path) / "resource_packs"

    def get_worlds_path(self) -> Optional[Path]:
        """Get the worlds directory path."""
        if self.connection_type == "sftp":
            return None
        if not self.is_server_configured():
            return None
        return Path(self.server_path) / "worlds"

    def get_server_display_path(self) -> str:
        """Get a user-facing display value for the configured server location."""
        if self.connection_type == "sftp":
            if not self.is_server_configured():
                return ""
            return (
                f"sftp://{self.sftp_username}@{self.sftp_host}:{self.sftp_port}"
                f"{self.sftp_remote_path}"
            )
        return self.server_path

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
