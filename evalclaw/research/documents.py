"""Shared document reading and archive handling for construction and research."""
from __future__ import annotations

import codecs
import hashlib
import io
import json
import shutil
import stat
import subprocess
import tarfile
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath

MAX_RESOURCE_BYTES = 1024 * 1024 * 1024


def pdf_to_text(source: Path, target: Path) -> None:
    try:
        subprocess.run(["pdftotext", "-layout", str(source), str(target)],
                       check=True, timeout=60, capture_output=True)
    except FileNotFoundError as exc:
        raise ValueError("PDF text extraction requires pdftotext (Poppler).") from exc


def document_text(data: bytes, directory: Path, limit: int = 100_000) -> str | None:
    """Decode a bounded text/PDF snapshot without running resource content."""
    if data.startswith(b"%PDF-"):
        with tempfile.TemporaryDirectory(prefix="pdf-", dir=directory) as temporary:
            source = Path(temporary) / "source.pdf"
            target = Path(temporary) / "text.txt"
            source.write_bytes(data)
            pdf_to_text(source, target)
            with target.open(encoding="utf-8") as file:
                return file.read(limit + 1)
    try:
        return codecs.getincrementaldecoder("utf-8-sig")().decode(data, final=False)
    except UnicodeError:
        return None


class ResourceArchive:
    """Read ZIP/TAR members without resolving archive paths on the host."""

    def __init__(self, path: Path):
        self.archive = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else tarfile.open(path)
        self.zip = isinstance(self.archive, zipfile.ZipFile)
        self.entries = self.archive.infolist() if self.zip else self.archive.getmembers()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.archive.close()

    def describe(self, entry) -> dict:
        if self.zip:
            mode = entry.external_attr >> 16
            kind = "directory" if entry.is_dir() else "file"
            if stat.S_IFMT(mode) and not stat.S_ISREG(mode) and not entry.is_dir():
                kind = "link_or_special"
            return {"name": entry.filename, "size_bytes": entry.file_size, "kind": kind}
        kind = "file" if entry.isfile() else "directory" if entry.isdir() else "link_or_special"
        return {"name": entry.name, "size_bytes": entry.size, "kind": kind}

    def find(self, name: str):
        matches = [entry for entry in self.entries if self.describe(entry)["name"] == name]
        if len(matches) != 1:
            raise ValueError(f"Archive member must identify exactly one entry: {name}")
        return matches[0]

    def open(self, entry):
        if self.describe(entry)["kind"] != "file":
            raise ValueError("Only regular archive files can be read or extracted.")
        return self.archive.open(entry) if self.zip else self.archive.extractfile(entry)


def local_resource_path(work_dir: Path, value: str) -> Path:
    root = work_dir.resolve()
    candidate = Path(value)
    resolved = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ValueError("Resource must be an existing file inside the Builder directory.")
    return resolved


