"""Leest en schrijft de gebruikersbasis in de databank.

Zelfde vorm als `infrastructure/db/importer.py`: SQLAlchemy Core, de beslissing
in Python, het schrijfwerk gebatcht, alles binnen de transactie van de
meegegeven verbinding — deze module opent er zelf geen en commit niet, zodat
een oproeper meerdere handelingen als één geheel kan doen.

Bewust géén `postgresql.insert(...).on_conflict_do_update()`: de tests draaien
op SQLite in het geheugen (zie `tests/test_db_scd2.py` voor hetzelfde
uitgangspunt) en een upsert die alleen op PostgreSQL werkt zou die tests
onmogelijk maken. Lezen-dan-schrijven op de primaire sleutel is hier goedkoop:
het gaat om tientallen rijen per gebruiker, niet om tienduizenden. De enige
uitzondering is `importeer_metingen`, die wél in bulk werkt.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional, Sequence
from uuid import UUID, uuid4

import sqlalchemy as sa

from energie_vlaanderen.gebruikers.models import (
    Aanname,
    Aansluitingspunt,
    AssetType,
    Contracttype,
    EnergieType,
    Exactheidsklasse,
    Gebruiker,
    GebruikersError,
    InstallatieAsset,
    Leveringscontract,
    Meter,
    Meterregime,
    OpgaveBron,
    Persoonsgegevens,
    Registerschema,
    Segment,
    Spanningsniveau,
    Toestemming,
    Topologie,
    Verbruiksopgave,
)
from energie_vlaanderen.infrastructure.db import schema

# 65535 bind-parameters is de PostgreSQL-grens; meterinterval schrijft zes
# kolommen per rij. Zelfde redenering als _PROFIELEN_CHUNK_SIZE in importer.py.
METING_CHUNK = 5_000


def _uuid(waarde: Any) -> Optional[UUID]:
    """SQLite geeft een Uuid-kolom als tekst terug, PostgreSQL als UUID."""
    if waarde is None or isinstance(waarde, UUID):
        return waarde
    return UUID(str(waarde))


def _dec(waarde: Any) -> Optional[Decimal]:
    if waarde is None:
        return None
    return waarde if isinstance(waarde, Decimal) else Decimal(str(waarde))


def _json_lijst(waarde: Any) -> list:
    if waarde in (None, ""):
        return []
    return waarde if isinstance(waarde, list) else json.loads(waarde)


class GebruikersRepository:
    """Toegang tot de gebruikersbasis binnen één databanktransactie."""

    def __init__(self, conn: sa.Connection) -> None:
        self.conn = conn

    # -- schrijven ---------------------------------------------------------

    def _upsert(self, tabel: sa.Table, sleutel: dict[str, Any], waarden: dict[str, Any]) -> None:
        voorwaarde = sa.and_(*[tabel.c[k] == v for k, v in sleutel.items()])
        bestaat = self.conn.execute(
            sa.select(sa.literal(1)).select_from(tabel).where(voorwaarde)
        ).first()
        if bestaat:
            self.conn.execute(sa.update(tabel).where(voorwaarde).values(**waarden))
        else:
            self.conn.execute(sa.insert(tabel).values(**sleutel, **waarden))

    def bewaar_gebruiker(
        self,
        gebruiker: Gebruiker,
        persoonsgegevens: Optional[Persoonsgegevens] = None,
    ) -> UUID:
        self._upsert(
            schema.gebruiker,
            {"id": gebruiker.id},
            {
                "segment": str(gebruiker.segment),
                "land": gebruiker.land,
                "toestemming_referentie": gebruiker.toestemming_referentie,
            },
        )
        if persoonsgegevens is not None:
            if persoonsgegevens.gebruiker_id != gebruiker.id:
                raise GebruikersError(
                    "De persoonsgegevens horen bij een andere gebruiker dan "
                    "degene die bewaard wordt."
                )
            self._upsert(
                schema.gebruiker_persoonsgegeven,
                {"gebruiker_id": gebruiker.id},
                {
                    "naam": persoonsgegevens.naam,
                    "email": persoonsgegevens.email,
                    "straat": persoonsgegevens.straat,
                    "huisnummer": persoonsgegevens.huisnummer,
                    "postcode": persoonsgegevens.postcode,
                    "gemeente": persoonsgegevens.gemeente,
                },
            )
        return gebruiker.id

    def bewaar_aansluitingspunt(self, punt: Aansluitingspunt) -> UUID:
        self._upsert(
            schema.aansluitingspunt,
            {"id": punt.id},
            {
                "gebruiker_id": punt.gebruiker_id,
                "energie_type": str(punt.energie_type),
                "ean_code": punt.ean_code,
                "postcode": punt.postcode,
                "gemeente_naam": punt.gemeente,
                "netbeheerder_code": punt.netbeheerder_code or None,
                "spanningsniveau": str(punt.spanningsniveau),
                "aansluitingsvermogen_kva": punt.aansluitingsvermogen_kva,
                "aantal_fasen": punt.aantal_fasen,
                "geldig_van": punt.geldig_van,
                "geldig_tot": punt.geldig_tot,
            },
        )
        return punt.id

    def bewaar_meter(self, meter: Meter) -> UUID:
        self._upsert(
            schema.meter,
            {"id": meter.id},
            {
                "aansluitingspunt_id": meter.aansluitingspunt_id,
                "meterregime": str(meter.meterregime),
                "registerschema": str(meter.registerschema),
                "terugdraaiend": meter.terugdraaiend,
                "geschatte_maandpiek_kw": meter.geschatte_maandpiek_kw,
                "minimum_maandpiek_kw": meter.minimum_maandpiek_kw,
                "geldig_van": meter.geldig_van,
                "geldig_tot": meter.geldig_tot,
            },
        )
        return meter.id

    def bewaar_asset(self, asset: InstallatieAsset) -> UUID:
        self._upsert(
            schema.installatie_asset,
            {"id": asset.id},
            {
                "aansluitingspunt_id": asset.aansluitingspunt_id,
                "type": str(asset.type),
                "merk": asset.merk,
                "model": asset.model,
                "kwp": asset.kwp,
                "omvormer_merk": asset.omvormer_merk,
                "omvormer_model": asset.omvormer_model,
                "omvormer_kva": asset.omvormer_kva,
                "topologie": str(asset.topologie) if asset.topologie else None,
                "geldig_van": asset.geldig_van,
                "geldig_tot": asset.geldig_tot,
            },
        )
        return asset.id

    def bewaar_contract(self, contract: Leveringscontract) -> UUID:
        self._upsert(
            schema.leveringscontract,
            {"id": contract.id},
            {
                "aansluitingspunt_id": contract.aansluitingspunt_id,
                "leverancier": contract.leverancier,
                "product": contract.product,
                "vreg_id": contract.vreg_id,
                "contracttype": str(contract.contracttype),
                "geldig_van": contract.geldig_van,
                "geldig_tot": contract.geldig_tot,
                "tariefkaart_geldig_van": contract.tariefkaart_geldig_van,
                "bron": contract.bron,
            },
        )
        return contract.id

    def bewaar_verbruiksopgave(self, opgave: Verbruiksopgave) -> UUID:
        self._upsert(
            schema.verbruiksopgave,
            {"id": opgave.id},
            {
                "aansluitingspunt_id": opgave.aansluitingspunt_id,
                "periode_van": opgave.periode_van,
                "periode_tot": opgave.periode_tot,
                "afname_dag_kwh": opgave.afname_dag_kwh,
                "afname_nacht_kwh": opgave.afname_nacht_kwh,
                "afname_exclusief_nacht_kwh": opgave.afname_exclusief_nacht_kwh,
                "injectie_dag_kwh": opgave.injectie_dag_kwh,
                "injectie_nacht_kwh": opgave.injectie_nacht_kwh,
                "bron": str(opgave.bron),
                "dekkingsgraad": opgave.dekkingsgraad,
                "aannames": [asdict(a) for a in opgave.aannames],
            },
        )
        return opgave.id

    def bewaar_toestemming(self, toestemming: Toestemming) -> UUID:
        self._upsert(
            schema.toestemming,
            {"id": toestemming.id},
            {
                "gebruiker_id": toestemming.gebruiker_id,
                "doel": toestemming.doel,
                "verleend_op": toestemming.verleend_op,
                "ingetrokken_op": toestemming.ingetrokken_op,
                "bron": toestemming.bron,
            },
        )
        return toestemming.id

    def importeer_metingen(
        self,
        aansluitingspunt_id: UUID,
        rijen: Iterable[dict[str, Any]],
        bron_bestand: str = "",
    ) -> int:
        """Vervangt de metingen van dit toegangspunt over het aangeleverde bereik.

        Eerst verwijderen, dan invoegen — en alleen binnen het bereik dat de
        invoer werkelijk dekt. Een tweede import van hetzelfde bestand levert
        dus exact dezelfde rijen op, en een import van één maand wist niet stil
        de rest van het jaar.
        """
        batch = [
            {
                "aansluitingspunt_id": aansluitingspunt_id,
                "tijdstip": rij["tijdstip"],
                "afname_kwh": _dec(rij.get("afname_kwh", 0)),
                "injectie_kwh": _dec(rij.get("injectie_kwh", 0)),
                "kwaliteitscode": rij.get("kwaliteitscode", ""),
                "bron_bestand": bron_bestand or None,
            }
            for rij in rijen
        ]
        if not batch:
            return 0

        tijdstippen = [r["tijdstip"] for r in batch]
        self.conn.execute(
            sa.delete(schema.meterinterval).where(
                schema.meterinterval.c.aansluitingspunt_id == aansluitingspunt_id,
                schema.meterinterval.c.tijdstip >= min(tijdstippen),
                schema.meterinterval.c.tijdstip <= max(tijdstippen),
            )
        )
        for start in range(0, len(batch), METING_CHUNK):
            self.conn.execute(
                sa.insert(schema.meterinterval), batch[start : start + METING_CHUNK]
            )
        return len(batch)

    # -- lezen -------------------------------------------------------------

    def gebruikers(self) -> list[Gebruiker]:
        rijen = self.conn.execute(
            sa.select(schema.gebruiker).order_by(schema.gebruiker.c.aangemaakt_op)
        ).mappings()
        return [self._naar_gebruiker(r) for r in rijen]

    def gebruiker(self, gebruiker_id: UUID) -> Gebruiker:
        rij = self.conn.execute(
            sa.select(schema.gebruiker).where(schema.gebruiker.c.id == gebruiker_id)
        ).mappings().first()
        if rij is None:
            raise GebruikersError(f"Geen gebruiker met id {gebruiker_id}.")
        return self._naar_gebruiker(rij)

    def persoonsgegevens(self, gebruiker_id: UUID) -> Optional[Persoonsgegevens]:
        rij = self.conn.execute(
            sa.select(schema.gebruiker_persoonsgegeven).where(
                schema.gebruiker_persoonsgegeven.c.gebruiker_id == gebruiker_id
            )
        ).mappings().first()
        if rij is None:
            return None
        return Persoonsgegevens(
            gebruiker_id=_uuid(rij["gebruiker_id"]),
            naam=rij["naam"],
            email=rij["email"],
            straat=rij["straat"],
            huisnummer=rij["huisnummer"],
            postcode=rij["postcode"],
            gemeente=rij["gemeente"],
        )

    def aansluitingspunten(
        self, gebruiker_id: UUID, energie_type: Optional[str] = None
    ) -> list[Aansluitingspunt]:
        query = sa.select(schema.aansluitingspunt).where(
            schema.aansluitingspunt.c.gebruiker_id == gebruiker_id
        )
        if energie_type:
            query = query.where(schema.aansluitingspunt.c.energie_type == str(energie_type))
        rijen = self.conn.execute(query.order_by(schema.aansluitingspunt.c.energie_type)).mappings()
        return [
            Aansluitingspunt(
                id=_uuid(r["id"]),
                gebruiker_id=_uuid(r["gebruiker_id"]),
                energie_type=EnergieType(r["energie_type"]),
                ean_code=r["ean_code"],
                postcode=r["postcode"],
                gemeente=r["gemeente_naam"],
                netbeheerder_code=r["netbeheerder_code"] or "",
                spanningsniveau=Spanningsniveau(r["spanningsniveau"]),
                aansluitingsvermogen_kva=_dec(r["aansluitingsvermogen_kva"]),
                aantal_fasen=r["aantal_fasen"],
                geldig_van=r["geldig_van"],
                geldig_tot=r["geldig_tot"],
            )
            for r in rijen
        ]

    def meters(self, aansluitingspunt_id: UUID) -> list[Meter]:
        rijen = self.conn.execute(
            sa.select(schema.meter).where(
                schema.meter.c.aansluitingspunt_id == aansluitingspunt_id
            )
        ).mappings()
        return [
            Meter(
                id=_uuid(r["id"]),
                aansluitingspunt_id=_uuid(r["aansluitingspunt_id"]),
                meterregime=Meterregime(r["meterregime"]),
                registerschema=Registerschema(r["registerschema"]),
                terugdraaiend=bool(r["terugdraaiend"]),
                geschatte_maandpiek_kw=_dec(r["geschatte_maandpiek_kw"]),
                minimum_maandpiek_kw=_dec(r["minimum_maandpiek_kw"]),
                geldig_van=r["geldig_van"],
                geldig_tot=r["geldig_tot"],
            )
            for r in rijen
        ]

    def assets(self, aansluitingspunt_id: UUID) -> list[InstallatieAsset]:
        rijen = self.conn.execute(
            sa.select(schema.installatie_asset).where(
                schema.installatie_asset.c.aansluitingspunt_id == aansluitingspunt_id
            )
        ).mappings()
        return [
            InstallatieAsset(
                id=_uuid(r["id"]),
                aansluitingspunt_id=_uuid(r["aansluitingspunt_id"]),
                type=AssetType(r["type"]),
                merk=r["merk"],
                model=r["model"],
                kwp=_dec(r["kwp"]),
                omvormer_merk=r["omvormer_merk"],
                omvormer_model=r["omvormer_model"],
                omvormer_kva=_dec(r["omvormer_kva"]),
                topologie=Topologie(r["topologie"]) if r["topologie"] else None,
                geldig_van=r["geldig_van"],
                geldig_tot=r["geldig_tot"],
            )
            for r in rijen
        ]

    def contracten(self, aansluitingspunt_id: UUID) -> list[Leveringscontract]:
        rijen = self.conn.execute(
            sa.select(schema.leveringscontract)
            .where(schema.leveringscontract.c.aansluitingspunt_id == aansluitingspunt_id)
            .order_by(schema.leveringscontract.c.geldig_van)
        ).mappings()
        return [
            Leveringscontract(
                id=_uuid(r["id"]),
                aansluitingspunt_id=_uuid(r["aansluitingspunt_id"]),
                leverancier=r["leverancier"],
                product=r["product"],
                vreg_id=r["vreg_id"],
                contracttype=Contracttype(r["contracttype"]),
                geldig_van=r["geldig_van"],
                geldig_tot=r["geldig_tot"],
                tariefkaart_geldig_van=r["tariefkaart_geldig_van"],
                bron=r["bron"],
            )
            for r in rijen
        ]

    def verbruiksopgaven(self, aansluitingspunt_id: UUID) -> list[Verbruiksopgave]:
        rijen = self.conn.execute(
            sa.select(schema.verbruiksopgave)
            .where(schema.verbruiksopgave.c.aansluitingspunt_id == aansluitingspunt_id)
            .order_by(schema.verbruiksopgave.c.periode_van)
        ).mappings()
        return [
            Verbruiksopgave(
                id=_uuid(r["id"]),
                aansluitingspunt_id=_uuid(r["aansluitingspunt_id"]),
                periode_van=r["periode_van"],
                periode_tot=r["periode_tot"],
                afname_dag_kwh=_dec(r["afname_dag_kwh"]),
                afname_nacht_kwh=_dec(r["afname_nacht_kwh"]),
                afname_exclusief_nacht_kwh=_dec(r["afname_exclusief_nacht_kwh"]),
                injectie_dag_kwh=_dec(r["injectie_dag_kwh"]),
                injectie_nacht_kwh=_dec(r["injectie_nacht_kwh"]),
                bron=OpgaveBron(r["bron"]),
                dekkingsgraad=_dec(r["dekkingsgraad"]),
                aannames=tuple(Aanname(**a) for a in _json_lijst(r["aannames"])),
            )
            for r in rijen
        ]

    def metingen(
        self,
        aansluitingspunt_id: UUID,
        van=None,
        tot=None,
    ) -> list[dict[str, Any]]:
        query = sa.select(schema.meterinterval).where(
            schema.meterinterval.c.aansluitingspunt_id == aansluitingspunt_id
        )
        if van is not None:
            query = query.where(schema.meterinterval.c.tijdstip >= van)
        if tot is not None:
            query = query.where(schema.meterinterval.c.tijdstip < tot)
        rijen = self.conn.execute(query.order_by(schema.meterinterval.c.tijdstip)).mappings()
        return [
            {
                "tijdstip": r["tijdstip"],
                "afname_kwh": _dec(r["afname_kwh"]),
                "injectie_kwh": _dec(r["injectie_kwh"]),
                "kwaliteitscode": r["kwaliteitscode"],
            }
            for r in rijen
        ]

    # -- simulatieresultaat ------------------------------------------------

    def bewaar_simulatie(
        self,
        *,
        gebruiker_id: UUID,
        aansluitingspunt_id: Optional[UUID],
        periode_van: date,
        periode_tot: date,
        totalen: dict[str, Decimal],
        exactheidsklasse: Exactheidsklasse,
        regels: Sequence[dict[str, Any]] = (),
        leverancier: str = "",
        product: str = "",
        vreg_id: Optional[str] = None,
        version_id: Optional[str] = None,
        bronversies: Optional[dict[str, Any]] = None,
        aannames: Sequence[Aanname] = (),
        warnings: Sequence[str] = (),
    ) -> UUID:
        simulatie_id = uuid4()
        self.conn.execute(
            sa.insert(schema.simulatie).values(
                id=simulatie_id,
                gebruiker_id=gebruiker_id,
                aansluitingspunt_id=aansluitingspunt_id,
                version_id=version_id,
                vreg_id=vreg_id,
                leverancier=leverancier,
                product=product,
                periode_van=periode_van,
                periode_tot=periode_tot,
                supplier_eur=totalen.get("supplier", Decimal("0")),
                grid_eur=totalen.get("grid", Decimal("0")),
                levies_eur=totalen.get("levies", Decimal("0")),
                injection_credit_eur=totalen.get("injection_credit", Decimal("0")),
                vat_eur=totalen.get("vat", Decimal("0")),
                totaal_eur=totalen.get("totaal", Decimal("0")),
                exactheidsklasse=str(exactheidsklasse),
                bronversies=bronversies or {},
                aannames=[asdict(a) for a in aannames],
                warnings=list(warnings),
            )
        )
        if regels:
            self.conn.execute(
                sa.insert(schema.simulatie_regel),
                [self._regel(simulatie_id, regel) for regel in regels],
            )
        return simulatie_id

    @staticmethod
    def _regel(simulatie_id: UUID, regel: dict[str, Any]) -> dict[str, Any]:
        """Vult de bedragvelden expliciet aan in plaats van op de databank te steunen.

        De kolommen hebben een server_default van 0, maar daarop vertrouwen
        betekent dat een oproeper die een component vergeet stil een nul krijgt
        in plaats van een fout. Hier staan ze er altijd, en een ontbrekend veld
        is dan een zichtbare nul en geen toeval.
        """
        volledig = {
            "simulatie_id": simulatie_id,
            "supplier_eur": Decimal("0"),
            "grid_eur": Decimal("0"),
            "levies_eur": Decimal("0"),
            "injection_credit_eur": Decimal("0"),
            "vat_eur": Decimal("0"),
            "totaal_eur": Decimal("0"),
            "leverancier": "",
            "product": "",
            "exactheidsklasse": "geschat",
            "redenen": [],
        }
        volledig.update(regel)
        return volledig

    # -- hulp --------------------------------------------------------------

    @staticmethod
    def _naar_gebruiker(rij) -> Gebruiker:
        return Gebruiker(
            id=_uuid(rij["id"]),
            segment=Segment(rij["segment"]),
            land=rij["land"],
            toestemming_referentie=rij["toestemming_referentie"],
        )
