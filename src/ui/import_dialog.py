"""Import addon dialog."""

import sys
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk
from PIL import Image, ImageTk

from ..addon import AddonImporter


class ImportDialog(ctk.CTkToplevel):
    """Dialog for importing addons."""

    def __init__(self, parent):
        super().__init__(parent)

        self.imported = False
        self.selected_path: Optional[str] = None
        self.imported_packs = []  # List of (folder_name, PackType) tuples
        self._pending_report_lines = []
        self._report_lock = threading.Lock()
        self._last_progress_message = ""
        self._step_progress_info = None

        self.title("Import Addon")
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        default_w = 760
        default_h = 680
        min_w = 680
        min_h = 560

        width = min(default_w, max(min_w, screen_w - 80))
        height = min(default_h, max(min_h, screen_h - 80))

        self.geometry(f"{width}x{height}")
        self.minsize(min_w, min_h)
        self.resizable(True, True)

        # Set window icon
        self._set_icon()

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on screen so the full dialog stays visible regardless of parent position
        self.update_idletasks()
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2)
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

    def _set_icon(self) -> None:
        """Set the window icon."""
        # Determine base path (handles PyInstaller bundled apps)
        if getattr(sys, "frozen", False):
            base_path = Path(sys._MEIPASS)
        else:
            base_path = Path(__file__).parent.parent.parent

        icon_path = base_path / "assets" / "MCBManagerIcon.png"
        ico_path = base_path / "assets" / "MCBManagerIcon.ico"

        try:
            # On Windows, use .ico for window icon
            if ico_path.exists():
                self.after(200, lambda: self.iconbitmap(str(ico_path)))
            if icon_path.exists():
                icon_image = Image.open(icon_path)
                icon_photo = ImageTk.PhotoImage(icon_image)
                self._icon_photo = icon_photo  # Keep reference
                self.iconphoto(True, icon_photo)
        except Exception:
            pass  # Silently fail if icon cannot be loaded

    def _create_widgets(self) -> None:
        """Create dialog widgets."""
        # Title
        title_label = ctk.CTkLabel(
            self,
            text="Import Minecraft Addon",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title_label.pack(pady=(20, 5))

        # Instructions
        instructions = ctk.CTkLabel(
            self,
            text="Enter the path to an addon file or folder, or use Browse to select.",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        instructions.pack(pady=(0, 15))

        # Path entry frame
        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.pack(fill="x", padx=30, pady=10)

        self.path_entry = ctk.CTkEntry(
            path_frame,
            placeholder_text="Enter path or browse...",
            width=350,
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.path_entry.bind("<KeyRelease>", self._on_path_change)

        # Browse buttons
        browse_frame = ctk.CTkFrame(self, fg_color="transparent")
        browse_frame.pack(fill="x", padx=30, pady=5)

        self.file_btn = ctk.CTkButton(
            browse_frame, text="Browse File", width=130, command=self._select_file
        )
        self.file_btn.pack(side="left", padx=(0, 10))

        self.folder_btn = ctk.CTkButton(
            browse_frame,
            text="Browse Folder",
            width=130,
            fg_color="gray",
            command=self._select_folder,
        )
        self.folder_btn.pack(side="left")

        # Supported formats info
        formats_label = ctk.CTkLabel(
            self,
            text="Supported formats: .mcaddon, .mcpack, .zip, or addon folder",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        formats_label.pack(pady=(15, 5))

        self.install_to_development_var = ctk.BooleanVar(value=False)
        self.install_to_development_checkbox = ctk.CTkCheckBox(
            self,
            text=(
                "Install to development directories "
                "(development_behavior_packs / development_resource_packs)"
            ),
            variable=self.install_to_development_var,
        )
        self.install_to_development_checkbox.pack(pady=(0, 6))

        # Status label for errors/success (placed before progress so we can insert progress before it)
        self.status_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=12))
        self.status_label.pack(pady=5)

        # Progress section (hidden initially, will be inserted before status_label when shown)
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")

        # Progress status label (e.g., "Extracting archive...")
        self.progress_label = ctk.CTkLabel(
            self.progress_frame,
            text="",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self.progress_label.pack(anchor="w", pady=(0, 5))

        # Progress bar with percentage
        progress_bar_frame = ctk.CTkFrame(self.progress_frame, fg_color="transparent")
        progress_bar_frame.pack(fill="x")

        self.progress_bar = ctk.CTkProgressBar(progress_bar_frame)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.progress_bar.set(0)

        self.progress_percent = ctk.CTkLabel(
            progress_bar_frame,
            text="0%",
            font=ctk.CTkFont(size=12, weight="bold"),
            width=45,
        )
        self.progress_percent.pack(side="right")

        # Step progress section for compression/upload operations
        self.step_progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.step_progress_frame.pack(fill="x", padx=30, pady=(8, 0))

        self.step_progress_label = ctk.CTkLabel(
            self.step_progress_frame,
            text="Step progress: Waiting for transfer steps...",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            anchor="w",
        )
        self.step_progress_label.pack(anchor="w", pady=(0, 4))

        step_bar_row = ctk.CTkFrame(self.step_progress_frame, fg_color="transparent")
        step_bar_row.pack(fill="x")

        self.step_progress_bar = ctk.CTkProgressBar(step_bar_row)
        self.step_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.step_progress_bar.set(0)

        self.step_progress_percent = ctk.CTkLabel(
            step_bar_row,
            text="0%",
            font=ctk.CTkFont(size=11, weight="bold"),
            width=45,
        )
        self.step_progress_percent.pack(side="right")

        # Detailed report section
        report_label = ctk.CTkLabel(
            self,
            text="Import Report",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        report_label.pack(fill="x", padx=30, pady=(10, 2))

        self.report_text = ctk.CTkTextbox(self, height=180, wrap="word")
        self.report_text.pack(fill="both", expand=True, padx=30, pady=(0, 5))
        self.report_text.configure(state="disabled")

        # Bottom buttons
        bottom_frame = ctk.CTkFrame(self, fg_color="transparent")
        bottom_frame.pack(fill="x", padx=30, pady=(10, 20), side="bottom")

        self.import_btn = ctk.CTkButton(
            bottom_frame,
            text="Import",
            width=100,
            state="disabled",
            command=self._do_import,
        )
        self.import_btn.pack(side="right", padx=5)

        self.cancel_btn = ctk.CTkButton(
            bottom_frame,
            text="Cancel",
            width=100,
            fg_color="gray",
            command=self.destroy,
        )
        self.cancel_btn.pack(side="right", padx=5)

    def _on_path_change(self, event=None) -> None:
        """Handle path entry change."""
        path = self.path_entry.get().strip()
        if path:
            self.selected_path = path
            self.import_btn.configure(state="normal")
        else:
            self.selected_path = None
            self.import_btn.configure(state="disabled")

    def _select_file(self) -> None:
        """Open file selection dialog."""
        filetypes = [
            ("Minecraft Addons", "*.mcaddon *.mcpack *.zip"),
            ("MC Addon", "*.mcaddon"),
            ("MC Pack", "*.mcpack"),
            ("ZIP Archive", "*.zip"),
            ("All Files", "*.*"),
        ]

        # Temporarily release grab to allow file dialog to work properly
        self.grab_release()

        filepath = filedialog.askopenfilename(
            title="Select Addon File",
            filetypes=filetypes,
            initialdir=Path.home() / "Downloads",
            parent=self,
        )

        # Restore grab and focus
        self.grab_set()
        self.focus_force()
        self.lift()

        if filepath:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, filepath)
            self.selected_path = filepath
            self.import_btn.configure(state="normal")

    def _select_folder(self) -> None:
        """Open folder selection dialog."""
        # Temporarily release grab to allow file dialog to work properly
        self.grab_release()

        folder = filedialog.askdirectory(
            title="Select Addon Folder",
            initialdir=Path.home() / "Downloads",
            parent=self,
        )

        # Restore grab and focus
        self.grab_set()
        self.focus_force()
        self.lift()

        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)
            self.selected_path = folder
            self.import_btn.configure(state="normal")

    def _do_import(self) -> None:
        """Perform the import."""
        if not self.selected_path:
            return

        path = Path(self.selected_path)
        install_to_development = bool(self.install_to_development_var.get())
        self._reset_report()

        # Show progress section (insert before status label)
        self.progress_frame.pack(
            fill="x", padx=30, pady=(10, 0), before=self.status_label
        )
        self.progress_bar.set(0)
        self.progress_label.configure(text="Step 0/1: Starting import...")
        self.status_label.configure(text="")
        self.import_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.file_btn.configure(state="disabled")
        self.folder_btn.configure(state="disabled")
        self.install_to_development_checkbox.configure(state="disabled")

        # Initialize progress tracking
        self._progress_step = 0
        self._progress_total = 1
        self._progress_message = "Starting..."
        self._last_progress_message = ""
        self._step_progress_info = None
        self.step_progress_bar.set(0)
        self.step_progress_percent.configure(text="0%")
        self.step_progress_label.configure(
            text="Step progress: Waiting for transfer steps...",
            text_color="gray",
        )
        self._append_report_line(f"Starting import: {path}")
        self._append_report_line(
            "Install target: development directories"
            if install_to_development
            else "Install target: default pack directories"
        )

        # Run import in background thread to keep UI responsive
        self._import_thread = threading.Thread(
            target=self._run_import_thread,
            args=(path, install_to_development),
            daemon=True,
        )
        self._import_thread.start()

        # Start checking for completion and updating progress
        self._update_progress_display()

    def _progress_callback(
        self, step: int, total: int, message: str, step_info: Optional[dict] = None
    ) -> None:
        """Callback for import progress updates (called from background thread)."""
        self._progress_step = step
        self._progress_total = total
        self._progress_message = message
        if step_info:
            step_name = str(step_info.get("step_name", "")).strip().lower()
            if step_name in {"compression", "upload"}:
                self._step_progress_info = step_info
        if message != self._last_progress_message:
            with self._report_lock:
                self._pending_report_lines.append(message)
            self._last_progress_message = message

    def _run_import_thread(self, path: Path, install_to_development: bool) -> None:
        """Run the import operation in a background thread."""
        # Perform import with progress callback
        if path.is_dir():
            self._import_result = AddonImporter.import_folder(
                path,
                progress_callback=self._progress_callback,
                install_to_development=install_to_development,
            )
        else:
            self._import_result = AddonImporter.import_addon(
                path,
                progress_callback=self._progress_callback,
                install_to_development=install_to_development,
            )

    def _update_progress_display(self) -> None:
        """Update the progress bar and label from the main thread."""
        self._flush_pending_report_lines()

        # Update progress bar, percentage, and label
        if self._progress_total > 0:
            progress = self._progress_step / self._progress_total
            self.progress_bar.set(progress)
            percent = int(progress * 100)
            self.progress_percent.configure(text=f"{percent}%")
        step_display = min(self._progress_step, self._progress_total)
        self.progress_label.configure(
            text=f"Step {step_display}/{self._progress_total}: {self._progress_message}"
        )

        # Update dedicated step-progress bar (compression/upload only)
        if self._step_progress_info:
            current = int(self._step_progress_info.get("current", 0))
            total = max(int(self._step_progress_info.get("total", 1)), 1)
            label = str(self._step_progress_info.get("label", "Step progress"))
            value = max(0.0, min(1.0, current / total))
            self.step_progress_bar.set(value)
            self.step_progress_percent.configure(text=f"{int(value * 100)}%")
            self.step_progress_label.configure(
                text=f"Step progress ({label}): {current}/{total}",
                text_color="gray",
            )

        if self._import_thread.is_alive():
            # Still running, check again in 50ms
            self.after(50, self._update_progress_display)
        else:
            # Import complete, handle result
            self._handle_import_result()

    def _handle_import_result(self) -> None:
        """Handle the import result on the main thread."""
        result = self._import_result
        self._flush_pending_report_lines()
        if result.details:
            self._append_report_lines(result.details)

        if result.success:
            self.progress_bar.set(1)  # Show complete
            self.progress_percent.configure(text="100%")
            self.progress_label.configure(text="Complete!")
            self.step_progress_bar.set(1)
            self.step_progress_percent.configure(text="100%")
            self.step_progress_label.configure(
                text="Step progress: Complete",
                text_color="#00C853",
            )
            self.status_label.configure(
                text="Import successful!",
                text_color="#00C853",  # Green
            )
            self.imported = True
            self.imported_packs = result.imported_packs  # Store for auto-enable

            # Show compatibility warnings if any
            if result.warnings:
                warning_text = "\n\n".join(result.warnings)
                messagebox.showwarning(
                    "Compatibility Warning",
                    f"Import successful, but there are compatibility concerns:\n\n{warning_text}",
                )

            self.status_label.configure(
                text="Import complete. Review the report below.",
                text_color="#00C853",
            )
            self.cancel_btn.configure(text="Close", state="normal")
            self.import_btn.configure(state="normal")
            self.file_btn.configure(state="normal")
            self.folder_btn.configure(state="normal")
            self.install_to_development_checkbox.configure(state="normal")
            messagebox.showinfo("Import Successful", result.message)
        else:
            self.progress_bar.set(0)  # Reset
            self.progress_percent.configure(text="0%")
            self.step_progress_bar.set(0)
            self.step_progress_percent.configure(text="0%")
            self.step_progress_label.configure(
                text="Step progress: Stopped",
                text_color="#FF5252",
            )
            self.status_label.configure(
                text=f"Import failed: {result.message}",
                text_color="#FF5252",  # Red
            )
            self.import_btn.configure(state="normal")
            self.cancel_btn.configure(state="normal")
            self.file_btn.configure(state="normal")
            self.folder_btn.configure(state="normal")
            self.install_to_development_checkbox.configure(state="normal")

            messagebox.showerror("Import Failed", result.message)

    def _append_report_line(self, line: str) -> None:
        """Append a single line to the report textbox."""
        text = (line or "").strip()
        if not text:
            return
        self.report_text.configure(state="normal")
        self.report_text.insert("end", text + "\n")
        self.report_text.see("end")
        self.report_text.configure(state="disabled")

    def _append_report_lines(self, lines) -> None:
        """Append multiple lines to the report textbox."""
        for line in lines:
            self._append_report_line(line)

    def _flush_pending_report_lines(self) -> None:
        """Move queued report lines from worker thread into the UI."""
        with self._report_lock:
            pending = self._pending_report_lines[:]
            self._pending_report_lines.clear()
        if pending:
            self._append_report_lines(pending)

    def _reset_report(self) -> None:
        """Clear the report textbox and queued lines."""
        with self._report_lock:
            self._pending_report_lines.clear()
        self.report_text.configure(state="normal")
        self.report_text.delete("1.0", "end")
        self.report_text.configure(state="disabled")
