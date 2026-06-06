"""Recursive folder discovery and folder-relative photo identifiers."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Container

DEFAULT_LOAD_RECURSIVELY = True
WINDOWS_DRIVE_PART_LENGTH = 2


def normalize_load_recursively(load_recursively: object) -> bool:
    """
    Return a supported recursive-loading preference.

    Parameters
    ----------
    load_recursively : object
        Raw preference value. Booleans are returned directly. String values
        such as ``"true"``, ``"yes"``, ``"on"``, and ``"1"`` map to ``True``;
        ``"false"``, ``"no"``, ``"off"``, and ``"0"`` map to ``False``.

    Returns
    -------
    bool
        Normalized recursive-loading preference. Unsupported values fall back
        to :data:`DEFAULT_LOAD_RECURSIVELY`.
    """
    if isinstance(load_recursively, bool):
        return load_recursively

    if isinstance(load_recursively, str):
        normalized = load_recursively.strip().casefold()
        if normalized in {'1', 'true', 'yes', 'on'}:
            return True

        if normalized in {'0', 'false', 'no', 'off'}:
            return False

    return DEFAULT_LOAD_RECURSIVELY


def discover_photo_files(
        folder: Path,
        supported_extensions: set[str],
        *,
        load_recursively: object = DEFAULT_LOAD_RECURSIVELY,
) -> list[Path]:
    """
    Return supported photo files in deterministic relative-path order.

    Parameters
    ----------
    folder : Path
        Folder selected by the user. The path is expanded and resolved before
        scanning.
    supported_extensions : set[str]
        Lowercase file extensions that should be treated as photo files.
    load_recursively : object, default=DEFAULT_LOAD_RECURSIVELY
        Raw recursive-loading preference. Values are normalized with
        :func:`normalize_load_recursively`.

    Returns
    -------
    list[Path]
        Supported files sorted by folder-relative POSIX path. When recursive
        loading is disabled, only direct child files are returned. Recursive
        scans skip symlinked directories.
    """
    root = folder.expanduser().resolve()
    recursive = normalize_load_recursively(load_recursively)
    if recursive:
        files = _recursive_photo_files(root, supported_extensions)
    else:
        files = [
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.lower() in supported_extensions
        ]

    return sorted(
        files,
        key=lambda path: (
            relative_posix_path(root, path).casefold(),
            relative_posix_path(root, path),
        ),
    )


def relative_posix_path(folder: Path, path: Path) -> str:
    """
    Return ``path`` relative to ``folder`` using POSIX separators.

    Parameters
    ----------
    folder : Path
        Root folder that owns the photo library metadata file.
    path : Path
        File path under ``folder``.

    Returns
    -------
    str
        Relative path using ``/`` separators, including the file extension.

    Raises
    ------
    ValueError
        Raised by :meth:`pathlib.Path.relative_to` if ``path`` is not under
        ``folder``.
    """
    return path.relative_to(folder).as_posix()


def relative_photo_id(folder: Path, path: Path) -> str:
    """
    Return the folder-relative extensionless POSIX photo identifier.

    Parameters
    ----------
    folder : Path
        Root folder that owns the loaded photo set.
    path : Path
        Photo file path under ``folder``.

    Returns
    -------
    str
        Folder-relative POSIX path with the final file suffix removed. For
        example, ``subfolder/IMG_1234.JPG`` becomes ``subfolder/IMG_1234``.

    Raises
    ------
    ValueError
        Raised by :func:`relative_posix_path` if ``path`` is not under
        ``folder``.
    """
    relative_path = relative_posix_path(folder, path)
    suffix = path.suffix
    if suffix:
        return relative_path[: -len(suffix)]

    return relative_path


def relative_photo_group_key(folder: Path, path: Path) -> tuple[str, str]:
    """
    Return the grouping key for related files in one relative folder.

    Folder loading groups companion files such as JPEG+RAW pairs before it
    creates one :class:`PhotoRecord`. That grouping must be case-insensitive
    for the final stem so ``IMG_1000.JPG`` and ``img_1000.CR3`` can represent
    the same photo. It must not case-fold the folder path, because recursive
    loading can scan case-sensitive filesystems where ``Trip/IMG_1000`` and
    ``trip/IMG_1000`` are different photos.

    The returned key therefore preserves the relative parent path exactly and
    case-folds only the extensionless filename.

    Parameters
    ----------
    folder : Path
        Resolved root folder that owns the loaded photo set.
    path : Path
        Photo file path under ``folder``.

    Returns
    -------
    tuple[str, str]
        ``(relative_parent, casefolded_stem)``. Root-level photos use an empty
        string for ``relative_parent``.

    Raises
    ------
    ValueError
        Raised by :func:`relative_photo_id` if ``path`` is not under
        ``folder``.
    """
    photo_id = PurePosixPath(relative_photo_id(folder, path))
    parent = photo_id.parent.as_posix()
    if parent == '.':
        parent = ''

    return parent, photo_id.name.casefold()


def normalize_photo_identifier(value: object) -> str | None:
    """
    Normalize a persisted photo id/key while preserving subfolders.

    Parameters
    ----------
    value : object
        Persisted photo ID or metadata key. Windows separators are accepted and
        converted to ``/``.

    Returns
    -------
    str | None
        Safe POSIX photo ID with the final suffix removed, or ``None`` when the
        input is empty, absolute, drive-qualified, or contains ``.`` or ``..``
        path components.
    """
    return _normalize_posix_path(value, strip_suffix=True)


def normalize_photo_identifier_for_valid_ids(
        value: object, valid_photo_ids: Container[str]
) -> str | None:
    """
    Resolve a persisted photo identifier against current loaded photo IDs.

    This helper is used when the caller already knows which photo IDs exist in
    the loaded folder. That extra context lets migration logic distinguish a
    current extensionless ID from an old filename-style key.

    Resolution order is intentionally conservative:

    1. Normalize separators and validate path safety without stripping a
       suffix; accept the value only if it exactly matches a loaded photo ID.
    2. Fall back to :func:`normalize_photo_identifier`, which strips a final
       suffix for legacy keys such as ``IMG_0001.JPG``.

    The exact-match step is necessary for valid dotted stems such as
    ``IMG.0001``. Without the loaded-ID check, generic suffix stripping would
    reduce that ID to ``IMG`` and make saved metadata or scene groups vanish.

    Parameters
    ----------
    value : object
        Persisted photo ID, legacy filename key, or scene photo ID to resolve.
        Windows separators are accepted and converted to ``/``.
    valid_photo_ids : Container[str]
        Current loaded photo IDs that are safe to return.

    Returns
    -------
    str | None
        Matching current photo ID, or ``None`` when ``value`` is unsafe or does
        not resolve to a loaded photo ID.
    """
    exact = _normalize_posix_path(value, strip_suffix=False)
    if exact is not None and exact in valid_photo_ids:
        return exact

    legacy = normalize_photo_identifier(value)
    if legacy is not None and legacy in valid_photo_ids:
        return legacy

    return None


def normalize_relative_file_path(value: object) -> str | None:
    """
    Normalize a persisted folder-relative file path.

    Parameters
    ----------
    value : object
        Persisted relative file path. Windows separators are accepted and
        converted to ``/``.

    Returns
    -------
    str | None
        Safe POSIX relative file path with any suffix preserved, or ``None``
        when the input is empty, absolute, drive-qualified, or contains ``.``
        or ``..`` path components.
    """
    return _normalize_posix_path(value, strip_suffix=False)


def resolve_relative_path(folder: Path, relative_path: object) -> Path:
    """
    Resolve a safe POSIX-style relative path under ``folder``.

    Parameters
    ----------
    folder : Path
        Root folder that owns the path.
    relative_path : object
        Relative path value to normalize and join under ``folder``.

    Returns
    -------
    Path
        Platform-native path under ``folder``.

    Raises
    ------
    ValueError
        If ``relative_path`` cannot be normalized into a safe folder-relative
        path.
    """
    normalized = normalize_relative_file_path(relative_path)
    if normalized is None:
        raise ValueError(f'Unsafe relative path: {relative_path}')

    return folder.joinpath(*PurePosixPath(normalized).parts)


def exif_metadata_for_path(
        exif_map: dict[str, dict[str, Any]], path: Path
) -> dict[str, Any]:
    """
    Look up EXIF metadata by resolved path, with basename fallback.

    Parameters
    ----------
    exif_map : dict[str, dict[str, Any]]
        Mapping returned by EXIF readers or tests. Production data is keyed by
        resolved path and basename; older test stubs may only use basenames.
    path : Path
        File path whose metadata should be returned.

    Returns
    -------
    dict[str, Any]
        Metadata dictionary for ``path``. An empty dictionary is returned when
        no matching record exists.
    """
    return (
        exif_map.get(str(path.expanduser().resolve()))
        or exif_map.get(path.as_posix())
        or exif_map.get(path.name)
        or {}
    )


def _recursive_photo_files(
        folder: Path, supported_extensions: set[str]
) -> list[Path]:
    """
    Return recursively discovered files while pruning symlinked folders.

    Parameters
    ----------
    folder : Path
        Resolved root folder to walk.
    supported_extensions : set[str]
        Lowercase photo extensions to include.

    Returns
    -------
    list[Path]
        Supported photo files found under ``folder``.
    """
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        current_dir = Path(dirpath)
        # Keep recursive scans within real child folders only. Symlinked
        # directories could point outside the selected root, which would make
        # folder-relative photo IDs misleading and unsafe to resolve later.
        dirnames[:] = [
            name for name in dirnames if not (current_dir / name).is_symlink()
        ]
        for filename in filenames:
            path = current_dir / filename
            if path.is_file() and path.suffix.lower() in supported_extensions:
                files.append(path)

    return files


def _normalize_posix_path(value: object, *, strip_suffix: bool) -> str | None:
    """
    Normalize and validate a persisted POSIX-style relative path.

    Parameters
    ----------
    value : object
        Raw path-like value to normalize.
    strip_suffix : bool
        Whether to remove the final file suffix from the path.

    Returns
    -------
    str | None
        Safe POSIX relative path, or ``None`` for unsafe or empty input.
    """
    raw = str(value).replace('\\', '/').strip()
    if not raw:
        return None

    path = PurePosixPath(raw)
    parts = path.parts
    # Persisted IDs are later resolved under the selected folder. Reject paths
    # that could escape that folder or represent platform-specific absolutes.
    if (
        path.is_absolute()
        or not parts
        or any(part in {'', '.', '..'} for part in parts)
        or _looks_like_windows_drive(parts[0])
    ):
        return None

    if strip_suffix and path.suffix:
        path = path.with_suffix('')

    return path.as_posix()


def _looks_like_windows_drive(part: str) -> bool:
    """
    Return whether ``part`` looks like a Windows drive component.

    Parameters
    ----------
    part : str
        First POSIX path component to inspect.

    Returns
    -------
    bool
        ``True`` when ``part`` has the form ``C:``.
    """
    return len(part) == WINDOWS_DRIVE_PART_LENGTH and part[1] == ':'
