"""Addon panel UI component."""

from pathlib import Path
from tkinter import messagebox
from typing import Callable, Dict, List, Optional

import customtkinter as ctk
from PIL import Image

from ..addon import Addon, AddonManager, PackType
from ..server import ServerMonitor
from .import_dialog import ImportDialog

# Global image cache to avoid reloading/resizing images
_image_cache: Dict[str, ctk.CTkImage] = {}


def get_cached_icon(icon_path: Path, size: tuple = (40, 40)) -> Optional[ctk.CTkImage]:
    """Get a cached icon image, loading it if necessary."""
    cache_key = f"{icon_path}_{size[0]}x{size[1]}"
    if cache_key not in _image_cache:
        try:
            img = Image.open(icon_path)
            img = img.resize(size, Image.Resampling.LANCZOS)
            _image_cache[cache_key] = ctk.CTkImage(img, size=size)
        except Exception:
            return None
    return _image_cache.get(cache_key)


class AddonPanel(ctk.CTkFrame):
    """Panel for managing addons."""

    def __init__(
        self,
        parent,
        addon_manager: AddonManager,
        server_monitor: ServerMonitor,
        on_refresh: Optional[Callable] = None,
    ):
        super().__init__(parent)

        self.addon_manager = addon_manager
        self.server_monitor = server_monitor
        self.on_refresh = on_refresh
        self.selected_world: Optional[str] = None
        self.search_query: str = ""
        self.show_default_packs: bool = False
        self._behavior_packs: List[Addon] = []
        self._resource_packs: List[Addon] = []
        self._search_debounce_id: Optional[str] = None

        self._create_widgets()

    def _is_server_running(self) -> bool:
        """Check if the server is currently running."""
        self.server_monitor.check_status()
        return self.server_monitor.is_running

    def _show_server_running_warning(self) -> None:
        """Show a warning that the server must be stopped."""
        messagebox.showwarning(
            "Server Running",
            "Cannot modify addons while the server is running.\n\n"
            "Please stop the server first, then try again.",
        )

    def _create_widgets(self) -> None:
        """Create panel widgets."""
        # Configure grid
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # Header with title and buttons
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))
        header_frame.grid_columnconfigure(1, weight=1)

        title_label = ctk.CTkLabel(
            header_frame,
            text="Installed Addons",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title_label.grid(row=0, column=0, sticky="w")

        # Import button
        self.import_btn = ctk.CTkButton(
            header_frame,
            text="Import Addon",
            width=120,
            command=self._show_import_dialog,
        )
        self.import_btn.grid(row=0, column=2, padx=(5, 0))

        # Refresh button
        self.refresh_btn = ctk.CTkButton(
            header_frame,
            text="Refresh",
            width=80,
            fg_color="gray",
            command=self._refresh,
        )
        self.refresh_btn.grid(row=0, column=3, padx=(5, 0))

        # World selector
        world_frame = ctk.CTkFrame(self, fg_color="transparent")
        world_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        world_label = ctk.CTkLabel(
            world_frame, text="World:", font=ctk.CTkFont(weight="bold")
        )
        world_label.pack(side="left", padx=(0, 10))

        self.world_selector = ctk.CTkComboBox(
            world_frame,
            values=["No worlds found"],
            width=250,
            command=self._on_world_change,
        )
        self.world_selector.pack(side="left")

        # Search bar
        search_frame = ctk.CTkFrame(self, fg_color="transparent")
        search_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        search_label = ctk.CTkLabel(
            search_frame, text="Search:", font=ctk.CTkFont(weight="bold")
        )
        search_label.pack(side="left", padx=(0, 10))

        self.search_entry = ctk.CTkEntry(
            search_frame,
            placeholder_text="Filter addons by name...",
            width=300,
        )
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self._on_search_change)

        clear_btn = ctk.CTkButton(
            search_frame,
            text="Clear",
            width=60,
            fg_color="gray",
            command=self._clear_search,
        )
        clear_btn.pack(side="left", padx=(10, 0))

        # Show default packs checkbox
        self.show_default_var = ctk.BooleanVar(value=False)
        self.show_default_checkbox = ctk.CTkCheckBox(
            search_frame,
            text="Show default packs",
            variable=self.show_default_var,
            command=self._on_show_default_toggle,
            width=20,
        )
        self.show_default_checkbox.pack(side="right", padx=(10, 0))

        # Tabview for Behavior/Resource packs
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=3, column=0, sticky="nsew", padx=10, pady=(5, 10))

        self.behavior_tab = self.tabview.add("Behavior Packs")
        self.resource_tab = self.tabview.add("Resource Packs")

        # Configure tabs
        self.behavior_tab.grid_columnconfigure(0, weight=1)
        self.behavior_tab.grid_rowconfigure(0, weight=1)
        self.resource_tab.grid_columnconfigure(0, weight=1)
        self.resource_tab.grid_rowconfigure(0, weight=1)

        # Scrollable frames for pack lists
        self.behavior_scroll = ctk.CTkScrollableFrame(self.behavior_tab)
        self.behavior_scroll.grid(row=0, column=0, sticky="nsew")
        self.behavior_scroll.grid_columnconfigure(0, weight=1)

        self.resource_scroll = ctk.CTkScrollableFrame(self.resource_tab)
        self.resource_scroll.grid(row=0, column=0, sticky="nsew")
        self.resource_scroll.grid_columnconfigure(0, weight=1)

        # Button frames for each tab (to hold Enable All and Delete All buttons)
        behavior_btn_frame = ctk.CTkFrame(self.behavior_tab, fg_color="transparent")
        self.behavior_tab.grid_rowconfigure(1, weight=0)
        behavior_btn_frame.grid(row=1, column=0, pady=(5, 5), padx=10, sticky="e")

        self.behavior_enable_all_btn = ctk.CTkButton(
            behavior_btn_frame,
            text="Enable All Custom Packs",
            fg_color="#4CAF50",
            hover_color="#388E3C",
            command=self._enable_all_behavior_packs,
        )
        self.behavior_enable_all_btn.pack(side="left", padx=(0, 10))

        self.behavior_delete_all_btn = ctk.CTkButton(
            behavior_btn_frame,
            text="Delete All Custom Packs",
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            command=self._delete_all_behavior_packs,
        )
        self.behavior_delete_all_btn.pack(side="left")

        resource_btn_frame = ctk.CTkFrame(self.resource_tab, fg_color="transparent")
        self.resource_tab.grid_rowconfigure(1, weight=0)
        resource_btn_frame.grid(row=1, column=0, pady=(5, 5), padx=10, sticky="e")

        self.resource_enable_all_btn = ctk.CTkButton(
            resource_btn_frame,
            text="Enable All Custom Packs",
            fg_color="#4CAF50",
            hover_color="#388E3C",
            command=self._enable_all_resource_packs,
        )
        self.resource_enable_all_btn.pack(side="left", padx=(0, 10))

        self.resource_delete_all_btn = ctk.CTkButton(
            resource_btn_frame,
            text="Delete All Custom Packs",
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            command=self._delete_all_resource_packs,
        )
        self.resource_delete_all_btn.pack(side="left")

        # Empty state messages
        self.behavior_empty_msg = "No behavior packs installed"
        self.resource_empty_msg = "No resource packs installed"

    def refresh(self) -> None:
        """Refresh the addon lists."""
        # Update world selector
        worlds = self.addon_manager.get_worlds()
        if worlds:
            self.world_selector.configure(values=worlds)
            if not self.selected_world or self.selected_world not in worlds:
                self.selected_world = worlds[0]
                self.world_selector.set(self.selected_world)
        else:
            self.world_selector.configure(values=["No worlds found"])
            self.world_selector.set("No worlds found")
            self.selected_world = None

        # Store all packs
        self._behavior_packs = self.addon_manager.get_behavior_packs()
        self._resource_packs = self.addon_manager.get_resource_packs()

        # Update pack lists with filtering
        self._update_filtered_lists()

    def _filter_packs(self, packs: List[Addon]) -> List[Addon]:
        """Filter packs based on search query and default pack visibility."""
        filtered = packs

        # Filter out default packs unless show_default_packs is enabled
        if not self.show_default_packs:
            filtered = [pack for pack in filtered if not pack.is_default]

        # Apply search filter
        if self.search_query:
            query = self.search_query.lower()
            filtered = [
                pack
                for pack in filtered
                if query in pack.name.lower()
                or (pack.description and query in pack.description.lower())
            ]

        return filtered

    def _update_filtered_lists(self) -> None:
        """Update pack lists with current search filter."""
        filtered_behavior = self._filter_packs(self._behavior_packs)
        filtered_resource = self._filter_packs(self._resource_packs)

        self._update_pack_list(
            self.behavior_scroll,
            self.behavior_empty_msg,
            filtered_behavior,
        )
        self._update_pack_list(
            self.resource_scroll,
            self.resource_empty_msg,
            filtered_resource,
        )

    def _on_search_change(self, event=None) -> None:
        """Handle search entry change with debouncing."""
        # Cancel any pending search
        if self._search_debounce_id is not None:
            self.after_cancel(self._search_debounce_id)

        # Schedule the actual search after a short delay
        self._search_debounce_id = self.after(150, self._execute_search)

    def _execute_search(self) -> None:
        """Execute the search after debounce delay."""
        self._search_debounce_id = None
        self.search_query = self.search_entry.get().strip()
        self._update_filtered_lists()

    def _clear_search(self) -> None:
        """Clear the search entry."""
        self.search_entry.delete(0, "end")
        self.search_query = ""
        self._update_filtered_lists()

    def _on_show_default_toggle(self) -> None:
        """Handle show default packs checkbox toggle."""
        self.show_default_packs = self.show_default_var.get()
        self._update_filtered_lists()

    def _update_pack_list(
        self,
        scroll_frame: ctk.CTkScrollableFrame,
        empty_message: str,
        packs: List[Addon],
    ) -> None:
        """Update a pack list frame."""
        # Clear existing widgets
        for widget in scroll_frame.winfo_children():
            widget.destroy()

        if not packs:
            # Show appropriate message based on whether filtering is active
            if self.search_query:
                message = "No addons match your search"
            elif not self.show_default_packs and (
                self._behavior_packs or self._resource_packs
            ):
                message = "No custom addons installed (default packs hidden)"
            else:
                message = empty_message

            empty_label = ctk.CTkLabel(scroll_frame, text=message, text_color="gray")
            empty_label.pack(pady=50)
            return

        # Create pack cards
        for i, pack in enumerate(packs):
            card = AddonCard(
                scroll_frame,
                pack,
                self.selected_world,
                self.addon_manager,
                on_toggle=self._on_addon_toggle,
                on_delete=self._on_addon_delete,
            )
            card.grid(row=i, column=0, sticky="ew", pady=5, padx=5)

    def _on_world_change(self, world: str) -> None:
        """Handle world selection change."""
        if world != "No worlds found":
            self.selected_world = world
            self.refresh()

    def _on_addon_toggle(self, addon: Addon, enabled: bool) -> None:
        """Handle addon enable/disable toggle."""
        if self._is_server_running():
            self._show_server_running_warning()
            self.refresh()  # Reset the toggle switch
            return

        if not self.selected_world:
            messagebox.showwarning("Warning", "Please select a world first.")
            return

        if enabled:
            success = self.addon_manager.enable_addon(addon, self.selected_world)
            action = "enabled"
        else:
            success = self.addon_manager.disable_addon(addon, self.selected_world)
            action = "disabled"

        if success:
            self.refresh()
        else:
            messagebox.showerror("Error", f"Failed to {action[:-1]} addon.")

    def _on_addon_delete(self, addon: Addon) -> None:
        """Handle addon deletion."""
        if self._is_server_running():
            self._show_server_running_warning()
            return

        result = messagebox.askyesno(
            "Confirm Delete",
            f"Are you sure you want to delete '{addon.name}'?\n\n"
            "This will remove it from the server and cannot be undone.",
        )

        if result:
            # First disable from all worlds
            for world in self.addon_manager.get_worlds():
                if addon.pack_type == PackType.BEHAVIOR:
                    self.addon_manager.disable_addon(addon, world)
                else:
                    self.addon_manager.disable_addon(addon, world)

            # Delete the pack
            success = self.addon_manager.delete_addon(addon)

            if success:
                self.refresh()
                messagebox.showinfo("Success", f"'{addon.name}' has been deleted.")
            else:
                messagebox.showerror("Error", "Failed to delete addon.")

    def _show_import_dialog(self) -> None:
        """Show the import addon dialog."""
        if self._is_server_running():
            self._show_server_running_warning()
            return

        dialog = ImportDialog(self.winfo_toplevel())
        self.winfo_toplevel().wait_window(dialog)

        if dialog.imported:
            self._refresh()

    def _refresh(self) -> None:
        """Refresh data from parent."""
        if self.on_refresh:
            self.on_refresh()
        else:
            self.addon_manager.refresh()
            self.refresh()

    def _delete_all_behavior_packs(self) -> None:
        """Delete all custom (non-default) behavior packs."""
        self._delete_all_packs(PackType.BEHAVIOR)

    def _delete_all_resource_packs(self) -> None:
        """Delete all custom (non-default) resource packs."""
        self._delete_all_packs(PackType.RESOURCE)

    def _enable_all_behavior_packs(self) -> None:
        """Enable all custom (non-default) behavior packs."""
        self._enable_all_packs(PackType.BEHAVIOR)

    def _enable_all_resource_packs(self) -> None:
        """Enable all custom (non-default) resource packs."""
        self._enable_all_packs(PackType.RESOURCE)

    def _enable_all_packs(self, pack_type: PackType) -> None:
        """Enable all custom packs of the specified type."""
        if self._is_server_running():
            self._show_server_running_warning()
            return

        if not self.selected_world:
            messagebox.showwarning("Warning", "Please select a world first.")
            return

        # Get packs of the specified type, excluding defaults
        if pack_type == PackType.BEHAVIOR:
            all_packs = self._behavior_packs
            pack_type_name = "behavior"
        else:
            all_packs = self._resource_packs
            pack_type_name = "resource"

        # Filter to only custom (non-default) packs that are not already enabled
        custom_packs = [pack for pack in all_packs if not pack.is_default]
        disabled_packs = [
            pack
            for pack in custom_packs
            if not self.addon_manager.is_addon_enabled_in_world(
                pack, self.selected_world
            )
        ]

        if not custom_packs:
            messagebox.showinfo(
                "No Custom Packs",
                f"There are no custom {pack_type_name} packs to enable.",
            )
            return

        if not disabled_packs:
            messagebox.showinfo(
                "All Enabled",
                f"All custom {pack_type_name} packs are already enabled.",
            )
            return

        # Enable each pack
        enabled_count = 0
        failed_count = 0

        for pack in disabled_packs:
            if self.addon_manager.enable_addon(pack, self.selected_world):
                enabled_count += 1
            else:
                failed_count += 1

        # Refresh and show result
        self._refresh()

        if failed_count == 0:
            messagebox.showinfo(
                "Enable Complete",
                f"Successfully enabled {enabled_count} {pack_type_name} pack(s).",
            )
        else:
            messagebox.showwarning(
                "Enable Partially Complete",
                f"Enabled {enabled_count} pack(s), but {failed_count} failed to enable.",
            )

    def _delete_all_packs(self, pack_type: PackType) -> None:
        """Delete all custom packs of the specified type."""
        if self._is_server_running():
            self._show_server_running_warning()
            return

        # Get packs of the specified type, excluding defaults
        if pack_type == PackType.BEHAVIOR:
            all_packs = self._behavior_packs
            pack_type_name = "behavior"
        else:
            all_packs = self._resource_packs
            pack_type_name = "resource"

        # Filter to only custom (non-default) packs
        custom_packs = [pack for pack in all_packs if not pack.is_default]

        if not custom_packs:
            messagebox.showinfo(
                "No Custom Packs",
                f"There are no custom {pack_type_name} packs to delete.",
            )
            return

        # Confirm deletion
        result = messagebox.askyesno(
            "Confirm Delete All",
            f"Are you sure you want to delete all {len(custom_packs)} custom {pack_type_name} pack(s)?\n\n"
            "This will remove them from the server and cannot be undone.\n"
            "Default packs will not be deleted.",
        )

        if not result:
            return

        # Delete each pack
        deleted_count = 0
        failed_count = 0

        for pack in custom_packs:
            # Disable from all worlds first
            for world in self.addon_manager.get_worlds():
                self.addon_manager.disable_addon(pack, world)

            # Delete the pack
            if self.addon_manager.delete_addon(pack):
                deleted_count += 1
            else:
                failed_count += 1

        # Refresh and show result
        self._refresh()

        if failed_count == 0:
            messagebox.showinfo(
                "Delete Complete",
                f"Successfully deleted {deleted_count} {pack_type_name} pack(s).",
            )
        else:
            messagebox.showwarning(
                "Delete Partially Complete",
                f"Deleted {deleted_count} pack(s), but {failed_count} failed to delete.",
            )


class AddonCard(ctk.CTkFrame):
    """Card widget for displaying addon information."""

    def __init__(
        self,
        parent,
        addon: Addon,
        world: Optional[str],
        addon_manager: AddonManager,
        on_toggle: Optional[Callable] = None,
        on_delete: Optional[Callable] = None,
    ):
        super().__init__(parent)

        self.addon = addon
        self.world = world
        self.addon_manager = addon_manager
        self.on_toggle = on_toggle
        self.on_delete = on_delete

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create card widgets."""
        self.grid_columnconfigure(1, weight=1)

        # Icon placeholder
        icon_frame = ctk.CTkFrame(self, width=50, height=50, corner_radius=5)
        icon_frame.grid(row=0, column=0, rowspan=2, padx=10, pady=10)
        icon_frame.grid_propagate(False)

        # Try to load pack icon from cache
        if self.addon.icon_path and self.addon.icon_path.exists():
            photo = get_cached_icon(self.addon.icon_path)
            if photo:
                icon_label = ctk.CTkLabel(icon_frame, image=photo, text="")
                icon_label.place(relx=0.5, rely=0.5, anchor="center")
            else:
                self._show_default_icon(icon_frame)
        else:
            self._show_default_icon(icon_frame)

        # Pack name
        name_label = ctk.CTkLabel(
            self,
            text=self.addon.name,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        name_label.grid(row=0, column=1, sticky="sw", pady=(10, 0))

        # Pack info
        info_text = f"v{self.addon.version_string}"
        if self.addon.description:
            desc = self.addon.description[:60]
            if len(self.addon.description) > 60:
                desc += "..."
            info_text += f" - {desc}"

        info_label = ctk.CTkLabel(
            self,
            text=info_text,
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        )
        info_label.grid(row=1, column=1, sticky="nw", pady=(0, 10))

        # Controls frame
        controls_frame = ctk.CTkFrame(self, fg_color="transparent")
        controls_frame.grid(row=0, column=2, rowspan=2, padx=10, pady=10)

        # Enable/Disable switch
        is_enabled = False
        if self.world:
            is_enabled = self.addon_manager.is_addon_enabled_in_world(
                self.addon, self.world
            )

        self.switch_var = ctk.BooleanVar(value=is_enabled)
        self.switch = ctk.CTkSwitch(
            controls_frame,
            text="Enabled",
            variable=self.switch_var,
            command=self._on_switch_toggle,
            width=40,
        )
        self.switch.pack(side="left", padx=(0, 10))

        # Delete button
        self.delete_btn = ctk.CTkButton(
            controls_frame,
            text="Delete",
            width=60,
            height=28,
            fg_color="#D32F2F",
            hover_color="#B71C1C",
            command=self._on_delete_click,
        )
        self.delete_btn.pack(side="left")

    def _show_default_icon(self, frame: ctk.CTkFrame) -> None:
        """Show default pack icon."""
        pack_type_char = "B" if self.addon.pack_type == PackType.BEHAVIOR else "R"
        icon_label = ctk.CTkLabel(
            frame,
            text=pack_type_char,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="gray",
        )
        icon_label.place(relx=0.5, rely=0.5, anchor="center")

    def _on_switch_toggle(self) -> None:
        """Handle switch toggle."""
        if self.on_toggle:
            self.on_toggle(self.addon, self.switch_var.get())

    def _on_delete_click(self) -> None:
        """Handle delete button click."""
        if self.on_delete:
            self.on_delete(self.addon)
