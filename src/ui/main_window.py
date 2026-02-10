"""Main application window."""

import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from ..addon import Addon, AddonManager, PackType
from ..config import config
from ..server import ServerMonitor, ServerProperties, server_fs
from ..updater import check_for_updates, check_for_updates_async, open_release_url, UpdateInfo
from .addon_panel import AddonPanel
from .server_panel import ServerPanel


def set_dialog_icon(dialog: ctk.CTkToplevel) -> None:
    """Set the MCBManager icon for a dialog window."""
    # Determine base path (handles PyInstaller bundled apps)
    if getattr(sys, "frozen", False):
        base_path = Path(sys._MEIPASS)
    else:
        base_path = Path(__file__).parent.parent.parent

    icon_path = base_path / "assets" / "MCBManagerIcon.png"
    ico_path = base_path / "assets" / "MCBManagerIcon.ico"

    try:
        if ico_path.exists():
            dialog.after(200, lambda: dialog.iconbitmap(str(ico_path)))
        if icon_path.exists():
            icon_image = Image.open(icon_path)
            icon_photo = ImageTk.PhotoImage(icon_image)
            dialog._icon_photo = icon_photo  # Keep reference
            dialog.iconphoto(True, icon_photo)
    except Exception:
        pass  # Silently fail if icon cannot be loaded


