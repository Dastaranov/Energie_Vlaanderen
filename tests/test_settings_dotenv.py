"""Tests voor het inlezen van `.env`.

README en CLAUDE.md wijzen `.env` aan als de plek voor ENTSOE_API_KEY en de
databankcredentials, maar `Settings.load()` las enkel `os.environ`. Gevolg:
`market sync` gaf altijd "API-key ontbreekt", ook met een correct ingevulde
`.env`. Deze tests leggen het herstelde gedrag vast.
"""

from __future__ import annotations

import os

import pytest

from energie_vlaanderen.settings import Settings, _read_dotenv


class TestDotenvLezen:
    def test_leest_sleutel_en_waarde(self, tmp_path):
        pad = tmp_path / ".env"
        pad.write_text("ENTSOE_API_KEY=abc123\n", encoding="utf-8")

        assert _read_dotenv(pad) == {"ENTSOE_API_KEY": "abc123"}

    def test_negeert_commentaar_en_lege_regels(self, tmp_path):
        pad = tmp_path / ".env"
        pad.write_text(
            "# een commentaar\n\nA=1\n   \n# nog een\nB=2\n", encoding="utf-8"
        )

        assert _read_dotenv(pad) == {"A": "1", "B": "2"}

    def test_haalt_aanhalingstekens_weg(self, tmp_path):
        pad = tmp_path / ".env"
        pad.write_text('A="met spaties"\nB=\'ook zo\'\n', encoding="utf-8")

        assert _read_dotenv(pad) == {"A": "met spaties", "B": "ook zo"}

    def test_waarde_mag_een_isgelijkteken_bevatten(self, tmp_path):
        # Databank-URL's en base64-sleutels doen dat geregeld.
        pad = tmp_path / ".env"
        pad.write_text("DB=postgresql://u:p@h/db?opt=1\n", encoding="utf-8")

        assert _read_dotenv(pad) == {"DB": "postgresql://u:p@h/db?opt=1"}

    def test_ontbrekend_bestand_geeft_lege_dict(self, tmp_path):
        # `.env` is optioneel; alles kan ook als echte omgevingsvariabele.
        assert _read_dotenv(tmp_path / "bestaat-niet") == {}


class TestSettingsGebruiktDotenv:
    @pytest.fixture
    def project(self, tmp_path, monkeypatch):
        (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
        monkeypatch.delenv("ENTSOE_API_KEY", raising=False)
        return tmp_path

    def test_env_bestand_vult_os_environ(self, project, monkeypatch):
        (project / ".env").write_text("ENTSOE_API_KEY=uit-env\n", encoding="utf-8")

        Settings.load(project_root=project)

        # Niet enkel in Settings: market/entsoe.py en de db-laag lezen
        # os.getenv rechtstreeks.
        assert os.environ["ENTSOE_API_KEY"] == "uit-env"

    def test_bestaande_omgevingsvariabele_wint(self, project, monkeypatch):
        (project / ".env").write_text("ENTSOE_API_KEY=uit-env\n", encoding="utf-8")
        monkeypatch.setenv("ENTSOE_API_KEY", "expliciet-gezet")

        Settings.load(project_root=project)

        assert os.environ["ENTSOE_API_KEY"] == "expliciet-gezet"

    def test_expliciete_environ_slaat_dotenv_over(self, project):
        """Met een meegegeven `environ` blijft de omgeving onaangeroerd.

        Tests geven vaak een handgemaakte omgeving mee; die mag niet
        stilzwijgend aangevuld worden met wat er toevallig in `.env` staat.
        """
        (project / ".env").write_text("ENTSOE_API_KEY=uit-env\n", encoding="utf-8")

        Settings.load(project_root=project, environ={})

        assert "ENTSOE_API_KEY" not in os.environ