def page_payload(content: str, offset: int, *, max_chars: int, has_more: bool, **metadata) -> str:
    """Keep a paged tool response valid JSON even when text needs escaping."""
    while True:
        if not content and has_more:
            raise ValueError("Page metadata leaves no room for content; increase max_chars.")
        payload = {**metadata, "offset": offset, "content": content,
                   "next_offset": offset + len(content) if has_more else None}
        encoded = json.dumps(payload, ensure_ascii=False)
        if len(encoded) <= max_chars:
            return encoded
        if not content:
            raise ValueError("Page metadata exceeds the tool response budget.")
        content = content[:max(0, len(content) - max(1, (len(encoded) - max_chars + 1) // 2))]
        has_more = True


def read_document(path: Path, cache_dir: Path, *, member: str = "", offset: int = 0,
                  max_chars: int = 8000) -> str:
    if offset < 0:
        raise ValueError("offset must be nonnegative.")
    with ExitStack() as stack:
        if member:
            archive = stack.enter_context(ResourceArchive(path))
            entry = archive.find(member)
            size = archive.describe(entry)["size_bytes"]
            stream = stack.enter_context(archive.open(entry))
        else:
            size = path.stat().st_size
            stream = stack.enter_context(path.open("rb"))
        if size > MAX_RESOURCE_BYTES:
            raise ValueError("Document exceeds the 1 GiB processing limit.")
        prefix = stream.read(5)
        stream.seek(0)
        if prefix == b"%PDF-":
            version = f"{path}:{path.stat().st_mtime_ns}:{path.stat().st_size}:{member}"
            digest = hashlib.sha256(version.encode()).hexdigest()
            cache_dir.mkdir(parents=True, exist_ok=True)
            target = cache_dir / f"{digest}.txt"
            if not target.exists():
                with tempfile.TemporaryDirectory(prefix="pdf-", dir=cache_dir) as temporary:
                    source = Path(temporary) / "source.pdf"
                    converted = Path(temporary) / "text.txt"
                    with source.open("wb") as file:
                        shutil.copyfileobj(stream, file)
                    pdf_to_text(source, converted)
                    converted.replace(target)
            text_file = stack.enter_context(target.open(encoding="utf-8"))
        else:
            if b"\x00" in prefix:
                raise ValueError("Binary resource is not readable UTF-8 text or PDF.")
            text_file = stack.enter_context(io.TextIOWrapper(stream, encoding="utf-8-sig"))
        remaining = offset
        while remaining:
            skipped = text_file.read(min(remaining, 65536))
            if not skipped:
                break
            remaining -= len(skipped)
        content = text_file.read(max_chars + 1)
        return page_payload(content[:max_chars], offset, max_chars=max_chars,
                            has_more=len(content) > max_chars, path=str(path), member=member)


def list_archive(path: Path, *, offset: int = 0, limit: int = 50, max_chars: int = 50_000) -> dict:
    if offset < 0 or not 1 <= limit <= 200:
        raise ValueError("Use a nonnegative offset and a limit in 1..200.")
    with ResourceArchive(path) as archive:
        total = len(archive.entries)
        members = []
        result = {"path": str(path), "members": members, "total_members": total,
                  "next_offset": offset}
        for entry in archive.entries[offset:offset + limit]:
            members.append(archive.describe(entry))
            result["next_offset"] = offset + len(members)
            if len(json.dumps(result, ensure_ascii=False)) > max_chars:
                members.pop()
                break
        if not members and offset < total:
            raise ValueError("An archive member name exceeds the tool response budget.")
        end = offset + len(members)
        result["next_offset"] = end if end < total else None
        return result


def extract_archive(path: Path, destination_root: Path, *, members: list[str] | None = None) -> dict:
    """Extract selected regular files into a fresh directory, preserving their layout."""
    with ResourceArchive(path) as archive:
        names = members if members is not None else [
            archive.describe(entry)["name"] for entry in archive.entries
            if archive.describe(entry)["kind"] != "directory"
        ]
        if not 1 <= len(names) <= 64 or len(set(names)) != len(names):
            raise ValueError("Select 1..64 distinct regular archive files; use list_archive for larger archives.")
        selected = []
        total = 0
        for name in names:
            entry = archive.find(name)
            info = archive.describe(entry)
            relative = PurePosixPath(name.replace("\\", "/"))
            if not relative.parts or relative.is_absolute() or ".." in relative.parts or ":" in relative.parts[0] or info["kind"] != "file":
                raise ValueError(f"Unsafe archive member: {name}")
            total += info["size_bytes"]
            if total > MAX_RESOURCE_BYTES:
                raise ValueError("Selected archive files exceed the 1 GiB extraction limit.")
            selected.append((entry, relative, info["size_bytes"]))
        paths = [relative for _, relative, _ in selected]
        if len(set(paths)) != len(paths) or any(a in b.parents for a in paths for b in paths):
            raise ValueError("Selected archive paths conflict.")
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = Path(tempfile.mkdtemp(prefix="extracted-", dir=destination_root))
        files = []
        try:
            for entry, relative, size in selected:
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
                mode = (entry.external_attr >> 16) if archive.zip else entry.mode
                target.chmod(0o644 | (mode & 0o111))
                files.append({"path": str(target), "member": str(relative), "size_bytes": size})
        except Exception:
            shutil.rmtree(destination)
            raise
        return {"directory": str(destination), "files": files, "size_bytes": total}