class MainWindow(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Configure window
        self.title("MCBManager")
        self.geometry(f"{config.window_width}x{config.window_height}")
        self.minsize(900, 600)

        # Set window icon
        self._set_icon()

        # Set appearance
        ctk.set_appearance_mode(config.theme)
        ctk.set_default_color_theme("blue")

        # Initialize managers
        self.addon_manager = AddonManager()
        self.server_monitor = ServerMonitor()
        self.server_properties = ServerProperties()
        self._refresh_lock = threading.Lock()
        self._refresh_in_progress = False
        self._refresh_pending = False
        self._refresh_callbacks: List[Callable[[], None]] = []

        # Build UI
        self._create_layout()
        self._create_menu_bar()

        # Load data if configured
        if config.is_server_configured():
            # Load default pack UUIDs first, before refreshing addon lists
            Addon.set_default_pack_uuids(set(config.default_pack_uuids))
            self._load_server_data(on_complete=self._check_default_packs_detection)
        else:
            self._prompt_server_path()

        # Bind window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Check for updates after window is shown
        if config.check_for_updates:
            self.after(1000, self._check_for_updates)

    def _check_for_updates(self) -> None:
        """Check for updates in the background."""
        check_for_updates_async(self._on_update_check_complete)

    def _on_update_check_complete(self, update_info: UpdateInfo) -> None:
        """Handle update check result (called from background thread)."""
        if update_info and update_info.is_update_available:
            # Schedule dialog on main thread
            self.after(0, lambda: self._show_update_dialog(update_info))

    def _show_update_dialog(self, update_info: UpdateInfo) -> None:
        """Show the update available dialog."""
        dialog = UpdateDialog(self, update_info)
        self.wait_window(dialog)

    def _set_icon(self) -> None:
        """Set the window and taskbar icon."""
        # Determine base path (handles PyInstaller bundled apps)
        if getattr(sys, "frozen", False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent.parent

        icon_path = base_path / "assets" / "MCBManagerIcon.png"
        ico_path = base_path / "assets" / "MCBManagerIcon.ico"

        try:
            # On Windows, use .ico for taskbar icon if available
            if ico_path.exists():
                self.iconbitmap(str(ico_path))
            if icon_path.exists():
                # Also set iconphoto for window title bar icon
                icon_image = Image.open(icon_path)
                icon_photo = ImageTk.PhotoImage(icon_image)
                # Keep reference to prevent garbage collection
                self._icon_photo = icon_photo
                self.iconphoto(True, icon_photo)
        except Exception:
            # Silently fail if icon cannot be loaded
            pass

    def _create_layout(self) -> None:
        """Create the main layout."""
        # Configure grid
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left sidebar - Server Panel
        self.server_panel = ServerPanel(
            self,
            self.server_monitor,
            self.server_properties,
            on_configure=self._prompt_server_path,
        )
        self.server_panel.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

        # Main content - Addon Panel
        self.addon_panel = AddonPanel(
            self, self.addon_manager, self.server_monitor, on_refresh=self._refresh_data
        )
        self.addon_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 10), pady=10)

    def _create_menu_bar(self) -> None:
        """Create the top menu bar."""
        # Create a frame for the menu
        self.menu_frame = ctk.CTkFrame(self, height=40, corner_radius=0)
        self.menu_frame.grid(
            row=0, column=0, columnspan=2, sticky="new", padx=0, pady=0
        )
        self.menu_frame.grid_columnconfigure(2, weight=1)

        # Title label
        title_label = ctk.CTkLabel(
            self.menu_frame,
            text="Bedrock Addon Manager",
            font=ctk.CTkFont(size=16, weight="bold"),
        )
        title_label.grid(row=0, column=0, padx=15, pady=8)

        # Settings button
        self.settings_btn = ctk.CTkButton(
            self.menu_frame, text="Settings", width=80, command=self._show_settings
        )
        self.settings_btn.grid(row=0, column=3, padx=10, pady=5)

        # Move panels down
        self.server_panel.grid(
            row=1, column=0, sticky="nsew", padx=(10, 5), pady=(5, 10)
        )
        self.addon_panel.grid(
            row=1, column=1, sticky="nsew", padx=(5, 10), pady=(5, 10)
        )
        self.grid_rowconfigure(0, weight=0)  # Menu bar row doesn't expand
        self.grid_rowconfigure(1, weight=1)  # Panel row expands

    def _check_default_packs_detection(self) -> None:
        """Check if we need to detect default packs on first launch."""
        # Load existing default pack UUIDs into the Addon class
        Addon.set_default_pack_uuids(set(config.default_pack_uuids))

        # If default packs haven't been detected yet, ask the user
        if not config.default_packs_detected:
            self.after(100, self._show_default_packs_dialog)

    def _show_default_packs_dialog(self) -> None:
        """Show dialog asking about existing custom packs."""
        dialog = DefaultPacksDialog(self, self.addon_manager)
        self.wait_window(dialog)

        # Reload the default pack UUIDs into the Addon class
        Addon.set_default_pack_uuids(set(config.default_pack_uuids))

        # Refresh the addon panel to apply filtering
        self.addon_panel.refresh()

    def _prompt_server_path(self) -> None:
        """Prompt the user to configure the server connection."""
        dialog = ServerPathDialog(self)
        self.wait_window(dialog)

        if dialog.result:
            server_fs.close()
            self._load_server_data(on_complete=self._check_default_packs_detection)

    def _set_refresh_ui_state(self, is_refreshing: bool) -> None:
        """Update refresh button states to reflect background refresh work."""
        if hasattr(self, "addon_panel") and hasattr(self.addon_panel, "refresh_btn"):
            self.addon_panel.refresh_btn.configure(
                text="Refreshing..." if is_refreshing else "Refresh",
                state="disabled" if is_refreshing else "normal",
            )
        if hasattr(self, "server_panel") and hasattr(self.server_panel, "refresh_btn"):
            self.server_panel.refresh_btn.configure(
                text="Refreshing..." if is_refreshing else "Refresh Status",
                state="disabled" if is_refreshing else "normal",
            )

    def _load_server_data(self, on_complete: Optional[Callable[[], None]] = None) -> None:
        """Queue a full data refresh in the background."""
        self._refresh_data(on_complete=on_complete)

    def _refresh_data(self, on_complete: Optional[Callable[[], None]] = None) -> None:
        """Refresh all data in a background worker."""
        if not config.is_server_configured():
            return

        should_start_worker = False
        with self._refresh_lock:
            if on_complete is not None:
                self._refresh_callbacks.append(on_complete)
            if self._refresh_in_progress:
                self._refresh_pending = True
            else:
                self._refresh_in_progress = True
                should_start_worker = True

        if not should_start_worker:
            return

        self._set_refresh_ui_state(True)
        threading.Thread(target=self._refresh_data_worker, daemon=True).start()

    def _refresh_data_worker(self) -> None:
        """Load server properties and addon data off the UI thread."""
        loaded_properties = ServerProperties()
        loaded_addon_manager = AddonManager()
        success = True

        try:
            loaded_properties.load()
            loaded_addon_manager.refresh()
        except Exception:
            success = False

        try:
            self.after(
                0,
                lambda: self._on_refresh_data_complete(
                    success, loaded_properties, loaded_addon_manager
                ),
            )
        except Exception:
            pass

    def _on_refresh_data_complete(
        self,
        success: bool,
        loaded_properties: ServerProperties,
        loaded_addon_manager: AddonManager,
    ) -> None:
        """Apply background refresh results and update UI."""
        with self._refresh_lock:
            callbacks = self._refresh_callbacks
            self._refresh_callbacks = []

        if success:
            self.server_properties = loaded_properties
            self.addon_manager = loaded_addon_manager
            self.server_panel.server_properties = self.server_properties
            self.addon_panel.addon_manager = self.addon_manager
            self.server_panel.refresh()
            self.addon_panel.refresh()

            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    pass

        should_restart = False
        with self._refresh_lock:
            if self._refresh_pending:
                self._refresh_pending = False
                should_restart = True
            else:
                self._refresh_in_progress = False

        if should_restart:
            threading.Thread(target=self._refresh_data_worker, daemon=True).start()
        else:
            self._set_refresh_ui_state(False)

    def _show_settings(self) -> None:
        """Show settings dialog."""
        dialog = SettingsDialog(self, self.addon_manager)
        self.wait_window(dialog)

        if dialog.changed:
            self._load_server_data()

    def _on_close(self) -> None:
        """Handle window close."""
        # Save window size
        config.window_width = self.winfo_width()
        config.window_height = self.winfo_height()
        # Ensure config is saved immediately before closing
        config.save_now()
        self.destroy()


