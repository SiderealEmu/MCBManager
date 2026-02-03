"""Server status panel UI component."""

import threading
from typing import Callable, Optional

import customtkinter as ctk

from ..config import config
from ..server import ServerMonitor, ServerProperties, ServerStatusQuery


class ServerPanel(ctk.CTkFrame):
    """Panel displaying server status and information."""

    def __init__(
        self,
        parent,
        server_monitor: ServerMonitor,
        server_properties: ServerProperties,
        on_configure: Optional[Callable] = None,
    ):
        super().__init__(parent, width=280)

        self.server_monitor = server_monitor
        self.server_properties = server_properties
        self.on_configure = on_configure
        self.status_query = ServerStatusQuery()
        self._poll_job_id = None
        self._poll_interval = 5000  # 5 seconds
        self._query_in_progress = False
        self._pending_version_result = None

        # Prevent frame from shrinking
        self.grid_propagate(False)

        self._create_widgets()
        self._start_polling()

    def _create_widgets(self) -> None:
        """Create panel widgets."""
        # Title
        title_label = ctk.CTkLabel(
            self, text="Server Status", font=ctk.CTkFont(size=18, weight="bold")
        )
        title_label.pack(pady=(15, 10))

        # Status indicator
        self.status_frame = ctk.CTkFrame(self)
        self.status_frame.pack(fill="x", padx=15, pady=5)

        status_title = ctk.CTkLabel(
            self.status_frame, text="Status:", font=ctk.CTkFont(weight="bold")
        )
        status_title.pack(side="left", padx=10, pady=8)

        self.status_indicator = ctk.CTkLabel(
            self.status_frame, text="Unknown", font=ctk.CTkFont(size=13)
        )
        self.status_indicator.pack(side="right", padx=10, pady=8)

        # Server info section
        info_label = ctk.CTkLabel(
            self, text="Server Info", font=ctk.CTkFont(size=14, weight="bold")
        )
        info_label.pack(pady=(15, 5), anchor="w", padx=15)

        self.info_frame = ctk.CTkFrame(self)
        self.info_frame.pack(fill="x", padx=15, pady=5)

        # Info items
        self.info_items = {}
        info_fields = [
            ("Version", "version"),
            ("Server Name", "server_name"),
            ("World", "level_name"),
            ("Gamemode", "gamemode"),
            ("Difficulty", "difficulty"),
            ("Max Players", "max_players"),
            ("Port", "server_port"),
        ]

        for display_name, prop_name in info_fields:
            row_frame = ctk.CTkFrame(self.info_frame, fg_color="transparent")
            row_frame.pack(fill="x", padx=10, pady=2)

            label = ctk.CTkLabel(
                row_frame,
                text=f"{display_name}:",
                font=ctk.CTkFont(size=12),
                text_color="gray",
            )
            label.pack(side="left")

            value_label = ctk.CTkLabel(row_frame, text="-", font=ctk.CTkFont(size=12))
            value_label.pack(side="right")

            self.info_items[prop_name] = value_label

        # Spacer
        spacer = ctk.CTkFrame(self, fg_color="transparent", height=20)
        spacer.pack(fill="x")

        # Configure button
        self.configure_btn = ctk.CTkButton(
            self, text="Configure Server Path", command=self._on_configure_click
        )
        self.configure_btn.pack(pady=10, padx=15, fill="x")

        # Refresh button
        self.refresh_btn = ctk.CTkButton(
            self, text="Refresh Status", fg_color="gray", command=self.refresh
        )
        self.refresh_btn.pack(pady=5, padx=15, fill="x")

        # Server path display
        path_label = ctk.CTkLabel(
            self,
            text="Server Path:",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray",
        )
        path_label.pack(pady=(20, 2), anchor="w", padx=15)

        self.path_display = ctk.CTkLabel(
            self,
            text="Not configured",
            font=ctk.CTkFont(size=10),
            text_color="gray",
            wraplength=250,
        )
        self.path_display.pack(anchor="w", padx=15, pady=(0, 10))

    def _on_configure_click(self) -> None:
        """Handle configure button click."""
        if self.on_configure:
            self.on_configure()

    def update_status(self) -> None:
        """Update just the server status indicator."""
        if self.server_monitor.is_running:
            self.status_indicator.configure(text="Running", text_color="#00C853")
        elif not config.is_server_configured():
            self.status_indicator.configure(text="Not Configured", text_color="#FFC107")
        elif not self.server_monitor.server_exists():
            self.status_indicator.configure(text="Server Not Found", text_color="gray")
        else:
            self.status_indicator.configure(text="Stopped", text_color="#FF5252")

    def refresh(self) -> None:
        """Refresh the server status display."""
        # Update status
        self.server_monitor.check_status()
        self.update_status()

        # Update server info
        if self.server_properties.is_loaded:
            # Query server for version (only if server is running)
            if self.server_monitor.is_running:
                status = self.status_query.query()
                if status.online and status.version:
                    # Save the version to config for when server goes offline
                    config.last_known_server_version = status.version
                    self.info_items["version"].configure(text=status.version_string)
                elif config.last_known_server_version:
                    # Query failed but we have a cached version
                    self.info_items["version"].configure(
                        text=config.last_known_server_version
                    )
                else:
                    self.info_items["version"].configure(text="Query failed")
            else:
                # Server offline - show last known version if available
                if config.last_known_server_version:
                    self.info_items["version"].configure(
                        text=f"{config.last_known_server_version} (offline)"
                    )
                else:
                    self.info_items["version"].configure(text="Server offline")
            self.info_items["server_name"].configure(
                text=self._truncate(self.server_properties.server_name, 20)
            )
            self.info_items["level_name"].configure(
                text=self._truncate(self.server_properties.level_name, 20)
            )
            self.info_items["gamemode"].configure(
                text=self.server_properties.gamemode.capitalize()
            )
            self.info_items["difficulty"].configure(
                text=self.server_properties.difficulty.capitalize()
            )
            self.info_items["max_players"].configure(
                text=str(self.server_properties.max_players)
            )
            self.info_items["server_port"].configure(
                text=str(self.server_properties.server_port)
            )
        else:
            for key in self.info_items:
                self.info_items[key].configure(text="-")

        # Update path display
        if config.server_path:
            display_path = config.server_path
            if len(display_path) > 40:
                display_path = "..." + display_path[-37:]
            self.path_display.configure(text=display_path)
        else:
            self.path_display.configure(text="Not configured")

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _start_polling(self) -> None:
        """Start the periodic status polling."""
        self._poll_status()

    def _poll_status(self) -> None:
        """Poll the server status and schedule the next poll."""
        # Check if server is running (fast, local check)
        self.server_monitor.check_status()
        self.update_status()

        # Query server version in background if running and not already querying
        if self.server_monitor.is_running and not self._query_in_progress:
            self._query_in_progress = True
            thread = threading.Thread(
                target=self._query_version_background, daemon=True
            )
            thread.start()
        elif not self.server_monitor.is_running and self.server_properties.is_loaded:
            # Server offline - show last known version if available
            if config.last_known_server_version:
                self.info_items["version"].configure(
                    text=f"{config.last_known_server_version} (offline)"
                )
            else:
                self.info_items["version"].configure(text="Server offline")

        # Schedule next poll
        self._poll_job_id = self.after(self._poll_interval, self._poll_status)

    def _query_version_background(self) -> None:
        """Query server version in background thread."""
        try:
            status = self.status_query.query()
            self._pending_version_result = status
            # Schedule UI update on main thread
            self.after(0, self._update_version_from_result)
        except Exception:
            self._query_in_progress = False

    def _update_version_from_result(self) -> None:
        """Update version display from background query result (called on main thread)."""
        self._query_in_progress = False
        status = self._pending_version_result
        if status is None:
            return

        if status.online and status.version:
            # Save the version to config for when server goes offline
            config.last_known_server_version = status.version
            self.info_items["version"].configure(text=status.version_string)
        elif config.last_known_server_version:
            # Query failed but we have a cached version
            self.info_items["version"].configure(text=config.last_known_server_version)
        else:
            self.info_items["version"].configure(text="Query failed")

    def stop_polling(self) -> None:
        """Stop the periodic status polling."""
        if self._poll_job_id is not None:
            self.after_cancel(self._poll_job_id)
            self._poll_job_id = None

    def destroy(self) -> None:
        """Clean up when the widget is destroyed."""
        self.stop_polling()
        super().destroy()
