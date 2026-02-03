"""Server monitoring functionality."""

import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

from ..config import config


def _get_subprocess_startupinfo():
    """Get subprocess startupinfo to hide console window on Windows."""
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        return startupinfo
    return None


class ServerMonitor:
    """Monitors Minecraft Bedrock server status."""

    BEDROCK_PROCESS_NAMES = ["bedrock_server", "bedrock_server.exe", "bedrock-server"]

    def __init__(self):
        self._is_running = False
        self._process_name: Optional[str] = None

    def check_status(self) -> bool:
        """Check if the Bedrock server is running."""
        self._is_running = False
        self._process_name = None

        system = platform.system()

        try:
            if system == "Windows":
                self._is_running = self._check_windows()
            elif system == "Darwin":  # macOS
                self._is_running = self._check_unix()
            else:  # Linux and others
                self._is_running = self._check_unix()
        except Exception:
            self._is_running = False

        return self._is_running

    def _check_windows(self) -> bool:
        """Check for running server on Windows."""
        try:
            output = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq bedrock_server.exe"],
                stderr=subprocess.DEVNULL,
                text=True,
                startupinfo=_get_subprocess_startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32"
                else 0,
            )
            if "bedrock_server.exe" in output.lower():
                self._process_name = "bedrock_server.exe"
                return True
        except subprocess.SubprocessError:
            pass
        return False

    def _check_unix(self) -> bool:
        """Check for running server on Unix-like systems."""
        try:
            output = subprocess.check_output(
                ["pgrep", "-l", "-f", "bedrock_server"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            if output.strip():
                self._process_name = "bedrock_server"
                return True
        except subprocess.SubprocessError:
            pass

        # Fallback: check with ps
        try:
            output = subprocess.check_output(
                ["ps", "aux"], stderr=subprocess.DEVNULL, text=True
            )
            for name in self.BEDROCK_PROCESS_NAMES:
                if name in output:
                    self._process_name = name
                    return True
        except subprocess.SubprocessError:
            pass

        return False

    @property
    def is_running(self) -> bool:
        """Get the last known running status."""
        return self._is_running

    @property
    def process_name(self) -> Optional[str]:
        """Get the detected process name."""
        return self._process_name

    def get_server_executable(self) -> Optional[Path]:
        """Get the path to the server executable."""
        if not config.is_server_configured():
            return None

        server_path = Path(config.server_path)

        # Check for different executable names
        for name in self.BEDROCK_PROCESS_NAMES:
            exe_path = server_path / name
            if exe_path.exists():
                return exe_path

        return None

    def server_exists(self) -> bool:
        """Check if the server executable exists."""
        return self.get_server_executable() is not None

    def get_status_text(self) -> str:
        """Get a human-readable status string."""
        if not config.is_server_configured():
            return "Not Configured"

        if not self.server_exists():
            return "Server Not Found"

        self.check_status()

        if self._is_running:
            return "Running"
        else:
            return "Stopped"
