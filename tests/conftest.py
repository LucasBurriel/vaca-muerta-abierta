import io
import json
from datetime import date
from pathlib import Path

import duckdb
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


# --- F6: a fake repo with the prices table (both sources) and one without it ------------------------------------------


def _tabla_precios_fixture():
    from vma.precios import fuentes as F

    r, meta = F.leer_regalias_crudo(FIXTURES / "precios" / "regalias_crudo.zip")
    g = F.leer_precios_gas(FIXTURES / "precios" / "precios_gas.csv")
    return F.construir(
        r, g, fecha_descarga="2026-11-02", version="2026-10-31", fecha_realizacion=meta["fecha_realizacion"]
    )


@pytest.fixture(scope="module")
def raiz_precios(tmp_path_factory) -> Path:
    """The F4 fake repo (tests/test_consulta.py) plus the prices table in both sources."""
    import test_consulta as TC

    from vma import site as S

    root = tmp_path_factory.mktemp("repo_precios")
    pub = root / "data" / "publicado" / "2026-10-31"
    pub.mkdir(parents=True)
    con = duckdb.connect()
    t = _tabla_precios_fixture()
    for name, df in (
        ("pozos", TC._master()),
        ("indicadores", TC._ind()),
        ("curvas_tipo", TC._curvas()),
        ("precios", t),
    ):
        con.register("t", df)
        con.execute(f"COPY t TO '{(pub / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        con.unregister("t")
    S.build_site_data(
        root / "site" / "data",
        TC._master(),
        TC._ind(),
        TC._curvas(),
        TC.MANIFEST,
        "2026-10-31",
        today=date(2026, 10, 31),
        precios=t,
    )
    return root


@pytest.fixture(scope="module")
def raiz_sin_precios(tmp_path_factory) -> Path:
    import test_consulta as TC

    from vma import site as S

    root = tmp_path_factory.mktemp("repo_sin_precios")
    pub = root / "data" / "publicado" / "2026-10-31"
    pub.mkdir(parents=True)
    con = duckdb.connect()
    for name, df in (("pozos", TC._master()), ("indicadores", TC._ind()), ("curvas_tipo", TC._curvas())):
        con.register("t", df)
        con.execute(f"COPY t TO '{(pub / f'{name}.parquet').as_posix()}' (FORMAT PARQUET)")
        con.unregister("t")
    S.build_site_data(
        root / "site" / "data",
        TC._master(),
        TC._ind(),
        TC._curvas(),
        TC.MANIFEST,
        "2026-10-31",
        today=date(2026, 10, 31),
    )
    return root


@pytest.fixture(params=["parquet", "json"])
def d_precios(raiz_precios, request):
    from vma.consulta import datos as D

    return D.abrir(raiz_precios, request.param)


@pytest.fixture(params=["parquet", "json"])
def d_sin_precios(raiz_sin_precios, request):
    from vma.consulta import datos as D

    return D.abrir(raiz_sin_precios, request.param)
