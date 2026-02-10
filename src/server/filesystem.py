"""Filesystem abstraction for local and SFTP-backed server access."""

import json
import os
import posixpath
import shlex
import shutil
import socket
import stat
import tempfile
import threading
import time
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..config import config


@dataclass
class ServerDirEntry:
    """Directory entry returned by the server filesystem."""

    path: str
    name: str
    is_dir: bool


class ServerFilesystem:
    """Provides filesystem operations for local or SFTP-backed server roots."""

    SFTP_ARCHIVE_FILE_THRESHOLD = 15
    SFTP_UPLOAD_CHUNK_SIZE = 32768
    SFTP_UPLOAD_MAX_RETRIES = 8
    SFTP_UPLOAD_RETRY_DELAY_SECONDS = 1.5
    SFTP_UPLOAD_CHANNEL_TIMEOUT_SECONDS = 15.0

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._ssh_client = None
        self._sftp_client = None
        self._connection_signature: Optional[str] = None
        self._cache_dir = Path(tempfile.gettempdir()) / "mcbmanager_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._file_cache: Dict[str, Tuple[int, int, Path]] = {}

    @staticmethod
    def join(*parts: str) -> str:
        """Join relative server paths using POSIX separators."""
        clean_parts = []
        for part in parts:
            part_str = str(part or "").strip().replace("\\", "/")
            if not part_str:
                continue
            clean_parts.append(part_str.strip("/"))

        if not clean_parts:
            return ""

        return posixpath.join(*clean_parts)

    def is_sftp_mode(self) -> bool:
        """Return True when the configured backend is SFTP."""
        return config.connection_type == "sftp"

    def is_configured(self) -> bool:
        """Check whether the current server connection is configured."""
        if self.is_sftp_mode():
            return bool(
                config.sftp_host and config.sftp_username and config.sftp_remote_path
            )

        if not config.server_path:
            return False

        server_dir = Path(config.server_path)
        return server_dir.exists() and server_dir.is_dir()

    def get_display_path(self) -> str:
        """Get a user-facing display path for the configured server."""
        if self.is_sftp_mode():
            user = config.sftp_username or "user"
            host = config.sftp_host or "host"
            port = config.sftp_port
            remote_path = config.sftp_remote_path or "/"
            return f"sftp://{user}@{host}:{port}{remote_path}"

        return config.server_path or ""

    def get_addon_display_path(self, addon_relative_path: str) -> str:
        """Get a display path for an addon folder."""
        relative = self._normalize_relative_path(addon_relative_path)
        if self.is_sftp_mode():
            base = config.sftp_remote_path.rstrip("/") or "/"
            if relative:
                return f"{base}/{relative}"
            return base

        return str(self._local_path(relative))

    def get_local_absolute_path(self, relative_path: str) -> Optional[Path]:
        """Return an absolute local path when running in local mode."""
        if self.is_sftp_mode():
            return None

        local_path = self._local_path(relative_path)
        if local_path.exists():
            return local_path
        return None

    def close(self) -> None:
        """Close active SFTP/SSH connections."""
        with self._lock:
            if self._sftp_client is not None:
                try:
                    self._sftp_client.close()
                except Exception:
                    pass
                self._sftp_client = None

            if self._ssh_client is not None:
                try:
                    self._ssh_client.close()
                except Exception:
                    pass
                self._ssh_client = None

            self._connection_signature = None

    def exists(self, relative_path: str = "") -> bool:
        """Check whether a file or directory exists."""
        relative = self._normalize_relative_path(relative_path)

        if not self.is_sftp_mode():
            return self._local_path(relative).exists()

        with self._lock:
            try:
                sftp = self._ensure_sftp_connected_locked()
                sftp.stat(self._remote_path(relative))
                return True
            except Exception:
                return False

    def is_dir(self, relative_path: str = "") -> bool:
        """Check whether a path is a directory."""
        relative = self._normalize_relative_path(relative_path)

        if not self.is_sftp_mode():
            return self._local_path(relative).is_dir()

        with self._lock:
            try:
                sftp = self._ensure_sftp_connected_locked()
                details = sftp.stat(self._remote_path(relative))
                return stat.S_ISDIR(details.st_mode)
            except Exception:
                return False

    def list_dir(self, relative_path: str = "") -> List[ServerDirEntry]:
        """List entries in a directory."""
        relative = self._normalize_relative_path(relative_path)

        if not self.exists(relative) or not self.is_dir(relative):
            return []

        if not self.is_sftp_mode():
            entries = []
            for item in self._local_path(relative).iterdir():
                entries.append(
                    ServerDirEntry(
                        path=self.join(relative, item.name),
                        name=item.name,
                        is_dir=item.is_dir(),
                    )
                )
            return sorted(entries, key=lambda x: x.name.lower())

        with self._lock:
            sftp = self._ensure_sftp_connected_locked()
            entries = []
            for attr in sftp.listdir_attr(self._remote_path(relative)):
                entries.append(
                    ServerDirEntry(
                        path=self.join(relative, attr.filename),
                        name=attr.filename,
                        is_dir=stat.S_ISDIR(attr.st_mode),
                    )
                )
            return sorted(entries, key=lambda x: x.name.lower())

    def read_text(self, relative_path: str, encoding: str = "utf-8") -> str:
        """Read and return a text file."""
        relative = self._normalize_relative_path(relative_path)

        if not self.is_sftp_mode():
            return self._local_path(relative).read_text(encoding=encoding)

        with self._lock:
            sftp = self._ensure_sftp_connected_locked()
            with sftp.open(self._remote_path(relative), "r") as handle:
                content = handle.read()
                if isinstance(content, bytes):
                    return content.decode(encoding)
                return content

    def write_text(
        self, relative_path: str, content: str, encoding: str = "utf-8"
    ) -> None:
        """Write text content to a file."""
        relative = self._normalize_relative_path(relative_path)

        if not self.is_sftp_mode():
            local_path = self._local_path(relative)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(content, encoding=encoding)
            return

        with self._lock:
            sftp = self._ensure_sftp_connected_locked()
            parent = posixpath.dirname(relative)
            if parent:
                self._mkdirs_remote_locked(parent)
            with sftp.open(self._remote_path(relative), "w") as handle:
                handle.write(content)

    def read_json(self, relative_path: str):
        """Read a JSON file and return the parsed object."""
        return json.loads(self.read_text(relative_path))

    def write_json(self, relative_path: str, data) -> None:
        """Write an object as pretty-printed JSON."""
        self.write_text(relative_path, json.dumps(data, indent=2), encoding="utf-8")

    def mkdirs(self, relative_path: str) -> None:
        """Create a directory (and parents) if needed."""
        relative = self._normalize_relative_path(relative_path)

        if not relative:
            return

        if not self.is_sftp_mode():
            self._local_path(relative).mkdir(parents=True, exist_ok=True)
            return

        with self._lock:
            self._ensure_sftp_connected_locked()
            self._mkdirs_remote_locked(relative)

    def delete_tree(self, relative_path: str) -> bool:
        """Recursively delete a directory tree."""
        relative = self._normalize_relative_path(relative_path)
        if not relative:
            return False

        if not self.exists(relative):
            return False

        if not self.is_sftp_mode():
            try:
                shutil.rmtree(self._local_path(relative))
                return True
            except (IOError, OSError):
                return False

        try:
            return self._delete_remote_tree_via_ssh(relative)
        except Exception:
            return False

    def copy_dir_from_local(
        self,
        local_source: Path,
        destination_relative: str,
        event_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> List[str]:
        """Copy a local directory to the server root at the destination path.

        Returns a list of transfer-log lines describing how the copy was performed.
        """
        destination = self._normalize_relative_path(destination_relative)

        if not local_source.exists() or not local_source.is_dir():
            raise FileNotFoundError(f"Source directory not found: {local_source}")

        if not self.is_sftp_mode():
            shutil.copytree(local_source, self._local_path(destination))
            logs = [
                "Transfer method: local direct copy",
                f"Destination: {destination}",
            ]
            self._emit_transfer_logs(logs, event_callback)
            return logs

        with self._lock:
            sftp = self._ensure_sftp_connected_locked()
            file_count = self._count_local_files(
                local_source, stop_after=self.SFTP_ARCHIVE_FILE_THRESHOLD
            )
            if file_count > self.SFTP_ARCHIVE_FILE_THRESHOLD:
                return self._copy_dir_from_local_via_archive_locked(
                    sftp,
                    local_source,
                    destination,
                    event_callback=event_callback,
                    progress_callback=progress_callback,
                )
            return self._copy_dir_from_local_direct_locked(
                sftp,
                local_source,
                destination,
                event_callback=event_callback,
                progress_callback=progress_callback,
            )

    @staticmethod
    def _count_local_files(source_dir: Path, stop_after: Optional[int] = None) -> int:
        """Count files in a local directory tree.

        If `stop_after` is set, counting stops once the count exceeds it.
        """
        count = 0
        for _root, _dirs, files in os.walk(source_dir):
            count += len(files)
            if stop_after is not None and count > stop_after:
                return count
        return count

    def _copy_dir_from_local_direct_locked(
        self,
        sftp,
        local_source: Path,
        destination_relative: str,
        event_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> List[str]:
        """Copy a local directory directly file-by-file to remote (lock must be held)."""
        upload_items: List[Tuple[Path, str, int]] = []
        total_upload_bytes = 0
        for root, _dirs, files in os.walk(local_source):
            root_path = Path(root)
            relative_root = root_path.relative_to(local_source).as_posix()
            target_dir = destination_relative
            if relative_root != ".":
                target_dir = self.join(destination_relative, relative_root)
            for file_name in files:
                local_file = root_path / file_name
                file_size = os.path.getsize(local_file)
                upload_items.append(
                    (local_file, self.join(target_dir, file_name), file_size)
                )
                total_upload_bytes += file_size

        file_count = len(upload_items)
        self._mkdirs_remote_locked(destination_relative)

        for root, dirs, files in os.walk(local_source):
            root_path = Path(root)
            relative_root = root_path.relative_to(local_source).as_posix()
            target_dir = destination_relative
            if relative_root != ".":
                target_dir = self.join(destination_relative, relative_root)
                self._mkdirs_remote_locked(target_dir)

            for directory in dirs:
                self._mkdirs_remote_locked(self.join(target_dir, directory))

        completed_bytes = 0
        for local_file, remote_relative, file_size in upload_items:

            def on_file_progress(current: int, total: int) -> None:
                overall_current = completed_bytes + current
                self._emit_transfer_progress(
                    progress_callback,
                    "upload",
                    overall_current,
                    total_upload_bytes if total_upload_bytes > 0 else 1,
                    "Uploading files",
                )

            self._upload_file_resumable_with_reconnect_locked(
                local_file,
                remote_relative,
                event_callback=event_callback,
                progress_callback=on_file_progress,
            )
            completed_bytes += file_size
            self._emit_transfer_progress(
                progress_callback,
                "upload",
                completed_bytes,
                total_upload_bytes if total_upload_bytes > 0 else 1,
                "Uploading files",
            )
        logs = [
            "Transfer method: SFTP direct file upload",
            f"Files uploaded directly: {file_count}",
            f"Destination: {destination_relative}",
        ]
        self._emit_transfer_logs(logs, event_callback)
        return logs

    def _copy_dir_from_local_via_archive_locked(
        self,
        sftp,
        local_source: Path,
        destination_relative: str,
        event_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[str, int, int, str], None]] = None,
    ) -> List[str]:
        """Upload a directory as a zip archive then extract remotely (lock must be held)."""
        destination_parent_relative = posixpath.dirname(destination_relative)
        destination_folder_name = posixpath.basename(destination_relative)
        archive_name = f"{destination_folder_name}.zip"
        local_archive_path = Path(tempfile.gettempdir()) / archive_name
        remote_archive_name = archive_name
        remote_archive_relative = self.join(
            destination_parent_relative, remote_archive_name
        )
        destination_parent_absolute = self._remote_path(destination_parent_relative)
        file_count = self._count_local_files(
            local_source, stop_after=self.SFTP_ARCHIVE_FILE_THRESHOLD
        )
        transfer_log = [
            "Transfer method: SFTP archive upload",
            (
                f"File count exceeds threshold "
                f"{self.SFTP_ARCHIVE_FILE_THRESHOLD}; compressing before upload."
            ),
            (
                "Archive layout: includes top-level folder using "
                "make_archive(root_dir=..., base_dir=...)"
            ),
            f"Temporary archive upload path: {remote_archive_relative}",
        ]
        self._emit_transfer_logs(transfer_log, event_callback)

        try:
            self._emit_transfer_progress(
                progress_callback, "compression", 0, 1, "Compressing addon"
            )
            self._build_zip_archive_with_top_level(
                local_source, local_archive_path, destination_folder_name
            )
            self._emit_transfer_progress(
                progress_callback, "compression", 1, 1, "Compressing addon"
            )
            self._append_transfer_log(
                transfer_log, "Local zip archive created.", event_callback
            )
            if destination_parent_relative:
                self._mkdirs_remote_locked(destination_parent_relative)
            self._upload_file_resumable_with_reconnect_locked(
                local_archive_path,
                remote_archive_relative,
                event_callback=event_callback,
                progress_callback=lambda current, total: self._emit_transfer_progress(
                    progress_callback,
                    "upload",
                    current,
                    total if total > 0 else 1,
                    "Uploading archive",
                ),
            )
            self._append_transfer_log(
                transfer_log, "Zip archive uploaded to SFTP server.", event_callback
            )

            extracted, method = self._extract_remote_archive_with_single_command_locked(
                destination_parent_absolute,
                remote_archive_name,
                destination_folder_name,
            )
            if extracted:
                manifest_relative = self.join(destination_relative, "manifest.json")
                if not self._remote_file_exists_locked(manifest_relative):
                    self._append_transfer_log(
                        transfer_log,
                        "Post-extract validation failed (manifest.json missing); falling back to direct upload.",
                        event_callback,
                    )
                    extracted = False

            if not extracted:
                self._append_transfer_log(
                    transfer_log,
                    "Remote extractor unavailable; using streaming fallback extraction.",
                    event_callback,
                )
                # Reset destination before fallback extraction to avoid partial trees.
                if self.exists(destination_relative):
                    self._delete_remote_tree_locked(destination_relative)
                fallback_logs = self._copy_dir_from_local_direct_locked(
                    sftp,
                    local_source,
                    destination_relative,
                    event_callback=event_callback,
                    progress_callback=progress_callback,
                )
                for line in fallback_logs:
                    if line not in transfer_log:
                        transfer_log.append(line)
                self._append_transfer_log(
                    transfer_log, "Fallback extraction complete.", event_callback
                )
            else:
                self._append_transfer_log(
                    transfer_log,
                    f"Remote extraction complete using: {method}",
                    event_callback,
                )
        finally:
            try:
                if self._remove_remote_file_locked(remote_archive_relative):
                    self._append_transfer_log(
                        transfer_log,
                        "Temporary remote archive removed.",
                        event_callback,
                    )
            except Exception:
                pass
            try:
                if local_archive_path.exists():
                    local_archive_path.unlink()
                    self._append_transfer_log(
                        transfer_log, "Temporary local archive removed.", event_callback
                    )
            except Exception:
                pass
        self._append_transfer_log(
            transfer_log, f"Destination: {destination_relative}", event_callback
        )
        return transfer_log

    @staticmethod
    def _emit_transfer_logs(
        lines: List[str], event_callback: Optional[Callable[[str], None]]
    ) -> None:
        """Emit transfer log lines to callback when provided."""
        if not event_callback:
            return
        for line in lines:
            event_callback(line)

    @staticmethod
    def _append_transfer_log(
        transfer_log: List[str],
        line: str,
        event_callback: Optional[Callable[[str], None]],
    ) -> None:
        """Append a transfer log line and emit it."""
        transfer_log.append(line)
        if event_callback:
            event_callback(line)

    @staticmethod
    def _build_zip_archive_with_top_level(
        source_dir: Path, archive_path: Path, top_level_dir_name: str
    ) -> None:
        """Build a zip archive that contains a top-level directory.

        Uses shutil.make_archive(root_dir=..., base_dir=...) to mirror the
        upload example behavior.
        """
        archive_base = archive_path.with_suffix("")

        if source_dir.name == top_level_dir_name:
            shutil.make_archive(
                str(archive_base),
                "zip",
                root_dir=str(source_dir.parent),
                base_dir=source_dir.name,
            )
            return

        with tempfile.TemporaryDirectory(prefix="mcb_ziproot_") as temp_root:
            staged_root = Path(temp_root)
            staged_dir = staged_root / top_level_dir_name
            shutil.copytree(source_dir, staged_dir)
            shutil.make_archive(
                str(archive_base),
                "zip",
                root_dir=str(staged_root),
                base_dir=top_level_dir_name,
            )

    def _upload_file_resumable_with_reconnect_locked(
        self,
        local_path: Path,
        remote_relative_path: str,
        event_callback: Optional[Callable[[str], None]] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        """Upload a file with resume + reconnect retries (lock must be held)."""
        local_size = os.path.getsize(local_path)
        remote_absolute_path = self._remote_path(remote_relative_path)

        retries = 0
        while retries <= self.SFTP_UPLOAD_MAX_RETRIES:
            try:
                sftp = self._ensure_sftp_connected_locked()
                channel = sftp.get_channel()
                if channel:
                    channel.settimeout(self.SFTP_UPLOAD_CHANNEL_TIMEOUT_SECONDS)

                remote_size = 0
                try:
                    remote_size = int(sftp.stat(remote_absolute_path).st_size)
                except Exception:
                    remote_size = 0

                if remote_size > local_size:
                    try:
                        sftp.remove(remote_absolute_path)
                    except Exception:
                        pass
                    remote_size = 0

                if remote_size == local_size and local_size > 0:
                    if progress_callback:
                        progress_callback(local_size, local_size)
                    return

                mode = "ab" if remote_size > 0 else "wb"
                with (
                    open(local_path, "rb") as local_file,
                    sftp.open(remote_absolute_path, mode) as remote_file,
                ):
                    if remote_size > 0:
                        local_file.seek(remote_size)
                        try:
                            remote_file.seek(remote_size)
                        except Exception:
                            pass

                    while True:
                        chunk = local_file.read(self.SFTP_UPLOAD_CHUNK_SIZE)
                        if not chunk:
                            break
                        remote_file.write(chunk)
                        if progress_callback:
                            progress_callback(local_file.tell(), local_size)

                return
            except (socket.timeout, EOFError, OSError, Exception) as exc:
                retries += 1
                if retries > self.SFTP_UPLOAD_MAX_RETRIES:
                    raise RuntimeError(
                        f"Upload failed after {self.SFTP_UPLOAD_MAX_RETRIES} reconnect attempts: {exc}"
                    ) from exc

                if event_callback:
                    event_callback(
                        f"Upload interrupted, reconnecting (attempt {retries}/{self.SFTP_UPLOAD_MAX_RETRIES})..."
                    )
                self.close()
                time.sleep(self.SFTP_UPLOAD_RETRY_DELAY_SECONDS)

    @staticmethod
    def _emit_transfer_progress(
        progress_callback: Optional[Callable[[str, int, int, str], None]],
        step_name: str,
        current: int,
        total: int,
        label: str,
    ) -> None:
        """Emit transfer step progress when callback is provided."""
        if not progress_callback:
            return
        progress_callback(step_name, current, total, label)

    def _remove_remote_file_locked(self, relative_path: str) -> bool:
        """Remove a remote file if present (lock must be held)."""
        target = self._normalize_relative_path(relative_path)
        if not target:
            return False

        sftp = self._ensure_sftp_connected_locked()
        try:
            sftp.remove(self._remote_path(target))
            return True
        except Exception:
            return False

    def _extract_remote_archive_with_single_command_locked(
        self,
        destination_absolute: str,
        remote_archive_name: str,
        destination_folder_name: str,
    ) -> Tuple[bool, str]:
        """Extract archive with a single remote command (lock must be held)."""
        q_dest = shlex.quote(destination_absolute)
        q_archive_name = shlex.quote(remote_archive_name)
        q_folder_name = shlex.quote(destination_folder_name)

        # Keep extraction as a single exec command that changes to the target directory
        # and extracts the archive there, mirroring the provided upload example.
        commands = [
            (
                "unzip-semicolon-validated",
                f"cd '{q_dest}'; rm -rf '{q_folder_name}'; unzip '{q_archive_name}'",
            )
        ]

        for method, command in commands:
            if self._run_remote_command_locked(command):
                return True, method

        return False, ""

    def _run_remote_command_locked(self, command: str, timeout: int = 180) -> bool:
        """Execute a remote command through SSH (lock must be held)."""
        ssh = self._ssh_client
        if ssh is None:
            return False

        try:
            _stdin, stdout, _stderr = ssh.exec_command(command, timeout=timeout)
            return stdout.channel.recv_exit_status() == 0
        except Exception:
            return False

    def _run_remote_command_isolated(self, command: str, timeout: int = 180) -> bool:
        """Execute a remote command using an isolated SSH connection."""
        try:
            import paramiko
        except ImportError:
            return False

        connect_kwargs = {
            "hostname": config.sftp_host,
            "port": int(config.sftp_port or 22),
            "username": config.sftp_username,
            "timeout": config.sftp_timeout,
            "look_for_keys": True,
            "allow_agent": True,
        }
        if config.sftp_key_file:
            connect_kwargs["key_filename"] = config.sftp_key_file
        if config.sftp_password:
            connect_kwargs["password"] = config.sftp_password

        for _attempt in range(2):
            ssh = None
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(**connect_kwargs)
                _stdin, stdout, _stderr = ssh.exec_command(command, timeout=timeout)
                return stdout.channel.recv_exit_status() == 0
            except Exception:
                time.sleep(0.8)
            finally:
                if ssh is not None:
                    try:
                        ssh.close()
                    except Exception:
                        pass
        return False

    def _remote_file_exists_locked(self, relative_path: str) -> bool:
        """Check whether a remote file exists (lock must be held)."""
        normalized = self._normalize_relative_path(relative_path)
        if not normalized:
            return False

        sftp = self._ensure_sftp_connected_locked()
        try:
            sftp.stat(self._remote_path(normalized))
            return True
        except Exception:
            return False

    def _delete_remote_tree_via_ssh(self, relative_path: str) -> bool:
        """Delete a remote path using rm -rf over SSH."""
        normalized = self._normalize_relative_path(relative_path)
        if not normalized:
            return False

        remote_target = self._remote_path(normalized)
        if remote_target in {"", "/", "."}:
            return False

        parent_dir = posixpath.dirname(remote_target) or "/"
        target_name = posixpath.basename(remote_target)
        if not target_name:
            return False

        command = (
            f"cd {shlex.quote(parent_dir)}; "
            f"rm -rf -- {shlex.quote(target_name)}"
        )
        return self._run_remote_command_isolated(command, timeout=600)

    def get_local_file_copy(self, relative_path: str) -> Optional[Path]:
        """Get a local file path for a server file (downloads and caches in SFTP mode)."""
        relative = self._normalize_relative_path(relative_path)
        if not relative:
            return None

        if not self.exists(relative):
            return None

        if not self.is_sftp_mode():
            return self._local_path(relative)

        with self._lock:
            sftp = self._ensure_sftp_connected_locked()
            remote_path = self._remote_path(relative)
            details = sftp.stat(remote_path)
            if stat.S_ISDIR(details.st_mode):
                return None

            signature = self._get_connection_signature()
            cache_key = f"{signature}:{remote_path}"
            cached = self._file_cache.get(cache_key)
            mtime = int(details.st_mtime)
            size = int(details.st_size)

            if (
                cached
                and cached[0] == size
                and cached[1] == mtime
                and cached[2].exists()
            ):
                return cached[2]

            suffix = Path(relative).suffix
            cache_file = (
                self._cache_dir
                / f"{sha1(cache_key.encode('utf-8')).hexdigest()}{suffix}"
            )
            sftp.get(remote_path, str(cache_file))
            self._file_cache[cache_key] = (size, mtime, cache_file)
            return cache_file

    @staticmethod
    def validate_sftp_connection(
        host: str,
        port: int,
        username: str,
        password: str,
        key_file: str,
        remote_path: str,
        timeout: int = 10,
    ) -> Tuple[bool, str]:
        """Validate an SFTP connection with provided settings."""
        if not host:
            return False, "SFTP host is required."
        if not username:
            return False, "SFTP username is required."
        if not remote_path:
            return False, "Remote server path is required."

        try:
            import paramiko
        except ImportError:
            return False, "Missing dependency: install 'paramiko' for SFTP support."

        client = None
        sftp = None

        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": host,
                "port": int(port or 22),
                "username": username,
                "timeout": timeout,
                "look_for_keys": True,
                "allow_agent": True,
            }

            if key_file:
                connect_kwargs["key_filename"] = key_file
            if password:
                connect_kwargs["password"] = password

            client.connect(**connect_kwargs)
            sftp = client.open_sftp()

            remote = remote_path.strip() or "/"
            details = sftp.stat(remote)
            if not stat.S_ISDIR(details.st_mode):
                return False, "Remote path exists but is not a directory."

            return True, "Connection successful."
        except Exception as exc:
            return False, f"SFTP connection failed: {exc}"
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    def _normalize_relative_path(self, relative_path: str) -> str:
        """Normalize a relative path to a consistent format."""
        value = str(relative_path or "").strip().replace("\\", "/")
        if value in {"", ".", "/"}:
            return ""
        return value.strip("/")

    def _local_path(self, relative_path: str = "") -> Path:
        """Build an absolute local path from a relative server path."""
        base = Path(config.server_path)
        relative = self._normalize_relative_path(relative_path)
        if not relative:
            return base

        path = base
        for part in relative.split("/"):
            path = path / part
        return path

    def _remote_path(self, relative_path: str = "") -> str:
        """Build an absolute remote path from a relative server path."""
        root = config.sftp_remote_path.strip() or "/"
        relative = self._normalize_relative_path(relative_path)

        if not relative:
            return root

        if root == "/":
            return f"/{relative}"

        return posixpath.join(root.rstrip("/"), relative)

    def _get_connection_signature(self) -> str:
        """Build a signature for active SFTP settings."""
        return "|".join(
            [
                config.connection_type,
                config.sftp_host,
                str(config.sftp_port),
                config.sftp_username,
                config.sftp_remote_path,
                config.sftp_key_file,
                config.sftp_password,
            ]
        )

    def _ensure_sftp_connected_locked(self):
        """Ensure an active SFTP client exists (lock must be held)."""
        signature = self._get_connection_signature()
        if signature != self._connection_signature:
            self.close()
            self._file_cache.clear()
            self._connection_signature = signature

        needs_reconnect = self._sftp_client is None or self._ssh_client is None

        if not needs_reconnect:
            try:
                self._sftp_client.stat(self._remote_path(""))
            except Exception:
                needs_reconnect = True

        if not needs_reconnect:
            return self._sftp_client

        try:
            import paramiko
        except ImportError as exc:
            raise RuntimeError(
                "Missing dependency: install 'paramiko' for SFTP support."
            ) from exc

        self.close()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": config.sftp_host,
            "port": int(config.sftp_port or 22),
            "username": config.sftp_username,
            "timeout": config.sftp_timeout,
            "look_for_keys": True,
            "allow_agent": True,
        }

        if config.sftp_key_file:
            connect_kwargs["key_filename"] = config.sftp_key_file
        if config.sftp_password:
            connect_kwargs["password"] = config.sftp_password

        client.connect(**connect_kwargs)
        sftp = client.open_sftp()

        root_details = sftp.stat(self._remote_path(""))
        if not stat.S_ISDIR(root_details.st_mode):
            sftp.close()
            client.close()
            raise NotADirectoryError(
                "Configured remote server path is not a directory."
            )

        self._ssh_client = client
        self._sftp_client = sftp
        self._connection_signature = signature
        return sftp

    def _mkdirs_remote_locked(self, relative_path: str) -> None:
        """Create remote directories recursively (lock must be held)."""
        sftp = self._ensure_sftp_connected_locked()
        normalized = self._normalize_relative_path(relative_path)

        if not normalized:
            return

        parts = normalized.split("/")
        current = self._remote_path("")
        root = current

        for part in parts:
            if current in {"", "/"}:
                current = f"/{part}" if current == "/" else part
            else:
                current = posixpath.join(current, part)

            if root == "/" and not current.startswith("/"):
                current = f"/{current}"
            try:
                details = sftp.stat(current)
                if not stat.S_ISDIR(details.st_mode):
                    raise NotADirectoryError(
                        f"Remote path is not a directory: {current}"
                    )
            except FileNotFoundError:
                sftp.mkdir(current)
            except OSError:
                # Some SFTP implementations raise generic OSError for missing paths.
                try:
                    sftp.mkdir(current)
                except Exception:
                    details = sftp.stat(current)
                    if not stat.S_ISDIR(details.st_mode):
                        raise

    def _delete_remote_tree_locked(self, relative_path: str) -> None:
        """Recursively delete a remote file or directory (lock must be held)."""
        sftp = self._ensure_sftp_connected_locked()
        remote_path = self._remote_path(relative_path)
        details = sftp.stat(remote_path)

        if stat.S_ISDIR(details.st_mode):
            for entry in sftp.listdir_attr(remote_path):
                child_rel = self.join(relative_path, entry.filename)
                self._delete_remote_tree_locked(child_rel)
            sftp.rmdir(remote_path)
        else:
            sftp.remove(remote_path)


server_fs = ServerFilesystem()
