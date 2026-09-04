from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pandas as pd

from energie_vlaanderen.domain.models import Product
from energie_vlaanderen.nettarieven.netbeheerder import (
    NetbeheerderRegister,
    standaard_gemeente_csv,
)
from energie_vlaanderen.utility.normalizer import dec


class DataRepositoryError(RuntimeError):
    pass


class DataRepository:
    """
    Repository voor de canonieke V-test datasets.

    Leest uitsluitend de output van ingest/vtest/pipeline.py.
    """

    REQUIRED_FILES = (
        "master_vast.csv",
        "master_var_dyn.csv",
    )

    # De nettariefbestanden die `ingest/tariffs/pipeline.py` in een versie legt.
    # Alle drie worden ingelezen: `grid_cost()` filtert zelf op Contracttype en
    # Klanttype, maar wie enkel het afnamebestand laadt kan nooit merken dat een
    # injectie- of hoogspanningsrij ontbreekt.
    TARIEFBESTANDEN = (
        "tariffs_electricity_afname.csv",
        "tariffs_electricity_injectie.csv",
        "tariffs_electricity_hoogspanning.csv",
        "tariffs_gas_afname.csv",
        "tariffs_gas_injectie.csv",
    )

    def __init__(
        self,
        data_dir: Path,
        *,
        gemeente_csv: Path | None = None,
        tariff_dir: Path | None = None,
    ) -> None:

        self.data_dir = Path(data_dir)

        # Nettarieven en de postcode->netbeheerder-koppeling worden lui geladen.
        # Ze zijn niet verplicht om producten te lezen, en de bestaande
        # oproepers (audit, ingest) hebben ze niet nodig; wie ze wél gebruikt
        # krijgt bij een ontbrekend bestand een duidelijke fout in plaats van
        # een lege tabel die stil op nul uitkomt.
        self._gemeente_csv = Path(gemeente_csv) if gemeente_csv else None
        self._tariff_dir = Path(tariff_dir) if tariff_dir else self.data_dir / "tariffs"
        self._dnb: pd.DataFrame | None = None
        self._register: NetbeheerderRegister | None = None
        self._tariefjaar: int | None = None

        self.fixed_file = (
            self.data_dir
            / "vtest"
            / "master_vast.csv"
        )

        self.variable_file = (
            self.data_dir
            / "vtest"
            / "master_var_dyn.csv"
        )

        self._validate()

        self.fixed = pd.read_csv(
            self.fixed_file,
            sep=";",
            encoding="utf-8-sig",
        )

        # low_memory=False: pandas leest anders in blokken en leidt per blok
        # een type af, wat op de formulekolommen (b/c/d, index_name_*,
        # index_value_*) een DtypeWarning geeft omdat lege blokken als float en
        # gevulde als object gelezen worden. De kolommen gaan hoe dan ook via
        # `dec()` door de normalizer; de waarschuwing zei niets over de data.
        self.variable = pd.read_csv(
            self.variable_file,
            sep=";",
            encoding="utf-8-sig",
            low_memory=False,
        )

    def _validate(self) -> None:

        missing: list[str] = []

        if not self.fixed_file.is_file():
            missing.append(str(self.fixed_file))

        if not self.variable_file.is_file():
            missing.append(str(self.variable_file))

        if missing:
            raise DataRepositoryError(
                "Ontbrekende datasetbestanden:\n"
                + "\n".join(missing)
            )

    def products(
        self,
        year: int,
        month: int,
        segment: str,
        *,
        energy: str = "electricity",
        direction: str = "consumption",
    ) -> list[Product]:

        frames = [
            self.fixed,
            self.variable,
        ]

        result: list[Product] = []

        for frame in frames:

            filtered = frame.loc[
                (frame["year"] == year)
                & (frame["month"] == month)
                & (frame["segment"] == segment)
                & (frame["energy"] == energy)
                & (frame["direction"] == direction)
            ]

            grouped = filtered.groupby(
                [
                    "year",
                    "month",
                    "segment",
                    "energy",
                    "direction",
                    "supplier",
                    "product",
                    "product_type",
                ],
                dropna=False,
            )

            for key, rows in grouped:

                (
                    row_year,
                    row_month,
                    row_segment,
                    row_energy,
                    row_direction,
                    supplier,
                    product_name,
                    product_type,
                ) = key

                components: dict[str, Decimal] = {}
                formulas: dict[str, dict] = {}

                source = ""

                for _, row in rows.iterrows():

                    source = str(
                        row.get(
                            "source_sheet",
                            "",
                        )
                    )

                    component = str(
                        row["component"]
                    )

                    price = dec(
                        row.get("price")
                    )

                    if price is not None:
                        components[
                            component
                        ] = price

                    formula = {}

                    for letter in (
                        "a",
                        "b",
                        "c",
                        "d",
                        "z",
                    ):
                        value = dec(
                            row.get(letter)
                        )

                        if value is not None:
                            formula[
                                letter
                            ] = value

                    for suffix in (
                        "A",
                        "B",
                        "C",
                        "D",
                    ):
                        name = row.get(
                            f"index_name_{suffix}"
                        )

                        value = row.get(
                            f"index_value_{suffix}"
                        )

                        if (
                            pd.notna(name)
                            and name
                        ):
                            formula[
                                f"index_{suffix}"
                            ] = {
                                "name": str(name),
                                "value": (
                                    dec(value)
                                ),
                            }

                    if formula:
                        formulas[
                            component
                        ] = formula

                result.append(
                    Product(
                        year=int(row_year),
                        month=int(row_month),
                        segment=str(row_segment),
                        energy=str(row_energy),
                        direction=str(row_direction),
                        supplier=str(supplier),
                        name=str(product_name),
                        kind=str(product_type),
                        components=components,
                        formulas=formulas,
                        source=source,
                    )
                )

        return result


    # ------------------------------------------------------------------
    # Nettarieven en netbeheerder
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings,
        data_dir: Path | None = None,
    ) -> "DataRepository":
        """Bouw een repository met de nettarief- en gemeentebestanden erbij.

        `DnbPerGemeente.csv` staat buiten de versiemappen, in
        `data/current/` — hetzelfde pad dat `cli/db.py` en
        `cli/ingest.py` ervoor gebruiken. Zonder `settings` is dat pad niet
        af te leiden, en raden zou de verkeerde netbeheerder kunnen opleveren.
        """
        from energie_vlaanderen.data.paths import DataPaths

        paden = DataPaths.from_settings(settings)
        gekozen = Path(data_dir) if data_dir else paden.current_data_dir()
        return cls(
            gekozen,
            gemeente_csv=standaard_gemeente_csv(settings.data_root),
        )

    @property
    def dnb(self) -> pd.DataFrame:
        """De nettariefrijen van alle netbeheerders, als één tabel.

        Kolommen zoals `ingest/tariffs/pipeline.py` ze schrijft: Netbeheerder,
        Klanttype, Contracttype, Tarieftype, Tariefdetail, Tariefnotering,
        Prijs_num.
        """
        if self._dnb is None:
            self._dnb = self._laad_nettarieven()
        return self._dnb

    def _laad_nettarieven(self) -> pd.DataFrame:
        gevonden = [
            self._tariff_dir / naam
            for naam in self.TARIEFBESTANDEN
            if (self._tariff_dir / naam).is_file()
        ]
        if not gevonden:
            raise DataRepositoryError(
                f"Geen nettariefbestanden gevonden in {self._tariff_dir}. "
                "Draai eerst `energievergelijker staging parse --version <id> "
                "--only tariffs`; zonder deze bestanden is de netkost niet te "
                "berekenen en mag ze niet als 0 doorgaan."
            )
        frames = [
            pd.read_csv(pad, sep=";", encoding="utf-8-sig") for pad in gevonden
        ]
        return pd.concat(frames, ignore_index=True)

    @property
    def tariefjaar(self) -> int | None:
        """Het jaar waarvoor de geladen nettarieven gelden, of None.

        Uit `tariffs_*_report.json`. Eén versie draagt één tariefjaar: de
        werkboeken van de VREG worden per kalenderjaar goedgekeurd, en de
        tariefdetails in de CSV's dragen zelf geen datum. Een berekening over
        2025 met de tarieven van 2026 is daardoor niet aan de data te zien —
        vandaar dat `Kostberekening` het jaar toetst in plaats van erop te
        vertrouwen.
        """
        if self._tariefjaar is None:
            jaren: set[int] = set()
            for rapport in sorted(self._tariff_dir.glob("tariffs_*_report.json")):
                try:
                    data = json.loads(rapport.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                jaar = data.get("tarief_jaar")
                if isinstance(jaar, int):
                    jaren.add(jaar)
            if len(jaren) > 1:
                raise DataRepositoryError(
                    f"De tariefbestanden in {self._tariff_dir} horen bij "
                    f"meerdere tariefjaren ({sorted(jaren)}). Eén dataversie "
                    "draagt één tariefjaar."
                )
            self._tariefjaar = jaren.pop() if jaren else 0
        return self._tariefjaar or None

    @property
    def netbeheerders(self) -> NetbeheerderRegister:
        if self._register is None:
            if self._gemeente_csv is None:
                raise DataRepositoryError(
                    "Deze repository kent DnbPerGemeente.csv niet. Gebruik "
                    "DataRepository.from_settings(settings) of geef "
                    "gemeente_csv= expliciet mee."
                )
            self._register = NetbeheerderRegister.load(self._gemeente_csv)
        return self._register

    def dnb_for(
        self,
        postcode: str,
        gemeente: str = "",
        energie_type: str = "elektriciteit",
    ) -> tuple[str, str]:
        """De netbeheerder op dit adres, als `(naam, code)`.

        Weigert een netbeheerder zonder tariefdata in deze dataset — zie
        `NetbeheerderRegister.dnb_met_tarieven`.
        """
        return self.netbeheerders.dnb_met_tarieven(postcode, gemeente, energie_type)
