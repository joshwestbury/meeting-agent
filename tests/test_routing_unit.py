from pathlib import Path

import pytest

from meeting_agent.errors import FolderValidationError
from meeting_agent.routing import resolve_vault_folder


def test_resolve_vault_folder_create_true_makes_directory(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    resolved = resolve_vault_folder(vault_root, "Work/Meetings/NewClient", create=True)

    assert resolved.is_dir()
    assert resolved == (vault_root / "Work/Meetings/NewClient").resolve()


def test_resolve_vault_folder_create_false_does_not_create_directory(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    resolved = resolve_vault_folder(vault_root, "Work/Meetings/Later", create=False)

    assert resolved == (vault_root / "Work/Meetings/Later").resolve()
    assert not resolved.exists()


def test_resolve_vault_folder_create_true_raises_when_mkdir_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()

    original_mkdir = Path.mkdir

    def _raise_mkdir(self: Path, *args, **kwargs):
        if self == (vault_root / "Blocked"):
            raise OSError("permission denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _raise_mkdir, raising=True)

    with pytest.raises(FolderValidationError, match="Could not create destination folder"):
        resolve_vault_folder(vault_root, "Blocked", create=True)
