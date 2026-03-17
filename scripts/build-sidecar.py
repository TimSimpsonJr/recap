"""Build the recap pipeline as a PyInstaller sidecar binary for Tauri."""
import subprocess
import shutil
import platform
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
BINARIES_DIR = REPO_ROOT / "src-tauri" / "binaries"


def get_target_triple() -> str:
    """Get the Rust target triple for the current platform."""
    result = subprocess.run(
        ["rustc", "--print", "host-tuple"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def build_sidecar() -> None:
    target_triple = get_target_triple()
    sidecar_name = f"recap-pipeline-{target_triple}"

    if platform.system() == "Windows":
        sidecar_name += ".exe"

    print(f"Building sidecar: {sidecar_name}")

    # Run PyInstaller
    subprocess.run(
        [
            "pyinstaller",
            "--onefile",
            "--name", sidecar_name.replace(".exe", "") if platform.system() == "Windows" else sidecar_name,
            str(REPO_ROOT / "run_pipeline.py"),
        ],
        cwd=str(REPO_ROOT),
        check=True,
    )

    # Copy to src-tauri/binaries/
    BINARIES_DIR.mkdir(parents=True, exist_ok=True)
    dist_path = REPO_ROOT / "dist" / sidecar_name
    dest_path = BINARIES_DIR / sidecar_name
    shutil.copy2(str(dist_path), str(dest_path))
    print(f"Sidecar copied to: {dest_path}")


if __name__ == "__main__":
    build_sidecar()