class ServerPathDialog(ctk.CTkToplevel):
    """Dialog for configuring local or SFTP server connection."""

    def __init__(self, parent):
        super().__init__(parent)

        self.result: Optional[bool] = None
        self._dialog_width = 680
        self._dialog_height = 620

        self.title("Configure Server Connection")
        self.geometry(f"{self._dialog_width}x{self._dialog_height}")
        self.resizable(False, False)

        # Set window icon
        set_dialog_icon(self)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on screen (parent geometry may not be finalized on first launch)
        self.update_idletasks()
        x = (self.winfo_screenwidth() - self._dialog_width) // 2
        y = (self.winfo_screenheight() - self._dialog_height) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        label = ctk.CTkLabel(
            self,
            text="Choose how to connect to your Bedrock server files:",
            font=ctk.CTkFont(size=14),
        )
        label.pack(pady=(20, 12))

        self.connection_mode_var = ctk.StringVar(value=config.connection_type)
        mode_switch = ctk.CTkSegmentedButton(
            self,
            values=["local", "sftp"],
            variable=self.connection_mode_var,
            command=self._on_mode_change,
        )
        mode_switch.pack(padx=20, pady=(0, 12))

        content_frame = ctk.CTkScrollableFrame(self)
        content_frame.pack(fill="both", expand=True, padx=20, pady=5)

        self.local_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.sftp_frame = ctk.CTkFrame(content_frame, fg_color="transparent")

        self._create_local_widgets()
        self._create_sftp_widgets()
        self._on_mode_change(self.connection_mode_var.get())

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=16)

        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", width=100, fg_color="gray", command=self.destroy
        )
        cancel_btn.pack(side="right", padx=5)

        save_btn = ctk.CTkButton(
            btn_frame, text="Confirm", width=100, command=self._save
        )
        save_btn.pack(side="right", padx=5)

    def _create_local_widgets(self) -> None:
        """Create local filesystem connection fields."""
        description = ctk.CTkLabel(
            self.local_frame,
            text="Local Folder Path",
            font=ctk.CTkFont(weight="bold"),
        )
        description.pack(anchor="w", pady=(6, 4))

        path_frame = ctk.CTkFrame(self.local_frame, fg_color="transparent")
        path_frame.pack(fill="x", pady=(0, 10))

        self.path_entry = ctk.CTkEntry(path_frame, width=420)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.path_entry.insert(0, config.server_path)

        browse_btn = ctk.CTkButton(
            path_frame, text="Browse", width=90, command=self._browse_local
        )
        browse_btn.pack(side="left")

        note = ctk.CTkLabel(
            self.local_frame,
            text="Select the root folder that contains server.properties / behavior_packs / resource_packs.",
            text_color="gray",
            font=ctk.CTkFont(size=11),
            wraplength=620,
            justify="left",
        )
        note.pack(anchor="w")

    def _create_sftp_widgets(self) -> None:
        """Create SFTP connection fields."""
        desc = ctk.CTkLabel(
            self.sftp_frame,
            text="SFTP Connection",
            font=ctk.CTkFont(weight="bold"),
        )
        desc.grid(row=0, column=0, columnspan=3, sticky="w", pady=(6, 8))

        self.sftp_frame.grid_columnconfigure(1, weight=1)

        def add_row(row: int, label_text: str, entry_attr: str, default: str = "", show: str = None):
            label = ctk.CTkLabel(self.sftp_frame, text=label_text, anchor="w")
            label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            entry = ctk.CTkEntry(self.sftp_frame, show=show) if show else ctk.CTkEntry(self.sftp_frame)
            entry.grid(row=row, column=1, sticky="ew", pady=4)
            if default:
                entry.insert(0, default)
            setattr(self, entry_attr, entry)

        add_row(1, "Host:", "sftp_host_entry", config.sftp_host)
        add_row(2, "Port:", "sftp_port_entry", str(config.sftp_port or 22))
        add_row(3, "Username:", "sftp_username_entry", config.sftp_username)
        add_row(4, "Password:", "sftp_password_entry", config.sftp_password, show="*")
        add_row(5, "Private Key (optional):", "sftp_key_file_entry", config.sftp_key_file)
        add_row(6, "Remote Server Path:", "sftp_remote_path_entry", config.sftp_remote_path or "/")
        add_row(
            7,
            "Status Host (optional):",
            "sftp_status_host_entry",
            config.sftp_status_host,
        )

        key_browse_btn = ctk.CTkButton(
            self.sftp_frame,
            text="Browse Key",
            width=90,
            command=self._browse_key_file,
        )
        key_browse_btn.grid(row=5, column=2, padx=(8, 0), pady=4)

        note = ctk.CTkLabel(
            self.sftp_frame,
            text="Status Host is used for Bedrock ping/version checks when it differs from the SFTP host.",
            text_color="gray",
            font=ctk.CTkFont(size=11),
            wraplength=620,
            justify="left",
        )
        note.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _on_mode_change(self, mode: str) -> None:
        """Show the matching connection form for the selected mode."""
        self.local_frame.pack_forget()
        self.sftp_frame.pack_forget()

        if mode == "sftp":
            self.sftp_frame.pack(fill="both", expand=True)
        else:
            self.local_frame.pack(fill="both", expand=True)

    def _browse_local(self) -> None:
        """Open folder browser for local server path."""
        folder = filedialog.askdirectory(
            title="Select Bedrock Server Folder",
            initialdir=self.path_entry.get() or Path.home(),
        )
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _browse_key_file(self) -> None:
        """Open file browser for an SSH private key file."""
        key_file = filedialog.askopenfilename(
            title="Select SSH Private Key",
            initialdir=Path.home(),
        )
        if key_file:
            self.sftp_key_file_entry.delete(0, "end")
            self.sftp_key_file_entry.insert(0, key_file)

    def _save(self) -> None:
        """Validate and persist the selected connection settings."""
        mode = self.connection_mode_var.get().strip().lower()

        if mode == "sftp":
            host = self.sftp_host_entry.get().strip()
            port_text = self.sftp_port_entry.get().strip() or "22"
            username = self.sftp_username_entry.get().strip()
            password = self.sftp_password_entry.get()
            key_file = self.sftp_key_file_entry.get().strip()
            remote_path = self.sftp_remote_path_entry.get().strip()
            status_host = self.sftp_status_host_entry.get().strip()

            try:
                port = int(port_text)
            except ValueError:
                messagebox.showerror("Error", "SFTP port must be a number.")
                return

            is_valid, message = server_fs.validate_sftp_connection(
                host=host,
                port=port,
                username=username,
                password=password,
                key_file=key_file,
                remote_path=remote_path,
                timeout=config.sftp_timeout,
            )
            if not is_valid:
                messagebox.showerror("SFTP Connection Failed", message)
                return

            config.connection_type = "sftp"
            config.sftp_host = host
            config.sftp_port = port
            config.sftp_username = username
            config.sftp_password = password
            config.sftp_key_file = key_file
            config.sftp_remote_path = remote_path
            config.sftp_status_host = status_host
            self.result = True
            self.destroy()
            return

        path = self.path_entry.get().strip()
        if not path:
            messagebox.showerror("Error", "Please select a server folder.")
            return

        server_path = Path(path)
        if not server_path.exists():
            messagebox.showerror("Error", "The selected folder does not exist.")
            return
        if not server_path.is_dir():
            messagebox.showerror("Error", "Please select a folder, not a file.")
            return

        has_properties = (server_path / "server.properties").exists()
        has_behavior = (server_path / "behavior_packs").exists()
        has_resource = (server_path / "resource_packs").exists()
        if not (has_properties or has_behavior or has_resource):
            result = messagebox.askyesno(
                "Warning",
                "This folder doesn't appear to be a Bedrock server directory.\n"
                "Continue anyway?",
            )
            if not result:
                return

        config.connection_type = "local"
        config.server_path = path
        self.result = True
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """Settings dialog."""

    def __init__(self, parent, addon_manager: AddonManager):
        super().__init__(parent)

        self.addon_manager = addon_manager
        self.changed = False
        self._connection_changed = False

        self.title("Settings")
        self.geometry("450x580")
        self.resizable(False, False)

        # Set window icon
        set_dialog_icon(self)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 450) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 580) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create settings widgets."""
        # Server connection
        connection_label = ctk.CTkLabel(
            self, text="Server Connection:", font=ctk.CTkFont(weight="bold")
        )
        connection_label.pack(anchor="w", padx=20, pady=(20, 5))

        connection_frame = ctk.CTkFrame(self, fg_color="transparent")
        connection_frame.pack(fill="x", padx=20)
        connection_frame.grid_columnconfigure(0, weight=1)

        self.connection_summary = ctk.CTkLabel(
            connection_frame,
            text="",
            text_color="gray",
            anchor="w",
            justify="left",
            wraplength=280,
        )
        self.connection_summary.grid(row=0, column=0, sticky="w")

        configure_btn = ctk.CTkButton(
            connection_frame,
            text="Configure...",
            width=110,
            command=self._configure_connection,
        )
        configure_btn.grid(row=0, column=1, padx=(10, 0), sticky="e")
        self._refresh_connection_summary()

        # Theme
        theme_label = ctk.CTkLabel(self, text="Theme:", font=ctk.CTkFont(weight="bold"))
        theme_label.pack(anchor="w", padx=20, pady=(20, 5))

        self.theme_var = ctk.StringVar(value=config.theme)
        theme_frame = ctk.CTkFrame(self, fg_color="transparent")
        theme_frame.pack(anchor="w", padx=20)

        dark_radio = ctk.CTkRadioButton(
            theme_frame, text="Dark", variable=self.theme_var, value="dark"
        )
        dark_radio.pack(side="left", padx=(0, 20))

        light_radio = ctk.CTkRadioButton(
            theme_frame, text="Light", variable=self.theme_var, value="light"
        )
        light_radio.pack(side="left")

        # Import settings section
        import_label = ctk.CTkLabel(
            self, text="Import Settings:", font=ctk.CTkFont(weight="bold")
        )
        import_label.pack(anchor="w", padx=20, pady=(20, 5))

        self.auto_enable_var = ctk.BooleanVar(value=config.auto_enable_after_import)
        auto_enable_checkbox = ctk.CTkCheckBox(
            self,
            text="Automatically enable addons after import",
            variable=self.auto_enable_var,
        )
        auto_enable_checkbox.pack(anchor="w", padx=20)

        # Updates section
        updates_label = ctk.CTkLabel(
            self, text="Updates:", font=ctk.CTkFont(weight="bold")
        )
        updates_label.pack(anchor="w", padx=20, pady=(20, 5))

        self.check_updates_var = ctk.BooleanVar(value=config.check_for_updates)
        check_updates_checkbox = ctk.CTkCheckBox(
            self,
            text="Check for updates on startup",
            variable=self.check_updates_var,
        )
        check_updates_checkbox.pack(anchor="w", padx=20)

        self.check_now_btn = ctk.CTkButton(
            self,
            text="Check for Updates Now",
            width=200,
            command=self._check_for_updates,
        )
        self.check_now_btn.pack(anchor="w", padx=20, pady=(5, 0))

        # Default packs section
        default_label = ctk.CTkLabel(
            self, text="Default Packs:", font=ctk.CTkFont(weight="bold")
        )
        default_label.pack(anchor="w", padx=20, pady=(20, 5))

        self.default_info_label = ctk.CTkLabel(
            self,
            text=f"{len(config.default_pack_uuids)} packs marked as default",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self.default_info_label.pack(anchor="w", padx=20)

        manage_btn = ctk.CTkButton(
            self,
            text="Manage Default Addons",
            width=200,
            command=self._manage_default_addons,
        )
        manage_btn.pack(anchor="w", padx=20, pady=(5, 0))

        reset_btn = ctk.CTkButton(
            self,
            text="Reset Default Packs Detection",
            width=200,
            fg_color="gray",
            command=self._reset_default_packs,
        )
        reset_btn.pack(anchor="w", padx=20, pady=(5, 0))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20, side="bottom")

        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", width=100, fg_color="gray", command=self.destroy
        )
        cancel_btn.pack(side="right", padx=5)

        save_btn = ctk.CTkButton(btn_frame, text="Save", width=100, command=self._save)
        save_btn.pack(side="right", padx=5)

    def _refresh_connection_summary(self) -> None:
        """Update the server connection summary text."""
        mode_text = "SFTP" if config.connection_type == "sftp" else "Local"
        location = config.get_server_display_path() or "Not configured"
        self.connection_summary.configure(text=f"Mode: {mode_text}\n{location}")

    def _configure_connection(self) -> None:
        """Open the server connection configuration dialog."""
        before = (
            config.connection_type,
            config.server_path,
            config.sftp_host,
            config.sftp_port,
            config.sftp_username,
            config.sftp_remote_path,
            config.sftp_status_host,
        )
        dialog = ServerPathDialog(self)
        self.wait_window(dialog)
        if dialog.result:
            after = (
                config.connection_type,
                config.server_path,
                config.sftp_host,
                config.sftp_port,
                config.sftp_username,
                config.sftp_remote_path,
                config.sftp_status_host,
            )
            if after != before:
                self._connection_changed = True
                server_fs.close()
                self._refresh_connection_summary()

    def _save(self) -> None:
        """Save settings."""
        new_theme = self.theme_var.get()
        new_auto_enable = self.auto_enable_var.get()
        new_check_updates = self.check_updates_var.get()

        if self._connection_changed:
            self.changed = True

        if new_theme != config.theme:
            config.theme = new_theme
            ctk.set_appearance_mode(new_theme)

        if new_auto_enable != config.auto_enable_after_import:
            config.auto_enable_after_import = new_auto_enable

        if new_check_updates != config.check_for_updates:
            config.check_for_updates = new_check_updates

        self.destroy()

    def _refresh_default_info(self) -> None:
        """Refresh default-addon count text."""
        self.default_info_label.configure(
            text=f"{len(config.default_pack_uuids)} packs marked as default"
        )

    def _manage_default_addons(self) -> None:
        """Open dialog to unmark currently default addons."""
        dialog = ManageDefaultAddonsDialog(self, self.addon_manager)
        self.wait_window(dialog)

        if not dialog.changed:
            return

        Addon.set_default_pack_uuids(set(config.default_pack_uuids))
        self._refresh_default_info()
        self.changed = True

    def _reset_default_packs(self) -> None:
        """Reset the default packs detection."""
        result = messagebox.askyesno(
            "Reset Default Packs",
            "This will clear the current default packs list and show the\n"
            "detection dialog again on next launch.\n\n"
            "Continue?",
        )
        if result:
            config.clear_default_pack_uuids()
            Addon.set_default_pack_uuids(set(config.default_pack_uuids))
            self._refresh_default_info()
            self.changed = True
            messagebox.showinfo(
                "Reset Complete",
                "Default packs detection has been reset.\n"
                "The detection dialog will appear when you restart the app.",
            )

    def _check_for_updates(self) -> None:
        """Manually check for updates."""
        self.check_now_btn.configure(text="Checking...", state="disabled")
        self.update()

        update_info = check_for_updates()

        self.check_now_btn.configure(text="Check for Updates Now", state="normal")

        if update_info is None:
            messagebox.showerror(
                "Update Check Failed",
                "Could not check for updates.\n"
                "Please check your internet connection.",
            )
        elif update_info.is_update_available:
            result = messagebox.askyesno(
                "Update Available",
                f"A new version is available!\n\n"
                f"Current version: {update_info.current_version}\n"
                f"Latest version: {update_info.latest_version}\n\n"
                "Would you like to open the download page?",
            )
            if result:
                open_release_url(update_info.release_url)
        else:
            messagebox.showinfo(
                "Up to Date",
                f"You are running the latest version ({update_info.current_version}).",
            )


class ManageDefaultAddonsDialog(ctk.CTkToplevel):
    """Dialog for managing currently marked default addons."""

    def __init__(self, parent, addon_manager: AddonManager):
        super().__init__(parent)

        self.addon_manager = addon_manager
        self.changed = False
        self._default_vars: List[tuple] = []
        self._installed_by_uuid: Dict[str, Addon] = {}
        self._build_installed_lookup()

        self.title("Manage Default Addons")
        self.geometry("620x460")
        self.resizable(False, False)

        set_dialog_icon(self)
        self.transient(parent)
        self.grab_set()

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 620) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 460) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _build_installed_lookup(self) -> None:
        """Build installed addon lookup by UUID."""
        all_addons = (
            self.addon_manager.get_behavior_packs()
            + self.addon_manager.get_resource_packs()
        )
        for addon in all_addons:
            self._installed_by_uuid[addon.uuid] = addon

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        title = ctk.CTkLabel(
            self,
            text="Default Addons",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title.pack(pady=(14, 6))

        help_text = ctk.CTkLabel(
            self,
            text="Uncheck any addon you no longer want marked as default.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        help_text.pack(pady=(0, 10))

        scroll = ctk.CTkScrollableFrame(self)
        scroll.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        default_uuids = list(config.default_pack_uuids)
        if not default_uuids:
            empty = ctk.CTkLabel(
                scroll,
                text="No addons are currently marked as default.",
                text_color="gray",
            )
            empty.pack(pady=20)
        else:
            for addon_uuid in default_uuids:
                addon = self._installed_by_uuid.get(addon_uuid)
                if addon:
                    pack_kind = (
                        "Behavior" if addon.pack_type == PackType.BEHAVIOR else "Resource"
                    )
                    title_text = f"{addon.name} ({pack_kind})"
                else:
                    title_text = "Unknown Addon"

                row = ctk.CTkFrame(scroll)
                row.pack(fill="x", padx=4, pady=4)

                keep_var = ctk.BooleanVar(value=True)
                self._default_vars.append((addon_uuid, keep_var))

                check = ctk.CTkCheckBox(
                    row,
                    text=title_text,
                    variable=keep_var,
                )
                check.pack(anchor="w", padx=10, pady=(8, 2))

                uuid_label = ctk.CTkLabel(
                    row,
                    text=addon_uuid,
                    font=ctk.CTkFont(size=10),
                    text_color="gray",
                )
                uuid_label.pack(anchor="w", padx=32, pady=(0, 8))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=14, pady=(0, 14))

        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", width=100, fg_color="gray", command=self.destroy
        )
        cancel_btn.pack(side="right", padx=5)

        save_btn = ctk.CTkButton(
            btn_frame, text="Save", width=100, command=self._save_changes
        )
        save_btn.pack(side="right", padx=5)

    def _save_changes(self) -> None:
        """Persist selected default-addon entries."""
        original = list(config.default_pack_uuids)
        updated = [uuid for uuid, keep_var in self._default_vars if keep_var.get()]

        if updated != original:
            config.default_pack_uuids = updated
            config.default_packs_detected = True
            self.changed = True

        self.destroy()


class DefaultPacksDialog(ctk.CTkToplevel):
    """Dialog for detecting default packs on first launch."""

    def __init__(self, parent, addon_manager):
        super().__init__(parent)

        self.addon_manager = addon_manager

        self.title("Default Packs Detection")
        self.geometry("500x250")
        self.resizable(False, False)

        # Set window icon
        set_dialog_icon(self)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on screen (more reliable than centering on parent at startup)
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        width = 500
        height = 250
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        # Title
        title_label = ctk.CTkLabel(
            self,
            text="First-Time Setup",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title_label.pack(pady=(20, 10))

        # Question
        question_label = ctk.CTkLabel(
            self,
            text="Have you already installed any custom resource or behavior packs\n"
            "on this server?",
            font=ctk.CTkFont(size=13),
            justify="center",
        )
        question_label.pack(pady=(10, 5))

        # Explanation
        explanation_label = ctk.CTkLabel(
            self,
            text="If you select 'No', all currently installed packs will be marked\n"
            "as default packs and hidden from the main list.",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            justify="center",
        )
        explanation_label.pack(pady=(5, 20))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=40, pady=20)

        # "No" button - mark all current packs as default
        no_btn = ctk.CTkButton(
            btn_frame,
            text="No, mark all as default",
            width=180,
            command=self._mark_all_as_default,
        )
        no_btn.pack(side="left", padx=10)

        # "Yes" button - don't mark any as default
        yes_btn = ctk.CTkButton(
            btn_frame,
            text="Yes, I have custom packs",
            width=180,
            fg_color="gray",
            command=self._skip_detection,
        )
        yes_btn.pack(side="right", padx=10)

    def _mark_all_as_default(self) -> None:
        """Mark all currently installed packs as default."""
        # Get all current pack UUIDs
        behavior_packs = self.addon_manager.get_behavior_packs()
        resource_packs = self.addon_manager.get_resource_packs()

        all_uuids = []
        for pack in behavior_packs:
            all_uuids.append(pack.uuid)
        for pack in resource_packs:
            all_uuids.append(pack.uuid)

        # Save to config
        config.default_pack_uuids = all_uuids
        config.default_packs_detected = True

        self.destroy()

    def _skip_detection(self) -> None:
        """Skip detection - user has custom packs already."""
        # Don't mark any packs as default, just mark detection as done
        config.default_packs_detected = True
        self.destroy()


class UpdateDialog(ctk.CTkToplevel):
    """Dialog for showing update availability."""

    def __init__(self, parent, update_info: UpdateInfo):
        super().__init__(parent)

        self.update_info = update_info

        self.title("Update Available")
        self.geometry("450x250")
        self.resizable(False, False)

        # Set window icon
        set_dialog_icon(self)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 450) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 250) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        # Title
        title_label = ctk.CTkLabel(
            self,
            text="Update Available!",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title_label.pack(pady=(20, 10))

        # Version info
        version_text = (
            f"A new version of MCBManager is available.\n\n"
            f"Current version: {self.update_info.current_version}\n"
            f"Latest version: {self.update_info.latest_version}"
        )
        version_label = ctk.CTkLabel(
            self,
            text=version_text,
            font=ctk.CTkFont(size=13),
            justify="center",
        )
        version_label.pack(pady=(10, 20))

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=40, pady=20)

        # Download button
        download_btn = ctk.CTkButton(
            btn_frame,
            text="Download Update",
            width=150,
            command=self._open_download,
        )
        download_btn.pack(side="left", padx=10)

        # Later button
        later_btn = ctk.CTkButton(
            btn_frame,
            text="Remind Me Later",
            width=150,
            fg_color="gray",
            command=self.destroy,
        )
        later_btn.pack(side="right", padx=10)

    def _open_download(self) -> None:
        """Open the download page and close dialog."""
        open_release_url(self.update_info.release_url)
        self.destroy()
