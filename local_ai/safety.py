"""Application-level file guard, not an OS sandbox. See docs/SECURITY.md."""

import os
import re
import stat
import unicodedata
from pathlib import Path

from .config import LabError

ALLOWED_SUFFIXES = {".txt", ".md", ".json", ".csv"}
RESERVED = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
RESERVED |= {f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)}


def visible(text):
    """Escape terminal controls, bidi overrides, and zero-width format chars."""
    return "".join(c if c in "\n\t" or not unicodedata.category(c).startswith("C")
                   else f"\\u{ord(c):04x}" for c in str(text))


def checked_stat(path):
    try:
        s = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
        raise LabError("禁止符号链接、junction 和 Windows reparse point")
    if not stat.S_ISDIR(s.st_mode) and (not stat.S_ISREG(s.st_mode) or s.st_nlink != 1):
        raise LabError("只允许普通文件，禁止设备、管道和硬链接")
    return s


def check_chain(path):
    for part in [*reversed(path.parents), path]:
        checked_stat(part)


def private_directory(path):
    path = Path(os.path.abspath(path))  # Do not resolve away links before checking.
    check_chain(path)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    check_chain(path)
    if not path.is_dir():
        raise LabError("工作区必须是目录")
    return path


def open_regular(path, flags):
    check_chain(path)
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0)
                 | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
    try:
        s = os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
            raise LabError("目标必须是独占普通文件")
        current = checked_stat(path)
        if current is None or (current.st_dev, current.st_ino) != (s.st_dev, s.st_ino):
            raise LabError("文件在检查后发生变化")
        return fd
    except BaseException:
        os.close(fd)
        raise


class Workspace:
    def __init__(self, root, max_bytes=8192):
        self.root = private_directory(root)
        self.max_bytes = max_bytes

    def path(self, name, directory=False):
        check_chain(self.root)
        if directory and name == ".":
            return self.root
        if (not isinstance(name, str) or not 1 <= len(name) <= 180
                or "\\" in name or ":" in name or name.startswith("/")):
            raise LabError("只允许工作区内使用 / 分隔的相对路径")
        parts = name.split("/")
        for part in parts:
            if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}", part)
                    or part.endswith(".") or part.split(".")[0].upper() in RESERVED):
                raise LabError("路径仅允许英文、数字、_、-、点；禁止隐藏文件和保留名称")
        path = self.root.joinpath(*parts)
        if not directory and path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise LabError("只允许 .txt/.md/.json/.csv 文件")
        check_chain(path)
        # Defense in depth; lstat above prevents links being hidden by resolve().
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise LabError("路径超出工作区")
        return path

    def read(self, name):
        path = self.path(name)
        fd = open_regular(path, os.O_RDONLY)
        with os.fdopen(fd, "rb") as stream:
            data = stream.read(self.max_bytes + 1)
        if len(data) > self.max_bytes:
            raise LabError("文件超过字节上限")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LabError("仅支持 UTF-8 文本") from exc

    def list(self, name="."):
        path = self.path(name, directory=True)
        found = []
        # Bounded scanning, not a recursive traversal.
        with os.scandir(path) as entries:
            for index, entry in enumerate(entries):
                if index >= 200:
                    raise LabError("目录超过 200 项，请使用较小的实验目录")
                relative = Path(entry.path).relative_to(self.root).as_posix()
                try:
                    s = checked_stat(Path(entry.path))
                    if s is None:
                        continue
                    directory = stat.S_ISDIR(s.st_mode)
                    self.path(relative, directory=directory)
                    found.append({"path": relative, "type": "directory" if directory else "file"})
                except LabError:
                    continue
        return sorted(found, key=lambda x: x["path"])

    def validate_create(self, name, content):
        path = self.path(name)
        if path.exists():
            raise LabError("文件已存在；不允许覆盖，请换一个文件名")
        if not path.parent.is_dir():
            raise LabError("父目录不存在；请由用户手动创建")
        if not isinstance(content, str) or len(content.encode("utf-8")) > self.max_bytes:
            raise LabError("写入内容不是文本或超过字节上限")
        return path

    def create(self, name, content):
        path = self.validate_create(name, content)  # Recheck after human approval.
        fd = open_regular(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        return {"path": name, "bytes": len(content.encode("utf-8")), "created": True}
