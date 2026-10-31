import io
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


class FakeResponse(io.BytesIO):
    """A bytes buffer that also works as a context manager, like urlopen's response."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def fake_opener_factory(files: dict[str, bytes], ckan: dict[str, dict] | None = None):
    """Build an opener that serves ``files`` by URL and answers CKAN resource_show from ``ckan``."""
    calls: list[str] = []

    def opener(url: str) -> FakeResponse:
        calls.append(url)
        if "/resource_show?id=" in url:
            rid = url.rsplit("=", 1)[-1]
            meta = (ckan or {}).get(rid)
            if meta is None:
                return FakeResponse(json.dumps({"success": False}).encode())
            return FakeResponse(json.dumps({"success": True, "result": meta}).encode())
        if url not in files:
            raise OSError(f"unexpected url {url}")
        return FakeResponse(files[url])

    opener.calls = calls  # type: ignore[attr-defined]
    return opener


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES
