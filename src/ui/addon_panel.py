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

        # Collapse state for sections (per tab)
        self._behavior_missing_deps_collapsed: bool = False
        self._behavior_enabled_collapsed: bool = False
        self._behavior_disabled_collapsed: bool = False
        self._resource_missing_deps_collapsed: bool = False
        self._resource_enabled_collapsed: bool = False
        self._resource_disabled_collapsed: bool = False

        # Cache for installed UUIDs (refreshed when pack lists change)
        self._installed_uuids: set = set()

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
        header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(2, 5))
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
        # Update installed UUIDs cache
        all_addons = self._behavior_packs + self._resource_packs
        self._installed_uuids = {addon.uuid for addon in all_addons}

        filtered_behavior = self._filter_packs(self._behavior_packs)
        filtered_resource = self._filter_packs(self._resource_packs)

        self._update_pack_list(
            self.behavior_scroll,
            self.behavior_empty_msg,
            filtered_behavior,
            PackType.BEHAVIOR,
        )
        self._update_pack_list(
            self.resource_scroll,
            self.resource_empty_msg,
            filtered_resource,
            PackType.RESOURCE,
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
        pack_type: PackType,
    ) -> None:
        """Update a pack list frame."""
        # Temporarily disable scrolling updates for smoother rebuilding
        scroll_frame.configure(width=scroll_frame.winfo_width())

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

        # Separate packs into categories: missing deps, enabled, disabled
        missing_deps_packs = []
        enabled_packs = []
        disabled_packs = []

        for pack in packs:
            # Check if pack has missing dependencies
            if pack.has_missing_dependencies(self._installed_uuids):
                missing_deps_packs.append(pack)
            elif self.selected_world and self.addon_manager.is_addon_enabled_in_world(
                pack, self.selected_world
            ):
                position = self.addon_manager.get_addon_position(
                    pack, self.selected_world
                )
                enabled_packs.append((pack, position if position is not None else 999))
            else:
                disabled_packs.append(pack)

        # Sort enabled packs by position (load order)
        enabled_packs.sort(key=lambda x: x[1])
        total_missing_deps = len(missing_deps_packs)
        total_enabled = len(enabled_packs)
        total_disabled = len(disabled_packs)

        # Get collapse states for this pack type
        if pack_type == PackType.BEHAVIOR:
            missing_deps_collapsed = self._behavior_missing_deps_collapsed
            enabled_collapsed = self._behavior_enabled_collapsed
            disabled_collapsed = self._behavior_disabled_collapsed
        else:
            missing_deps_collapsed = self._resource_missing_deps_collapsed
            enabled_collapsed = self._resource_enabled_collapsed
            disabled_collapsed = self._resource_disabled_collapsed

        row = 0

        # Summary header showing total counts
        summary_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        summary_frame.grid(row=row, column=0, sticky="ew", pady=(5, 10), padx=5)

        summary_parts = [f"Total: {len(packs)}", f"Enabled: {total_enabled}", f"Disabled: {total_disabled}"]
        if total_missing_deps > 0:
            summary_parts.append(f"Missing Deps: {total_missing_deps}")

        summary_label = ctk.CTkLabel(
            summary_frame,
            text="  |  ".join(summary_parts),
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        summary_label.pack(side="left")
        row += 1

        # Section for packs with missing dependencies (at top, highlighted)
        if missing_deps_packs:
            missing_header = self._create_collapsible_header(
                scroll_frame,
                f"Missing Dependencies ({total_missing_deps})",
                missing_deps_collapsed,
                lambda: self._toggle_section(pack_type, "missing_deps"),
                header_color="#D32F2F",
            )
            missing_header.grid(row=row, column=0, sticky="ew", pady=(5, 5), padx=5)
            row += 1

            if not missing_deps_collapsed:
                for pack in sorted(missing_deps_packs, key=lambda x: x.name.lower()):
                    card = AddonCard(
                        scroll_frame,
                        pack,
                        self.selected_world,
                        self.addon_manager,
                        on_toggle=self._on_addon_toggle,
                        on_delete=self._on_addon_delete,
                        installed_uuids=self._installed_uuids,
                    )
                    card.grid(row=row, column=0, sticky="ew", pady=5, padx=5)
                    row += 1

        # Create section header for enabled packs if any exist
        if enabled_packs:
            enabled_header = self._create_collapsible_header(
                scroll_frame,
                f"Enabled ({total_enabled}) - Load Order",
                enabled_collapsed,
                lambda: self._toggle_section(pack_type, "enabled"),
            )
            enabled_header.grid(row=row, column=0, sticky="ew", pady=(15 if missing_deps_packs else 5, 5), padx=5)
            row += 1

            if not enabled_collapsed:
                for pack, position in enabled_packs:
                    card = AddonCard(
                        scroll_frame,
                        pack,
                        self.selected_world,
                        self.addon_manager,
                        on_toggle=self._on_addon_toggle,
                        on_delete=self._on_addon_delete,
                        on_move_up=self._on_move_up,
                        on_move_down=self._on_move_down,
                        position=position,
                        total_enabled=total_enabled,
                        installed_uuids=self._installed_uuids,
                    )
                    card.grid(row=row, column=0, sticky="ew", pady=5, padx=5)
                    row += 1

        # Section for disabled packs
        if disabled_packs:
            disabled_header = self._create_collapsible_header(
                scroll_frame,
                f"Disabled ({total_disabled})",
                disabled_collapsed,
                lambda: self._toggle_section(pack_type, "disabled"),
            )
            disabled_header.grid(row=row, column=0, sticky="ew", pady=(15, 5), padx=5)
            row += 1

            if not disabled_collapsed:
                for pack in sorted(disabled_packs, key=lambda x: x.name.lower()):
                    card = AddonCard(
                        scroll_frame,
                        pack,
                        self.selected_world,
                        self.addon_manager,
                        on_toggle=self._on_addon_toggle,
                        on_delete=self._on_addon_delete,
                        installed_uuids=self._installed_uuids,
                    )
                    card.grid(row=row, column=0, sticky="ew", pady=5, padx=5)
                    row += 1

        # Force layout update after all widgets are created
        scroll_frame.update_idletasks()

    def _create_collapsible_header(
        self,
        parent,
        text: str,
        is_collapsed: bool,
        on_click: Callable,
        header_color: Optional[str] = None,
    ) -> ctk.CTkFrame:
        """Create a clickable collapsible section header."""
        header_frame = ctk.CTkFrame(parent, fg_color="transparent", cursor="hand2")

        # Collapse/expand indicator
        indicator = "\u25B6" if is_collapsed else "\u25BC"  # Right or down triangle
        indicator_label = ctk.CTkLabel(
            header_frame,
            text=indicator,
            font=ctk.CTkFont(size=10),
            width=15,
            text_color=header_color,
        )
        indicator_label.pack(side="left", padx=(0, 5))

        # Section title
        title_label = ctk.CTkLabel(
            header_frame,
            text=text,
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            text_color=header_color,
        )
        title_label.pack(side="left")

        # Make the entire header clickable
        def handle_click(event):
            on_click()

        header_frame.bind("<Button-1>", handle_click)
        indicator_label.bind("<Button-1>", handle_click)
        title_label.bind("<Button-1>", handle_click)

        return header_frame

    def _toggle_section(self, pack_type: PackType, section: str) -> None:
        """Toggle the collapsed state of a section."""
        if pack_type == PackType.BEHAVIOR:
            if section == "missing_deps":
                self._behavior_missing_deps_collapsed = not self._behavior_missing_deps_collapsed
            elif section == "enabled":
                self._behavior_enabled_collapsed = not self._behavior_enabled_collapsed
            else:
                self._behavior_disabled_collapsed = not self._behavior_disabled_collapsed
        else:
            if section == "missing_deps":
                self._resource_missing_deps_collapsed = not self._resource_missing_deps_collapsed
            elif section == "enabled":
                self._resource_enabled_collapsed = not self._resource_enabled_collapsed
            else:
                self._resource_disabled_collapsed = not self._resource_disabled_collapsed

        # Refresh the lists to apply the change
        self._update_filtered_lists()

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

        # Check for missing dependencies when trying to enable
        if enabled and addon.has_missing_dependencies(self._installed_uuids):
            missing = addon.get_missing_dependencies(self._installed_uuids)
            messagebox.showwarning(
                "Missing Dependencies",
                f"Cannot enable '{addon.name}' because it has {len(missing)} missing "
                f"dependenc{'y' if len(missing) == 1 else 'ies'}.\n\n"
                "Please install the required dependencies first.",
            )
            self.refresh()  # Reset the toggle switch
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

    def _on_move_up(self, addon: Addon) -> None:
        """Handle move up button click (increase priority)."""
        if self._is_server_running():
            self._show_server_running_warning()
            return

        if not self.selected_world:
            return

        success = self.addon_manager.move_addon_priority(
            addon, self.selected_world, -1
        )
        if success:
            self.refresh()

    def _on_move_down(self, addon: Addon) -> None:
        """Handle move down button click (decrease priority)."""
        if self._is_server_running():
            self._show_server_running_warning()
            return

        if not self.selected_world:
            return

        success = self.addon_manager.move_addon_priority(
            addon, self.selected_world, +1
        )
        if success:
            self.refresh()

    def _show_import_dialog(self) -> None:
        """Show the import addon dialog."""
        from ..config import config

        if self._is_server_running():
            self._show_server_running_warning()
            return

        dialog = ImportDialog(self.winfo_toplevel())
        self.winfo_toplevel().wait_window(dialog)

        if dialog.imported:
            # Auto-enable imported packs if setting is enabled
            if config.auto_enable_after_import and self.selected_world:
                self._auto_enable_imported_packs(dialog.imported_packs)
            else:
                self._refresh()

    def _auto_enable_imported_packs(self, imported_packs: list) -> None:
        """Automatically enable imported packs in the selected world."""
        # First refresh to get the newly imported packs
        self.addon_manager.refresh()

        if not imported_packs or not self.selected_world:
            self.refresh()
            return

        # Get all packs
        all_packs = (
            self.addon_manager.get_behavior_packs()
            + self.addon_manager.get_resource_packs()
        )

        # Enable imported packs
        # imported_packs is List[Tuple[folder_name, PackType]]
        for folder_name, pack_type in imported_packs:
            # Find the addon by matching folder name
            for addon in all_packs:
                if addon.path.name == folder_name and addon.pack_type == pack_type:
                    if not self.addon_manager.is_addon_enabled_in_world(
                        addon, self.selected_world
                    ):
                        self.addon_manager.enable_addon(addon, self.selected_world)
                    break

        # Update the UI
        self.refresh()

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
        on_move_up: Optional[Callable] = None,
        on_move_down: Optional[Callable] = None,
        position: Optional[int] = None,
        total_enabled: int = 0,
        installed_uuids: Optional[set] = None,
    ):
        super().__init__(parent)

        self.addon = addon
        self.world = world
        self.addon_manager = addon_manager
        self.on_toggle = on_toggle
        self.on_delete = on_delete
        self.on_move_up = on_move_up
        self.on_move_down = on_move_down
        self.position = position
        self.total_enabled = total_enabled
        self.installed_uuids = installed_uuids or self._get_installed_uuids()

        self._create_widgets()

    def _create_widgets(self) -> None:
        """Create card widgets."""
        # Check version compatibility
        is_compatible = self.addon.is_compatible

        # Check for missing dependencies
        has_missing_deps = self.addon.has_missing_dependencies(self.installed_uuids)
        missing_deps_count = len(self.addon.get_missing_dependencies(self.installed_uuids))

        # Determine if addon has issues (incompatible or missing dependencies)
        has_issues = not is_compatible or has_missing_deps

        # Use pack layout for more stable rendering during scroll
        self.configure(height=70)
        self.pack_propagate(False)

        # Set border color for addons with issues
        if has_issues:
            self.configure(border_width=2, border_color="#D32F2F")

        # Main container using pack for stability
        main_container = ctk.CTkFrame(self, fg_color="transparent")
        main_container.pack(fill="both", expand=True, padx=5, pady=5)

        # Icon placeholder
        icon_frame = ctk.CTkFrame(main_container, width=50, height=50, corner_radius=5)
        icon_frame.pack(side="left", padx=(5, 10), pady=5)
        icon_frame.pack_propagate(False)

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

        # Controls frame (pack on right side first)
        controls_frame = ctk.CTkFrame(main_container, fg_color="transparent")
        controls_frame.pack(side="right", padx=(10, 5), pady=5)

        # Info container in the middle (takes remaining space)
        info_container = ctk.CTkFrame(main_container, fg_color="transparent")
        info_container.pack(side="left", fill="both", expand=True, pady=5)

        # Pack name with position indicator for enabled packs
        name_text = self.addon.name
        if self.position is not None:
            # Show position as 1-indexed for user display
            name_text = f"#{self.position + 1}  {self.addon.name}"

        # Use red text color for addons with issues
        name_color = "#D32F2F" if has_issues else None

        name_label = ctk.CTkLabel(
            info_container,
            text=name_text,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            text_color=name_color,
        )
        name_label.pack(anchor="sw", pady=(5, 0))

        # Pack info - show warnings for issues
        info_text = f"v{self.addon.version_string}"
        if not is_compatible and has_missing_deps:
            # Both issues
            info_text += f" (requires MC {self.addon.min_engine_version_string}, {missing_deps_count} missing dep(s))"
        elif not is_compatible:
            info_text += f" (requires MC {self.addon.min_engine_version_string})"
        elif has_missing_deps:
            info_text += f" ({missing_deps_count} missing dependency)"
            if missing_deps_count > 1:
                info_text = info_text.replace("dependency)", "dependencies)")
        elif self.addon.description:
            desc = self.addon.description[:50]
            if len(self.addon.description) > 50:
                desc += "..."
            info_text += f" - {desc}"

        info_color = "#D32F2F" if has_issues else "gray"

        info_label = ctk.CTkLabel(
            info_container,
            text=info_text,
            font=ctk.CTkFont(size=11),
            text_color=info_color,
            anchor="w",
        )
        info_label.pack(anchor="nw", pady=(0, 5))

        # Priority controls (only for enabled packs with move callbacks)
        if self.position is not None and (self.on_move_up or self.on_move_down):
            priority_frame = ctk.CTkFrame(controls_frame, fg_color="transparent")
            priority_frame.pack(side="left", padx=(0, 15))

            # Up button (disabled if already at top)
            can_move_up = self.position > 0
            self.up_btn = ctk.CTkButton(
                priority_frame,
                text="\u25B2",  # Unicode up triangle
                width=30,
                height=24,
                font=ctk.CTkFont(size=10),
                command=self._on_move_up_click,
                state="normal" if can_move_up else "disabled",
                fg_color="#555555" if can_move_up else "#333333",
            )
            self.up_btn.pack(side="left", padx=2)

            # Down button (disabled if already at bottom)
            can_move_down = self.position < self.total_enabled - 1
            self.down_btn = ctk.CTkButton(
                priority_frame,
                text="\u25BC",  # Unicode down triangle
                width=30,
                height=24,
                font=ctk.CTkFont(size=10),
                command=self._on_move_down_click,
                state="normal" if can_move_down else "disabled",
                fg_color="#555555" if can_move_down else "#333333",
            )
            self.down_btn.pack(side="left", padx=2)

        # Enable/Disable switch
        is_enabled = False
        if self.world:
            is_enabled = self.addon_manager.is_addon_enabled_in_world(
                self.addon, self.world
            )

        # Disable switch for addons with missing dependencies
        switch_state = "disabled" if has_missing_deps else "normal"

        self.switch_var = ctk.BooleanVar(value=is_enabled)
        self.switch = ctk.CTkSwitch(
            controls_frame,
            text="Enabled" if not has_missing_deps else "Missing Deps",
            variable=self.switch_var,
            command=self._on_switch_toggle,
            width=40,
            state=switch_state,
        )
        self.switch.pack(side="left", padx=(0, 10))

        # Info button
        self.info_btn = ctk.CTkButton(
            controls_frame,
            text="Info",
            width=50,
            height=28,
            fg_color="#555555",
            hover_color="#666666",
            command=self._on_info_click,
        )
        self.info_btn.pack(side="left", padx=(0, 5))

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

    def _get_installed_uuids(self) -> set:
        """Get set of all installed addon UUIDs."""
        all_addons = (
            self.addon_manager.get_behavior_packs()
            + self.addon_manager.get_resource_packs()
        )
        return {addon.uuid for addon in all_addons}

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

    def _on_move_up_click(self) -> None:
        """Handle move up button click."""
        if self.on_move_up:
            self.on_move_up(self.addon)

    def _on_move_down_click(self) -> None:
        """Handle move down button click."""
        if self.on_move_down:
            self.on_move_down(self.addon)

    def _on_info_click(self) -> None:
        """Handle info button click."""
        from .addon_details_dialog import AddonDetailsDialog

        dialog = AddonDetailsDialog(
            self.winfo_toplevel(), self.addon, self.addon_manager
        )
        self.winfo_toplevel().wait_window(dialog)
