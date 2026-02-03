"""Main application window."""

from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from ..addon import Addon, AddonManager
from ..config import config
from ..server import ServerMonitor, ServerProperties
from .addon_panel import AddonPanel
from .server_panel import ServerPanel


class MainWindow(ctk.CTk):
    """Main application window."""

    def __init__(self):
        super().__init__()

        # Configure window
        self.title("MCBManager")
        self.geometry(f"{config.window_width}x{config.window_height}")
        self.minsize(900, 600)

        # Set appearance
        ctk.set_appearance_mode(config.theme)
        ctk.set_default_color_theme("blue")

        # Initialize managers
        self.addon_manager = AddonManager()
        self.server_monitor = ServerMonitor()
        self.server_properties = ServerProperties()

        # Build UI
        self._create_layout()
        self._create_menu_bar()

        # Load data if configured
        if config.is_server_configured():
            # Load default pack UUIDs first, before refreshing addon lists
            Addon.set_default_pack_uuids(set(config.default_pack_uuids))
            self._load_server_data()
            # Check if we need to detect default packs (first launch)
            self._check_default_packs_detection()
        else:
            self._prompt_server_path()

        # Bind window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)

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
        self.grid_rowconfigure(1, weight=1)

    def _check_default_packs_detection(self) -> None:
        """Check if we need to detect default packs on first launch."""
        # Load existing default pack UUIDs into the Addon class
        Addon.set_default_pack_uuids(set(config.default_pack_uuids))

        # If default packs haven't been detected yet, ask the user
        if not config.default_packs_detected:
            self.after(100, self._show_default_packs_dialog)

    def _show_default_packs_dialog(self) -> None:
        """Show dialog asking about existing custom packs."""
        # Ensure addon manager has the latest pack list
        self.addon_manager.refresh()

        dialog = DefaultPacksDialog(self, self.addon_manager)
        self.wait_window(dialog)

        # Reload the default pack UUIDs into the Addon class
        Addon.set_default_pack_uuids(set(config.default_pack_uuids))

        # Refresh the addon panel to apply filtering
        self.addon_panel.refresh()

    def _prompt_server_path(self) -> None:
        """Prompt the user to select the server directory."""
        dialog = ServerPathDialog(self)
        self.wait_window(dialog)

        if dialog.result:
            config.server_path = dialog.result
            self._load_server_data()
            # Check for default packs after server is configured
            self._check_default_packs_detection()

    def _load_server_data(self) -> None:
        """Load server data and refresh UI."""
        self.server_properties.load()
        self.addon_manager.refresh()
        self.server_panel.refresh()
        self.addon_panel.refresh()

    def _refresh_data(self) -> None:
        """Refresh all data."""
        self._load_server_data()

    def _show_settings(self) -> None:
        """Show settings dialog."""
        dialog = SettingsDialog(self)
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
    """Dialog for selecting server path."""

    def __init__(self, parent):
        super().__init__(parent)

        self.result: Optional[str] = None

        self.title("Configure Server Path")
        self.geometry("500x200")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 200) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        # Instructions
        label = ctk.CTkLabel(
            self,
            text="Select your Minecraft Bedrock Dedicated Server folder:",
            font=ctk.CTkFont(size=14),
        )
        label.pack(pady=(20, 10))

        # Path entry frame
        path_frame = ctk.CTkFrame(self)
        path_frame.pack(fill="x", padx=20, pady=10)

        self.path_entry = ctk.CTkEntry(path_frame, width=350)
        self.path_entry.pack(side="left", padx=(10, 5), pady=10)

        if config.server_path:
            self.path_entry.insert(0, config.server_path)

        browse_btn = ctk.CTkButton(
            path_frame, text="Browse", width=80, command=self._browse
        )
        browse_btn.pack(side="left", padx=(5, 10), pady=10)

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=20, pady=20)

        cancel_btn = ctk.CTkButton(
            btn_frame, text="Cancel", width=100, fg_color="gray", command=self.destroy
        )
        cancel_btn.pack(side="right", padx=5)

        save_btn = ctk.CTkButton(btn_frame, text="Save", width=100, command=self._save)
        save_btn.pack(side="right", padx=5)

    def _browse(self) -> None:
        """Open folder browser."""
        folder = filedialog.askdirectory(
            title="Select Bedrock Server Folder",
            initialdir=self.path_entry.get() or Path.home(),
        )
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _save(self) -> None:
        """Save the selected path."""
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

        # Check for expected server files
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

        self.result = path
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    """Settings dialog."""

    def __init__(self, parent):
        super().__init__(parent)

        self.changed = False

        self.title("Settings")
        self.geometry("450x380")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 450) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 300) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create settings widgets."""
        # Server path
        path_label = ctk.CTkLabel(
            self, text="Server Path:", font=ctk.CTkFont(weight="bold")
        )
        path_label.pack(anchor="w", padx=20, pady=(20, 5))

        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.pack(fill="x", padx=20)

        self.path_entry = ctk.CTkEntry(path_frame, width=300)
        self.path_entry.pack(side="left", padx=(0, 5))
        self.path_entry.insert(0, config.server_path)

        browse_btn = ctk.CTkButton(
            path_frame, text="Browse", width=80, command=self._browse
        )
        browse_btn.pack(side="left")

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

        # Default packs section
        default_label = ctk.CTkLabel(
            self, text="Default Packs:", font=ctk.CTkFont(weight="bold")
        )
        default_label.pack(anchor="w", padx=20, pady=(20, 5))

        default_info = ctk.CTkLabel(
            self,
            text=f"{len(config.default_pack_uuids)} packs marked as default",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        default_info.pack(anchor="w", padx=20)

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

    def _browse(self) -> None:
        """Open folder browser."""
        folder = filedialog.askdirectory(
            title="Select Bedrock Server Folder",
            initialdir=self.path_entry.get() or Path.home(),
        )
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)

    def _save(self) -> None:
        """Save settings."""
        new_path = self.path_entry.get().strip()
        new_theme = self.theme_var.get()

        if new_path != config.server_path:
            if new_path:
                path = Path(new_path)
                if not path.exists() or not path.is_dir():
                    messagebox.showerror("Error", "Invalid server path.")
                    return
            config.server_path = new_path
            self.changed = True

        if new_theme != config.theme:
            config.theme = new_theme
            ctk.set_appearance_mode(new_theme)

        self.destroy()

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
            messagebox.showinfo(
                "Reset Complete",
                "Default packs detection has been reset.\n"
                "The detection dialog will appear when you restart the app.",
            )


class DefaultPacksDialog(ctk.CTkToplevel):
    """Dialog for detecting default packs on first launch."""

    def __init__(self, parent, addon_manager):
        super().__init__(parent)

        self.addon_manager = addon_manager

        self.title("Default Packs Detection")
        self.geometry("500x250")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 500) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 250) // 2
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
