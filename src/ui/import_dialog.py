"""Import addon dialog."""

import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from ..addon import AddonImporter


class ImportDialog(ctk.CTkToplevel):
    """Dialog for importing addons."""

    def __init__(self, parent):
        super().__init__(parent)

        self.imported = False
        self.selected_path: Optional[str] = None

        self.title("Import Addon")
        self.geometry("550x350")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.grab_set()

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - 550) // 2
        y = parent.winfo_y() + (parent.winfo_height() - 350) // 2
        self.geometry(f"+{x}+{y}")

        self._create_widgets()

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

        # Show progress section (insert before status label)
        self.progress_frame.pack(
            fill="x", padx=30, pady=(10, 0), before=self.status_label
        )
        self.progress_bar.set(0)
        self.progress_label.configure(text="Starting import...")
        self.status_label.configure(text="")
        self.import_btn.configure(state="disabled")
        self.cancel_btn.configure(state="disabled")
        self.file_btn.configure(state="disabled")
        self.folder_btn.configure(state="disabled")

        # Initialize progress tracking
        self._progress_step = 0
        self._progress_total = 1
        self._progress_message = "Starting..."

        # Run import in background thread to keep UI responsive
        self._import_thread = threading.Thread(
            target=self._run_import_thread,
            args=(path,),
            daemon=True,
        )
        self._import_thread.start()

        # Start checking for completion and updating progress
        self._update_progress_display()

    def _progress_callback(self, step: int, total: int, message: str) -> None:
        """Callback for import progress updates (called from background thread)."""
        self._progress_step = step
        self._progress_total = total
        self._progress_message = message

    def _run_import_thread(self, path: Path) -> None:
        """Run the import operation in a background thread."""
        # Perform import with progress callback
        if path.is_dir():
            self._import_result = AddonImporter.import_folder(
                path, progress_callback=self._progress_callback
            )
        else:
            self._import_result = AddonImporter.import_addon(
                path, progress_callback=self._progress_callback
            )

    def _update_progress_display(self) -> None:
        """Update the progress bar and label from the main thread."""
        # Update progress bar, percentage, and label
        if self._progress_total > 0:
            progress = self._progress_step / self._progress_total
            self.progress_bar.set(progress)
            percent = int(progress * 100)
            self.progress_percent.configure(text=f"{percent}%")
        self.progress_label.configure(text=self._progress_message)

        if self._import_thread.is_alive():
            # Still running, check again in 50ms
            self.after(50, self._update_progress_display)
        else:
            # Import complete, handle result
            self._handle_import_result()

    def _handle_import_result(self) -> None:
        """Handle the import result on the main thread."""
        result = self._import_result

        if result.success:
            self.progress_bar.set(1)  # Show complete
            self.progress_percent.configure(text="100%")
            self.progress_label.configure(text="Complete!")
            self.status_label.configure(
                text="Import successful!",
                text_color="#00C853",  # Green
            )
            self.imported = True

            # Show compatibility warnings if any
            if result.warnings:
                warning_text = "\n\n".join(result.warnings)
                messagebox.showwarning(
                    "Compatibility Warning",
                    f"Import successful, but there are compatibility concerns:\n\n{warning_text}",
                )

            # Show success message with details
            messagebox.showinfo("Import Successful", result.message)

            self.destroy()
        else:
            self.progress_bar.set(0)  # Reset
            self.progress_percent.configure(text="0%")
            self.progress_frame.pack_forget()  # Hide progress section
            self.status_label.configure(
                text=f"Import failed: {result.message}",
                text_color="#FF5252",  # Red
            )
            self.import_btn.configure(state="normal")
            self.cancel_btn.configure(state="normal")
            self.file_btn.configure(state="normal")
            self.folder_btn.configure(state="normal")

            messagebox.showerror("Import Failed", result.message)
