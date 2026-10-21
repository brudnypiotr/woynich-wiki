"""woynich-wiki: project knowledge base with a paper trail."""
import re
from pathlib import Path

try:  # one version, kept in pyproject.toml
    __version__ = re.search(r'(?m)^version\s*=\s*"([^"]+)"', (Path(__file__).resolve().parents[1] / "pyproject.toml")
                            .read_text(encoding="utf-8"))[1]
except (OSError, TypeError):
    __version__ = "unknown"
