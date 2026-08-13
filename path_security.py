from pathlib import Path, PurePosixPath


class UnsafePathError(ValueError):
    """Raised when an untrusted path escapes or traverses a trusted root."""


def resolve_under(root: str | Path, untrusted_path: str | None, *, allow_root: bool = True) -> Path:
    """Resolve an API path beneath root without allowing traversal or symlinks."""
    root_path = Path(root).resolve()
    raw_path = str(untrusted_path or "/")
    if "\x00" in raw_path:
        raise UnsafePathError("path contains a null byte")

    normalized = raw_path.replace("\\", "/").lstrip("/")
    parts = PurePosixPath(normalized or ".").parts
    if any(part == ".." for part in parts):
        raise UnsafePathError("parent traversal is not allowed")

    lexical_path = root_path.joinpath(*[part for part in parts if part not in {"", "."}])
    current = root_path
    for part in lexical_path.relative_to(root_path).parts:
        current = current / part
        if current.is_symlink():
            raise UnsafePathError("symbolic links are not allowed")

    resolved = lexical_path.resolve(strict=False)
    try:
        relative = resolved.relative_to(root_path)
    except ValueError as exc:
        raise UnsafePathError("path escapes the allowed root") from exc

    if not allow_root and relative == Path("."):
        raise UnsafePathError("the root directory is not allowed")
    return resolved


def validate_child_name(name: str | None) -> str:
    """Validate a single file name supplied by a multipart upload."""
    value = str(name or "")
    if not value or "\x00" in value or value in {".", ".."}:
        raise UnsafePathError("invalid file name")
    if "/" in value or "\\" in value or Path(value).name != value:
        raise UnsafePathError("file name must not contain a path")
    return value
