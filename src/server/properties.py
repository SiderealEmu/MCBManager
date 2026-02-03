"""Server properties parsing."""

from pathlib import Path
from typing import Dict, Optional

from ..config import config


class ServerProperties:
    """Parses and provides access to server.properties values."""

    def __init__(self):
        self._properties: Dict[str, str] = {}
        self._loaded = False

    def load(self) -> bool:
        """Load server.properties file."""
        self._properties = {}
        self._loaded = False

        if not config.is_server_configured():
            return False

        properties_path = Path(config.server_path) / "server.properties"

        if not properties_path.exists():
            return False

        try:
            with open(properties_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        if "=" in line:
                            key, value = line.split("=", 1)
                            self._properties[key.strip()] = value.strip()
            self._loaded = True
            return True
        except IOError:
            return False

    def reload(self) -> bool:
        """Reload the properties file."""
        return self.load()

    @property
    def is_loaded(self) -> bool:
        """Check if properties have been loaded."""
        return self._loaded

    def get(self, key: str, default: str = "") -> str:
        """Get a property value."""
        return self._properties.get(key, default)

    @property
    def server_name(self) -> str:
        """Get the server name."""
        return self.get("server-name", "Dedicated Server")

    @property
    def level_name(self) -> str:
        """Get the world/level name."""
        return self.get("level-name", "Bedrock level")

    @property
    def gamemode(self) -> str:
        """Get the default gamemode."""
        return self.get("gamemode", "survival")

    @property
    def difficulty(self) -> str:
        """Get the difficulty."""
        return self.get("difficulty", "easy")

    @property
    def max_players(self) -> int:
        """Get maximum players allowed."""
        try:
            return int(self.get("max-players", "10"))
        except ValueError:
            return 10

    @property
    def server_port(self) -> int:
        """Get the server port."""
        try:
            return int(self.get("server-port", "19132"))
        except ValueError:
            return 19132

    @property
    def server_portv6(self) -> int:
        """Get the IPv6 server port."""
        try:
            return int(self.get("server-portv6", "19133"))
        except ValueError:
            return 19133

    @property
    def online_mode(self) -> bool:
        """Check if online mode is enabled."""
        return self.get("online-mode", "true").lower() == "true"

    @property
    def allow_cheats(self) -> bool:
        """Check if cheats are allowed."""
        return self.get("allow-cheats", "false").lower() == "true"

    @property
    def view_distance(self) -> int:
        """Get the view distance."""
        try:
            return int(self.get("view-distance", "32"))
        except ValueError:
            return 32

    @property
    def tick_distance(self) -> int:
        """Get the simulation distance."""
        try:
            return int(self.get("tick-distance", "4"))
        except ValueError:
            return 4

    @property
    def level_seed(self) -> str:
        """Get the level seed."""
        return self.get("level-seed", "")

    @property
    def default_player_permission_level(self) -> str:
        """Get default player permission level."""
        return self.get("default-player-permission-level", "member")

    @property
    def texturepack_required(self) -> bool:
        """Check if texture pack is required."""
        return self.get("texturepack-required", "false").lower() == "true"

    def get_all_properties(self) -> Dict[str, str]:
        """Get all properties as a dictionary."""
        return self._properties.copy()
