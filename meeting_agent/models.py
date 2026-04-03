from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

import httpx

from meeting_agent.errors import ConfigError


@dataclass(frozen=True)
class ModelSpec:
    repo_id: str
    filename_prefix: str
    small_size_guidance: str


DEFAULT_MODEL_REPO = "LiquidAI/LFM2-2.6B-Transcript-GGUF"
DEFAULT_MODEL_VARIANT = "Q4_K_M"
LARGE_MODEL_REPO = "LiquidAI/LFM2-24B-A2B-GGUF"
QWEN_MEDIUM_MODEL_REPO = "bartowski/Qwen2.5-7B-Instruct-GGUF"

MODEL_SPECS: dict[str, ModelSpec] = {
    DEFAULT_MODEL_REPO: ModelSpec(
        repo_id=DEFAULT_MODEL_REPO,
        filename_prefix="LFM2-2.6B-Transcript",
        small_size_guidance="approximately 1.5-2.7 GB",
    ),
    LARGE_MODEL_REPO: ModelSpec(
        repo_id=LARGE_MODEL_REPO,
        filename_prefix="LFM2-24B-A2B",
        small_size_guidance="approximately 13.5-25.4 GB (variant dependent)",
    ),
    QWEN_MEDIUM_MODEL_REPO: ModelSpec(
        repo_id=QWEN_MEDIUM_MODEL_REPO,
        filename_prefix="Qwen2.5-7B-Instruct",
        small_size_guidance="approximately 4.4-6.3 GB (variant dependent)",
    ),
}


@dataclass(frozen=True)
class ModelPullResult:
    output_path: Path
    downloaded: bool


@dataclass(frozen=True)
class ModelDoctorReport:
    runtime_installed: bool
    runtime_path: str | None
    model_present: bool
    model_path: Path
    server_reachable: bool


def resolve_model_filename(repo_id: str, variant: str) -> str:
    spec = MODEL_SPECS.get(repo_id)
    if spec is None:
        raise ConfigError(
            f"Unknown model repo '{repo_id}'. Supported: {', '.join(sorted(MODEL_SPECS))}"
        )
    clean_variant = variant.strip()
    if not clean_variant:
        raise ConfigError("Model variant must not be empty")
    return f"{spec.filename_prefix}-{clean_variant}.gguf"


def build_huggingface_model_url(repo_id: str, filename: str) -> str:
    return f"https://huggingface.co/{repo_id}/resolve/main/{filename}"


def resolve_model_output_path(model_cache_dir: Path, repo_id: str, filename: str) -> Path:
    repo_slug = repo_id.replace("/", "--")
    return model_cache_dir.expanduser() / repo_slug / filename


def pull_model(
    *,
    repo_id: str,
    variant: str,
    model_cache_dir: Path,
    force: bool = False,
    client: httpx.Client | None = None,
) -> ModelPullResult:
    filename = resolve_model_filename(repo_id, variant)
    output_path = resolve_model_output_path(model_cache_dir, repo_id, filename)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not force:
        return ModelPullResult(output_path=output_path, downloaded=False)

    url = build_huggingface_model_url(repo_id, filename)
    created_client = client is None
    http_client = client or httpx.Client(follow_redirects=True)
    try:
        try:
            with http_client.stream("GET", url, timeout=120.0) as response:
                if response.status_code >= 400:
                    raise ConfigError(
                        f"Model download failed: HTTP {response.status_code} for {repo_id}/{filename}"
                    )
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=output_path.parent,
                    prefix=f"{output_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as tmp:
                    for chunk in response.iter_bytes():
                        if chunk:
                            tmp.write(chunk)
                    tmp_name = tmp.name
        except httpx.TransportError as exc:
            raise ConfigError(f"Model download failed: {exc}") from exc
    finally:
        if created_client:
            http_client.close()

    Path(tmp_name).replace(output_path)
    return ModelPullResult(output_path=output_path, downloaded=True)


def list_installed_models(model_cache_dir: Path) -> list[Path]:
    root = model_cache_dir.expanduser()
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.gguf") if path.is_file())


def run_models_doctor(
    *,
    model_cache_dir: Path,
    repo_id: str,
    variant: str,
    server_url: str,
) -> ModelDoctorReport:
    runtime_path = shutil.which("llama-server")
    runtime_installed = runtime_path is not None
    filename = resolve_model_filename(repo_id, variant)
    model_path = resolve_model_output_path(model_cache_dir, repo_id, filename)
    model_present = model_path.exists()
    server_reachable = _check_server_reachable(server_url)

    return ModelDoctorReport(
        runtime_installed=runtime_installed,
        runtime_path=runtime_path,
        model_present=model_present,
        model_path=model_path,
        server_reachable=server_reachable,
    )


def _check_server_reachable(server_url: str) -> bool:
    from meeting_agent.llm import llm_openai_runtime_health_ok

    return llm_openai_runtime_health_ok(server_url, timeout=5.0)


def model_size_guidance(repo_id: str) -> str:
    spec = MODEL_SPECS.get(repo_id)
    if spec is None:
        return "size guidance unavailable for this model"
    return spec.small_size_guidance
