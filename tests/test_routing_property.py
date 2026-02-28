from pathlib import Path
import string
import tempfile

import pytest
from hypothesis import given, strategies as st

from meeting_agent.errors import FolderValidationError
from meeting_agent.routing import resolve_vault_folder


_safe_segment = st.text(
    alphabet=st.sampled_from(list(string.ascii_letters + string.digits + "_-")),
    min_size=1,
    max_size=16,
)
_safe_relative_path = st.lists(_safe_segment, min_size=1, max_size=5).map("/".join)


@given(folder=_safe_relative_path)
def test_resolve_safe_relative_folder_property(folder: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp) / "vault"
        vault_root.mkdir()

        resolved = resolve_vault_folder(vault_root, folder)

        assert resolved == (vault_root / folder).resolve()
        assert resolved.is_absolute()
        assert resolved.relative_to(vault_root.resolve()) is not None


@given(folder=st.text(min_size=1, max_size=40).filter(lambda s: not s.startswith("/")))
def test_reject_traversal_segments_property(folder: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp) / "vault"
        vault_root.mkdir()

        candidate = f"{folder}/../escape"
        with pytest.raises(FolderValidationError):
            resolve_vault_folder(vault_root, candidate)


@given(suffix=st.text(min_size=1, max_size=20).filter(lambda s: "/" not in s))
def test_reject_absolute_paths_property(suffix: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        vault_root = Path(tmp) / "vault"
        vault_root.mkdir()

        with pytest.raises(FolderValidationError):
            resolve_vault_folder(vault_root, f"/{suffix}")

def test_reject_symlink_escape_tmp(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    link = vault_root / "escape"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(FolderValidationError):
        resolve_vault_folder(vault_root, "escape")
