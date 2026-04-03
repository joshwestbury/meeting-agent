from pathlib import Path

import httpx
import pytest

from meeting_agent.errors import ConfigError
from meeting_agent.models import (
    DEFAULT_MODEL_REPO,
    DEFAULT_MODEL_VARIANT,
    LARGE_MODEL_REPO,
    QWEN_MEDIUM_MODEL_REPO,
    build_huggingface_model_url,
    list_installed_models,
    model_size_guidance,
    pull_model,
    resolve_model_filename,
    run_models_doctor,
)


def test_resolve_model_filename_for_known_models() -> None:
    assert resolve_model_filename(DEFAULT_MODEL_REPO, "Q4_K_M") == "LFM2-2.6B-Transcript-Q4_K_M.gguf"
    assert resolve_model_filename(LARGE_MODEL_REPO, "Q4_0") == "LFM2-24B-A2B-Q4_0.gguf"
    assert resolve_model_filename(QWEN_MEDIUM_MODEL_REPO, "Q5_K_M") == "Qwen2.5-7B-Instruct-Q5_K_M.gguf"


def test_resolve_model_filename_rejects_unknown_model() -> None:
    with pytest.raises(ConfigError, match="Unknown model repo"):
        resolve_model_filename("owner/unknown", "Q4_K_M")


def test_build_huggingface_model_url() -> None:
    url = build_huggingface_model_url(DEFAULT_MODEL_REPO, "model.gguf")
    assert url == "https://huggingface.co/LiquidAI/LFM2-2.6B-Transcript-GGUF/resolve/main/model.gguf"


def test_pull_model_downloads_to_cache(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"abc123")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = pull_model(
        repo_id=DEFAULT_MODEL_REPO,
        variant=DEFAULT_MODEL_VARIANT,
        model_cache_dir=tmp_path,
        client=client,
    )
    client.close()

    assert result.downloaded is True
    assert result.output_path.exists()
    assert result.output_path.read_bytes() == b"abc123"


def test_pull_model_skips_when_already_present(tmp_path: Path) -> None:
    filename = resolve_model_filename(DEFAULT_MODEL_REPO, DEFAULT_MODEL_VARIANT)
    model_path = tmp_path / "LiquidAI--LFM2-2.6B-Transcript-GGUF" / filename
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"existing")

    result = pull_model(
        repo_id=DEFAULT_MODEL_REPO,
        variant=DEFAULT_MODEL_VARIANT,
        model_cache_dir=tmp_path,
    )
    assert result.downloaded is False
    assert result.output_path == model_path


def test_pull_model_surfaces_http_error(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ConfigError, match="HTTP 404"):
        pull_model(
            repo_id=DEFAULT_MODEL_REPO,
            variant=DEFAULT_MODEL_VARIANT,
            model_cache_dir=tmp_path,
            client=client,
        )
    client.close()


def test_list_installed_models_returns_sorted_files(tmp_path: Path) -> None:
    a = tmp_path / "a.gguf"
    b = tmp_path / "nested" / "b.gguf"
    b.parent.mkdir(parents=True)
    a.write_text("a", encoding="utf-8")
    b.write_text("b", encoding="utf-8")
    paths = list_installed_models(tmp_path)
    assert paths == [a, b]


def test_run_models_doctor_reports_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    filename = resolve_model_filename(DEFAULT_MODEL_REPO, DEFAULT_MODEL_VARIANT)
    model_path = tmp_path / "LiquidAI--LFM2-2.6B-Transcript-GGUF" / filename
    model_path.parent.mkdir(parents=True, exist_ok=True)
    model_path.write_bytes(b"data")

    monkeypatch.setattr("meeting_agent.models.shutil.which", lambda _: "/usr/local/bin/llama-server")
    monkeypatch.setattr(
        "meeting_agent.llm.httpx.get",
        lambda *_args, **_kwargs: httpx.Response(200, json={"object": "list", "data": []}),
    )

    report = run_models_doctor(
        model_cache_dir=tmp_path,
        repo_id=DEFAULT_MODEL_REPO,
        variant=DEFAULT_MODEL_VARIANT,
        server_url="http://127.0.0.1:8080",
    )
    assert report.runtime_installed is True
    assert report.model_present is True
    assert report.server_reachable is True


def test_model_size_guidance_includes_known_ranges() -> None:
    assert "1.5-2.7 GB" in model_size_guidance(DEFAULT_MODEL_REPO)
    assert "13.5-25.4 GB" in model_size_guidance(LARGE_MODEL_REPO)
    assert "4.4-6.3 GB" in model_size_guidance(QWEN_MEDIUM_MODEL_REPO)
