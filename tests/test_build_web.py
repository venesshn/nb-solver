import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from build_web import write_engine


def test_browser_engine_imports_from_its_zip_alone(tmp_path: Path):
    """The site loads the solver from this zip only; a module left out breaks it live."""
    archive = tmp_path / "nbsolver.zip"
    write_engine(archive)
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "import nbsolver.webapi as w; assert w.__file__.startswith(sys.argv[1]), w.__file__"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(archive)],
        check=False,
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
