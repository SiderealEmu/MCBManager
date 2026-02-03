"""Server status querying using mcstatus."""

from dataclasses import dataclass
from typing import List, Optional

from ..config import config


@dataclass
class BedrockServerStatus:
    """Status information from a Bedrock server."""

    version: Optional[str] = None
    version_parts: Optional[List[int]] = None
    players_online: int = 0
    players_max: int = 0
    motd: Optional[str] = None
    map_name: Optional[str] = None
    gamemode: Optional[str] = None
    latency: Optional[float] = None
    online: bool = False
    error: Optional[str] = None

    @property
    def version_string(self) -> str:
        """Get version as display string."""
        return self.version if self.version else "Unknown"


class ServerStatusQuery:
    """Queries Minecraft Bedrock server status using mcstatus."""

    def __init__(self, host: str = "localhost", port: Optional[int] = None):
        """Initialize the status query.

        Args:
            host: Server hostname or IP address.
            port: Server port. If None, will try to read from server.properties.
        """
        self.host = host
        self._port = port
        self._last_status: Optional[BedrockServerStatus] = None

    @property
    def port(self) -> int:
        """Get the server port."""
        if self._port is not None:
            return self._port

        # Try to get port from server.properties
        from .properties import ServerProperties

        props = ServerProperties()
        if props.load():
            return props.server_port

        # Default Bedrock port
        return 19132

    def query(self) -> BedrockServerStatus:
        """Query the server for its current status.

        Returns:
            BedrockServerStatus with server information, or error details if failed.
        """
        try:
            from mcstatus import BedrockServer
        except ImportError:
            return BedrockServerStatus(
                online=False,
                error="mcstatus library not installed. Run: pip install mcstatus",
            )

        try:
            # Create server with timeout specified in constructor
            server = BedrockServer(self.host, self.port, timeout=5.0)
            status = server.status()

            # Parse version into parts
            version_parts = None
            version_name = None
            if status.version and status.version.name:
                version_name = status.version.name
                try:
                    # Version format is typically "1.20.81"
                    parts = version_name.split(".")
                    version_parts = [int(p) for p in parts[:3]]
                except (ValueError, IndexError):
                    pass

            self._last_status = BedrockServerStatus(
                version=version_name,
                version_parts=version_parts,
                players_online=status.players.online if status.players else 0,
                players_max=status.players.max if status.players else 0,
                motd=status.motd.raw if status.motd else None,
                map_name=status.map_name,
                gamemode=status.gamemode,
                latency=status.latency,
                online=True,
            )

        except TimeoutError:
            self._last_status = BedrockServerStatus(
                online=False, error="Server not responding (timeout)"
            )
        except ConnectionRefusedError:
            self._last_status = BedrockServerStatus(
                online=False, error="Connection refused"
            )
        except OSError as e:
            # Network-related errors
            self._last_status = BedrockServerStatus(
                online=False, error=f"Network error: {str(e)}"
            )
        except Exception as e:
            self._last_status = BedrockServerStatus(
                online=False,
                error=f"Failed to query server: {type(e).__name__}: {str(e)}",
            )

        return self._last_status

    @property
    def last_status(self) -> Optional[BedrockServerStatus]:
        """Get the last queried status without making a new request."""
        return self._last_status

    def get_version(self) -> Optional[str]:
        """Query and return just the server version string.

        Returns:
            Version string like "1.20.81", or None if query failed.
        """
        status = self.query()
        return status.version if status.online else None

    def get_version_parts(self) -> Optional[List[int]]:
        """Query and return the server version as a list of integers.

        Returns:
            Version as [major, minor, patch], or None if query failed.
        """
        status = self.query()
        return status.version_parts if status.online else None


def get_server_version() -> Optional[List[int]]:
    """Convenience function to get the server version.

    Returns:
        Version as [major, minor, patch], or None if server is not running or query failed.
    """
    query = ServerStatusQuery()
    return query.get_version_parts()


def get_server_version_string() -> Optional[str]:
    """Convenience function to get the server version as a string.

    Returns:
        Version string like "1.20.81", or None if server is not running or query failed.
    """
    query = ServerStatusQuery()
    return query.get_version()
