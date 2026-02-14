"""Addon details dialog for displaying detailed addon information."""

import subprocess
import sys
import webbrowser
from pathlib import Path
from tkinter import messagebox
from typing import Dict, Optional

import customtkinter as ctk
from PIL import Image

from ..addon import Addon, AddonManager, PackType
from ..config import config
from ..server import server_fs
from .main_window import set_dialog_icon


def get_icon(icon_path: Path, size: tuple = (80, 80)) -> Optional[ctk.CTkImage]:
    """Load an icon image at the specified size."""
    try:
        img = Image.open(icon_path)
        img = img.resize(size, Image.Resampling.LANCZOS)
        return ctk.CTkImage(img, size=size)
    except Exception:
        return None


class AddonDetailsDialog(ctk.CTkToplevel):
    """Dialog for displaying detailed addon information."""

    def __init__(self, parent, addon: Addon, addon_manager: AddonManager):
        super().__init__(parent)

        self.addon = addon
        self.addon_manager = addon_manager
        self.default_changed = False
        self._installed_addons_by_uuid: Dict[str, Addon] = {}
        self._build_uuid_lookup()

        self.title(f"Addon Details - {addon.name}")
        self.geometry("550x550")
        self.resizable(False, False)

        set_dialog_icon(self)

        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 550) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 550) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _build_uuid_lookup(self) -> None:
        """Build a lookup dictionary of installed addons by UUID."""
        all_addons = (
            self.addon_manager.get_behavior_packs()
            + self.addon_manager.get_resource_packs()
            + self.addon_manager.get_development_behavior_packs()
            + self.addon_manager.get_development_resource_packs()
        )
        for addon in all_addons:
            self._installed_addons_by_uuid[addon.uuid] = addon

    def _get_installed_addon(self, uuid: str) -> Optional[Addon]:
        """Get an installed addon by UUID, or None if not installed."""
        return self._installed_addons_by_uuid.get(uuid)

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        # Main scrollable container
        main_scroll = ctk.CTkScrollableFrame(self)
        main_scroll.pack(fill="both", expand=True, padx=10, pady=10)
        main_scroll.grid_columnconfigure(0, weight=1)

        row = 0

        # Header section with icon and name
        header_frame = ctk.CTkFrame(main_scroll)
        header_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        header_frame.grid_columnconfigure(1, weight=1)
        row += 1

        # Icon
        icon_frame = ctk.CTkFrame(header_frame, width=80, height=80, corner_radius=8)
        icon_frame.grid(row=0, column=0, rowspan=2, padx=10, pady=10)
        icon_frame.grid_propagate(False)

        icon_file = (
            server_fs.get_local_file_copy(self.addon.icon_path)
            if self.addon.icon_path
            else None
        )
        if icon_file:
            photo = get_icon(icon_file)
            if photo:
                icon_label = ctk.CTkLabel(icon_frame, image=photo, text="")
                icon_label.place(relx=0.5, rely=0.5, anchor="center")
            else:
                self._show_default_icon(icon_frame)
        else:
            self._show_default_icon(icon_frame)

        # Pack name
        name_label = ctk.CTkLabel(
            header_frame,
            text=self.addon.name,
            font=ctk.CTkFont(size=18, weight="bold"),
            anchor="w",
        )
        name_label.grid(row=0, column=1, sticky="sw", padx=10, pady=(15, 0))

        # Pack type
        pack_type_text = (
            "Behavior Pack"
            if self.addon.pack_type == PackType.BEHAVIOR
            else "Resource Pack"
        )
        type_label = ctk.CTkLabel(
            header_frame,
            text=f"Type: {pack_type_text}",
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
        )
        type_label.grid(row=1, column=1, sticky="nw", padx=10, pady=(0, 15))

        # Description section
        if self.addon.description:
            desc_section = self._create_section(main_scroll, "Description", row)
            row += 1

            desc_text = ctk.CTkTextbox(
                desc_section,
                height=80,
                wrap="word",
                fg_color="transparent",
                activate_scrollbars=True,
            )
            desc_text.pack(fill="x", padx=10, pady=(0, 10))
            desc_text.insert("1.0", self.addon.description)
            desc_text.configure(state="disabled")

        # Details section
        details_section = self._create_section(main_scroll, "Details", row)
        row += 1

        details_frame = ctk.CTkFrame(details_section, fg_color="transparent")
        details_frame.pack(fill="x", padx=10, pady=(0, 10))

        detail_row = 0

        # Version
        self._add_detail_row(
            details_frame, "Version:", self.addon.version_string, detail_row
        )
        detail_row += 1

        # Min Engine Version
        self._add_detail_row(
            details_frame,
            "Min Engine Version:",
            self.addon.min_engine_version_string,
            detail_row,
        )
        detail_row += 1

        # Format Version
        if self.addon.format_version:
            self._add_detail_row(
                details_frame,
                "Format Version:",
                self.addon.format_version,
                detail_row,
            )
            detail_row += 1

        # Author
        if self.addon.author:
            self._add_detail_row(
                details_frame, "Author:", self.addon.author, detail_row
            )
            detail_row += 1

        # URL
        if self.addon.url:
            url_label = ctk.CTkLabel(
                details_frame,
                text="URL:",
                font=ctk.CTkFont(weight="bold"),
                anchor="w",
            )
            url_label.grid(row=detail_row, column=0, sticky="w", pady=2)

            url_frame = ctk.CTkFrame(details_frame, fg_color="transparent")
            url_frame.grid(row=detail_row, column=1, sticky="w", pady=2)

            url_value = ctk.CTkLabel(
                url_frame,
                text=self._truncate_text(self.addon.url, 35),
                anchor="w",
            )
            url_value.pack(side="left")

            open_url_btn = ctk.CTkButton(
                url_frame,
                text="Open",
                width=50,
                height=24,
                command=self._open_url,
            )
            open_url_btn.pack(side="left", padx=(10, 0))
            detail_row += 1

        # License
        if self.addon.license:
            self._add_detail_row(
                details_frame, "License:", self.addon.license, detail_row
            )
            detail_row += 1

        # UUID with copy button
        uuid_label = ctk.CTkLabel(
            details_frame,
            text="UUID:",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        )
        uuid_label.grid(row=detail_row, column=0, sticky="w", pady=2)

        uuid_frame = ctk.CTkFrame(details_frame, fg_color="transparent")
        uuid_frame.grid(row=detail_row, column=1, sticky="w", pady=2)

        uuid_value = ctk.CTkLabel(
            uuid_frame,
            text=self.addon.uuid,
            anchor="w",
            font=ctk.CTkFont(size=11),
        )
        uuid_value.pack(side="left")

        self.copy_uuid_btn = ctk.CTkButton(
            uuid_frame,
            text="Copy",
            width=50,
            height=24,
            command=self._copy_uuid,
        )
        self.copy_uuid_btn.pack(side="left", padx=(10, 0))
        detail_row += 1

        # Path with open folder button
        path_label = ctk.CTkLabel(
            details_frame,
            text="Path:",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        )
        path_label.grid(row=detail_row, column=0, sticky="w", pady=2)

        path_frame = ctk.CTkFrame(details_frame, fg_color="transparent")
        path_frame.grid(row=detail_row, column=1, sticky="w", pady=2)

        path_text = server_fs.get_addon_display_path(self.addon.path)
        path_value = ctk.CTkLabel(
            path_frame,
            text=self._truncate_text(path_text, 30),
            anchor="w",
            font=ctk.CTkFont(size=11),
        )
        path_value.pack(side="left")

        open_folder_text = "Copy Path" if config.connection_type == "sftp" else "Open Folder"
        open_folder_btn = ctk.CTkButton(
            path_frame,
            text=open_folder_text,
            width=80,
            height=24,
            command=self._open_folder,
        )
        open_folder_btn.pack(side="left", padx=(10, 0))
        detail_row += 1

        # Default-addon row
        default_label = ctk.CTkLabel(
            details_frame,
            text="Default Addon:",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        )
        default_label.grid(row=detail_row, column=0, sticky="w", pady=2)

        default_frame = ctk.CTkFrame(details_frame, fg_color="transparent")
        default_frame.grid(row=detail_row, column=1, sticky="w", pady=2)

        self.default_state_label = ctk.CTkLabel(default_frame, text="", anchor="w")
        self.default_state_label.pack(side="left")

        self.set_default_btn = ctk.CTkButton(
            default_frame,
            text="Set as Default",
            width=110,
            height=24,
            command=self._set_as_default,
        )
        self.set_default_btn.pack(side="left", padx=(10, 0))
        self._refresh_default_controls()
        detail_row += 1

        # Capabilities section (if any)
        if self.addon.capabilities:
            caps_section = self._create_section(main_scroll, "Capabilities", row)
            row += 1

            caps_text = ", ".join(self.addon.capabilities)
            caps_label = ctk.CTkLabel(
                caps_section,
                text=caps_text,
                anchor="w",
                wraplength=500,
            )
            caps_label.pack(fill="x", padx=10, pady=(0, 10))

        # Dependencies section (if any, excluding Minecraft modules)
        pack_dependencies = [
            dep for dep in self.addon.dependencies
            if self.addon.should_track_dependency(dep)
        ]

        if pack_dependencies:
            deps_section = self._create_section(
                main_scroll, f"Dependencies ({len(pack_dependencies)})", row
            )
            row += 1

            for dep in pack_dependencies:
                dep_identifier = self.addon.get_dependency_identifier(dep) or "Unknown"
                dep_version = dep.get("version", [])
                if isinstance(dep_version, list):
                    dep_version_str = ".".join(str(v) for v in dep_version)
                else:
                    dep_version_str = str(dep_version)

                # Check if dependency is installed
                installed_addon = self._get_installed_addon(dep_identifier)

                # Create a row frame for this dependency
                dep_row_frame = ctk.CTkFrame(deps_section, fg_color="transparent")
                dep_row_frame.pack(fill="x", padx=10, pady=2)

                if installed_addon:
                    # Dependency is installed - show icon and name
                    icon_size = (24, 24)
                    installed_icon = (
                        server_fs.get_local_file_copy(installed_addon.icon_path)
                        if installed_addon.icon_path
                        else None
                    )
                    if installed_icon:
                        photo = get_icon(installed_icon, icon_size)
                        if photo:
                            icon_label = ctk.CTkLabel(
                                dep_row_frame, image=photo, text=""
                            )
                            icon_label.pack(side="left", padx=(0, 8))
                        else:
                            self._add_small_default_icon(
                                dep_row_frame, installed_addon.pack_type
                            )
                    else:
                        self._add_small_default_icon(
                            dep_row_frame, installed_addon.pack_type
                        )

                    # Show addon name and version
                    dep_text = installed_addon.name
                    if dep_version_str:
                        dep_text += f" (v{dep_version_str})"

                    dep_label = ctk.CTkLabel(
                        dep_row_frame,
                        text=dep_text,
                        anchor="w",
                        font=ctk.CTkFont(size=11),
                    )
                    dep_label.pack(side="left")
                else:
                    # Dependency is NOT installed - show red warning
                    warning_label = ctk.CTkLabel(
                        dep_row_frame,
                        text="!",
                        font=ctk.CTkFont(size=12, weight="bold"),
                        text_color="#FF4444",
                        width=24,
                    )
                    warning_label.pack(side="left", padx=(0, 8))

                    dep_text = dep_identifier
                    if dep_version_str:
                        dep_text += f" (v{dep_version_str})"

                    dep_label = ctk.CTkLabel(
                        dep_row_frame,
                        text=dep_text,
                        anchor="w",
                        font=ctk.CTkFont(size=11),
                        text_color="#FF4444",
                    )
                    dep_label.pack(side="left")

                    missing_label = ctk.CTkLabel(
                        dep_row_frame,
                        text="(Not Installed)",
                        anchor="w",
                        font=ctk.CTkFont(size=10),
                        text_color="#FF4444",
                    )
                    missing_label.pack(side="left", padx=(8, 0))

            # Add some padding at the end
            ctk.CTkLabel(deps_section, text="").pack(pady=2)

        # Subpacks section (if any)
        if self.addon.subpacks:
            subpacks_section = self._create_section(
                main_scroll, f"Subpacks ({len(self.addon.subpacks)})", row
            )
            row += 1

            for subpack in self.addon.subpacks:
                subpack_name = subpack.get("name", "Unnamed")
                subpack_folder = subpack.get("folder_name", "")
                memory_tier = subpack.get("memory_tier", "")

                subpack_text = f"  - {subpack_name}"
                if subpack_folder:
                    subpack_text += f" (folder: {subpack_folder})"
                if memory_tier:
                    subpack_text += f" [tier: {memory_tier}]"

                subpack_label = ctk.CTkLabel(
                    subpacks_section,
                    text=subpack_text,
                    anchor="w",
                    font=ctk.CTkFont(size=11),
                )
                subpack_label.pack(fill="x", padx=10, pady=1)

            # Add some padding at the end
            ctk.CTkLabel(subpacks_section, text="").pack(pady=2)

        # Close button
        close_btn = ctk.CTkButton(
            self,
            text="Close",
            width=100,
            command=self.destroy,
        )
        close_btn.pack(pady=10)

    def _create_section(
        self, parent, title: str, row: int
    ) -> ctk.CTkFrame:
        """Create a collapsible section with a title."""
        section_frame = ctk.CTkFrame(parent)
        section_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))

        title_label = ctk.CTkLabel(
            section_frame,
            text=title,
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        )
        title_label.pack(fill="x", padx=10, pady=(10, 5))

        return section_frame

    def _add_detail_row(
        self, parent, label: str, value: str, row: int
    ) -> None:
        """Add a label-value row to the details grid."""
        label_widget = ctk.CTkLabel(
            parent,
            text=label,
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        )
        label_widget.grid(row=row, column=0, sticky="w", pady=2, padx=(0, 10))

        value_widget = ctk.CTkLabel(
            parent,
            text=value or "-",
            anchor="w",
        )
        value_widget.grid(row=row, column=1, sticky="w", pady=2)

    def _truncate_text(self, text: str, max_length: int) -> str:
        """Truncate text with ellipsis if too long."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _show_default_icon(self, frame: ctk.CTkFrame) -> None:
        """Show default pack icon."""
        pack_type_char = "B" if self.addon.pack_type == PackType.BEHAVIOR else "R"
        icon_label = ctk.CTkLabel(
            frame,
            text=pack_type_char,
            font=ctk.CTkFont(size=32, weight="bold"),
            text_color="gray",
        )
        icon_label.place(relx=0.5, rely=0.5, anchor="center")

    def _add_small_default_icon(
        self, parent: ctk.CTkFrame, pack_type: PackType
    ) -> None:
        """Add a small default icon to a parent frame."""
        pack_type_char = "B" if pack_type == PackType.BEHAVIOR else "R"
        icon_frame = ctk.CTkFrame(parent, width=24, height=24, corner_radius=4)
        icon_frame.pack(side="left", padx=(0, 8))
        icon_frame.pack_propagate(False)
        icon_label = ctk.CTkLabel(
            icon_frame,
            text=pack_type_char,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color="gray",
        )
        icon_label.place(relx=0.5, rely=0.5, anchor="center")

    def _open_url(self) -> None:
        """Open the addon URL in the default browser."""
        if self.addon.url:
            webbrowser.open(self.addon.url)

    def _copy_uuid(self) -> None:
        """Copy the UUID to clipboard."""
        self.clipboard_clear()
        self.clipboard_append(self.addon.uuid)
        # Update button text briefly to show feedback
        self.copy_uuid_btn.configure(text="Copied!")
        self.after(1500, lambda: self.copy_uuid_btn.configure(text="Copy"))

    def _open_folder(self) -> None:
        """Open the addon folder in the file explorer, or copy remote path."""
        if config.connection_type == "sftp":
            remote_path = server_fs.get_addon_display_path(self.addon.path)
            self.clipboard_clear()
            self.clipboard_append(remote_path)
            messagebox.showinfo("Path Copied", "Remote addon path copied to clipboard.")
            return

        local_path = server_fs.get_local_absolute_path(self.addon.path)
        if local_path and local_path.exists():
            if sys.platform == "win32":
                subprocess.run(["explorer", str(local_path)], check=False)
            elif sys.platform == "darwin":
                subprocess.run(["open", str(local_path)], check=False)
            else:
                subprocess.run(["xdg-open", str(local_path)], check=False)

    def _refresh_default_controls(self) -> None:
        """Refresh default-addon status controls."""
        if self.addon.is_default:
            self.default_state_label.configure(text="Yes", text_color="#00C853")
            self.set_default_btn.configure(text="Already Default", state="disabled")
        else:
            self.default_state_label.configure(text="No", text_color="gray")
            self.set_default_btn.configure(text="Set as Default", state="normal")

    def _set_as_default(self) -> None:
        """Mark this addon as a default addon."""
        if self.addon.is_default:
            return

        default_uuids = list(config.default_pack_uuids)
        if self.addon.uuid not in default_uuids:
            default_uuids.append(self.addon.uuid)
            config.default_pack_uuids = default_uuids
            config.default_packs_detected = True
            Addon.set_default_pack_uuids(set(default_uuids))
            self.default_changed = True

        self._refresh_default_controls()
        self._refresh_parent_after_default_change()
        messagebox.showinfo(
            "Default Addon Updated",
            f"'{self.addon.name}' is now marked as a default addon.",
        )

    def _refresh_parent_after_default_change(self) -> None:
        """Refresh addon list in the parent window after default updates."""
        try:
            if hasattr(self.master, "addon_panel"):
                self.master.addon_panel.refresh()
        except Exception:
            pass
