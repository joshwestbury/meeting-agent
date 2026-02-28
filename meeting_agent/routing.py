from pathlib import Path

from meeting_agent.errors import FolderValidationError


def resolve_vault_folder(vault_root: Path, folder_input: str, *, create: bool = False) -> Path:
    """Validate user-supplied folder and return absolute resolved folder path."""
    folder_raw = (folder_input or "").strip()
    if not folder_raw:
        raise FolderValidationError("Folder is required")

    folder_path = Path(folder_raw)
    if folder_path.is_absolute():
        raise FolderValidationError("Folder must be vault-relative, not absolute")

    if any(part == ".." for part in folder_path.parts):
        raise FolderValidationError("Folder traversal is not allowed")

    normalized = Path(*[part for part in folder_path.parts if part not in ("", ".")])
    candidate = (vault_root / normalized).resolve()
    root_resolved = vault_root.resolve()

    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise FolderValidationError("Folder resolves outside vault root") from exc

    if create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FolderValidationError(f"Could not create destination folder: {candidate}") from exc

    return candidate
