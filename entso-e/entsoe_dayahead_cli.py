#!/usr/bin/env python3
"""ENTSO-E Day-Ahead Prijzen voor België.

Functies:
- vraagt standaard de prijzen voor morgen op;
- valt automatisch terug op de vorige kalenderdag als geen data beschikbaar is;
- ondersteunt een specifieke datum via --date JJJJ-MM-DD;
- leest eerst een lokale JSON-cache en gebruikt daarna optioneel de ENTSO-E API;
- toont een verzorgde terminaltabel, samenvatting, sparkline en bargrafiek;
- houdt rekening met Europe/Brussels, UTC en zomer-/wintertijd.

Voorbeelden:
    python entsoe_dayahead_cli.py
    python entsoe_dayahead_cli.py --today
    python entsoe_dayahead_cli.py --date 2025-01-01
    python entsoe_dayahead_cli.py --api-key "..."
    python entsoe_dayahead_cli.py --cache entsoe_day_ahead_prices.json
    python entsoe_dayahead_cli.py --no-rich
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from statistics import mean
from typing import Any, Optional
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Europe/Brussels")
UTC = ZoneInfo("UTC")
BASE_URL = "https://web-api.tp.entsoe.eu/api"
BE_DOMAIN = "10YBE----------2"

import os
from dotenv import load_dotenv

# 1. Laad de verborgen variabelen uit het .env bestand
load_dotenv()

# 2. Vraag de sleutel op uit het systeemgeheugen
mijn_api_key = os.getenv("ENTSOE_API_KEY")

# 3. Test of het gelukt is (zonder de sleutel zelf te printen!)
if mijn_api_key:
    print("Sleutel succesvol geladen! Klaar om ENTSO-E aan te roepen.")
    # Vanaf hier gebruik je de variabele 'mijn_api_key' in je requests
else:
    print("Fout: Sleutel niet gevonden. Check of je .env bestand klopt.")


@dataclass(frozen=True)
class PricePoint:
    timestamp_utc: datetime
    price_eur_mwh: float

    @property
    def local_time(self) -> datetime:
        return self.timestamp_utc.astimezone(LOCAL_TZ)

    @property
    def price_ct_kwh(self) -> float:
        # 1 EUR/MWh = 0,1 ct/kWh
        return self.price_eur_mwh / 10.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Toon Belgische ENTSO-E day-aheadprijzen in de terminal."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--date", help="Gevraagde lokale datum, JJJJ-MM-DD.")
    group.add_argument("--today", action="store_true", help="Vraag vandaag op.")
    group.add_argument("--tomorrow", action="store_true", help="Vraag morgen op.")
    parser.add_argument(
        "--api-key",
        help="ENTSO-E API-key. Alternatief: omgevingsvariabele ENTSOE_API_KEY.",
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("entsoe_day_ahead_prices.json"),
        help="JSON-cachebestand. Standaard: entsoe_day_ahead_prices.json",
    )
    parser.add_argument(
        "--timeout", type=int, default=60, help="API-time-out in seconden."
    )
    parser.add_argument(
        "--no-rich",
        action="store_true",
        help="Gebruik eenvoudige tekst in plaats van Rich-opmaak.",
    )
    parser.add_argument(
        "--no-chart", action="store_true", help="Verberg de bargrafiek per uur."
    )
    parser.add_argument(
        "--export-json", type=Path, help="Exporteer de getoonde dag naar JSON."
    )
    parser.add_argument(
    "--refresh",
    action="store_true",
    help="Negeer bestaande cache voor de gevraagde dag en haal opnieuw op via ENTSO-E.",
    )
    return parser.parse_args()


def requested_day(args: argparse.Namespace) -> date:
    today = datetime.now(LOCAL_TZ).date()
    if args.date:
        try:
            return date.fromisoformat(args.date)
        except ValueError as exc:
            raise ValueError("--date moet het formaat JJJJ-MM-DD hebben.") from exc
    if args.today:
        return today
    # Day-ahead betekent standaard: morgen.
    return today + timedelta(days=1)


def local_day_utc_range(day: date) -> tuple[datetime, datetime]:
    start_local = datetime.combine(day, time.min, tzinfo=LOCAL_TZ)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def cache_key(day: date) -> str:
    return f"day:{BE_DOMAIN}:{day.isoformat()}"


def records_to_points(records: list[dict[str, Any]], day: date) -> list[PricePoint]:
    points: list[PricePoint] = []
    for record in records:
        raw_ts = record.get("timestamp")
        raw_price = record.get("price_eur_mwh", record.get("price"))
        if raw_ts is None or raw_price is None:
            continue
        try:
            ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            point = PricePoint(ts.astimezone(UTC), float(raw_price))
            if point.local_time.date() == day:
                points.append(point)
        except (TypeError, ValueError):
            continue
    unique = {p.timestamp_utc: p for p in points}
    return sorted(unique.values(), key=lambda p: p.timestamp_utc)


def fetch_from_api(day: date, api_key: str, timeout: int) -> list[PricePoint]:
    start_utc, end_utc = local_day_utc_range(day)
    params = {
        "securityToken": api_key,
        "documentType": "A44",
        "in_Domain": BE_DOMAIN,
        "out_Domain": BE_DOMAIN,
        "periodStart": start_utc.strftime("%Y%m%d%H%M"),
        "periodEnd": end_utc.strftime("%Y%m%d%H%M"),
    }
    url = f"{BASE_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url, headers={"User-Agent": "ENTSOE-DayAhead-Terminal/1.0"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            xml_data = response.read()
    except urllib.error.HTTPError as exc:
        if exc.code in {400, 401, 403}:
            raise RuntimeError(
                f"ENTSO-E weigerde de aanvraag (HTTP {exc.code}). Controleer de API-key."
            ) from exc
        if exc.code in {404, 429, 500, 502, 503, 504}:
            return []
        raise RuntimeError(f"ENTSO-E HTTP-fout {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"ENTSO-E is niet bereikbaar: {exc}") from exc

    return parse_entsoe_xml(xml_data, day)


def parse_entsoe_xml(xml_data: bytes, day: date) -> list[PricePoint]:
    root = ET.fromstring(xml_data)
    namespace = root.tag.split("}", 1)[0].strip("{") if "}" in root.tag else ""
    ns = {"n": namespace} if namespace else {}
    prefix = "n:" if namespace else ""

    # Een ENTSO-E acknowledgement zonder TimeSeries betekent meestal geen data.
    series = root.findall(f".//{prefix}TimeSeries", ns)
    if not series:
        return []

    points: list[PricePoint] = []
    for time_series in series:
        for period in time_series.findall(f"{prefix}Period", ns):
            start_text = period.findtext(
                f"{prefix}timeInterval/{prefix}start", namespaces=ns
            )
            resolution = period.findtext(f"{prefix}resolution", namespaces=ns)
            if not start_text or not resolution:
                continue
            start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            if resolution == "PT15M":
                step = timedelta(minutes=15)
            elif resolution == "PT30M":
                step = timedelta(minutes=30)
            elif resolution == "PT60M":
                step = timedelta(hours=1)
            else:
                continue

            for node in period.findall(f"{prefix}Point", ns):
                position = node.findtext(f"{prefix}position", namespaces=ns)
                amount = node.findtext(f"{prefix}price.amount", namespaces=ns)
                if not position or amount is None:
                    continue
                timestamp = start + (int(position) - 1) * step
                point = PricePoint(timestamp.astimezone(UTC), float(amount))
                if point.local_time.date() == day:
                    points.append(point)

    unique = {p.timestamp_utc: p for p in points}
    return sorted(unique.values(), key=lambda p: p.timestamp_utc)


def points_to_records(points: list[PricePoint]) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": p.timestamp_utc.isoformat().replace("+00:00", "Z"),
            "price_eur_mwh": p.price_eur_mwh,
        }
        for p in points
    ]


def get_day(
    day: date,
    cache_path: Path,
    api_key: Optional[str],
    timeout: int,
    refresh: bool = False,
) -> tuple[list[PricePoint], str]:
    store = load_cache(cache_path)

    if not refresh:
        records = store.get(cache_key(day), [])

        cached = (
            records_to_points(records, day)
            if isinstance(records, list)
            else []
        )

        if cached:
            return cached, "cache"

    if not api_key:
        if refresh:
            return [], "refresh gevraagd, maar geen API-key beschikbaar"

        return [], "geen cache en geen API-key"

    points = fetch_from_api(
        day=day,
        api_key=api_key,
        timeout=timeout,
    )

    if points:
        store[cache_key(day)] = points_to_records(points)
        save_cache(cache_path, store)

        return points, "ENTSO-E API, cache vernieuwd"

    return [], "ENTSO-E API gaf geen prijzen"

def get_with_previous_day_fallback(
    day: date,
    cache_path: Path,
    api_key: Optional[str],
    timeout: int,
    refresh: bool = False,
) -> tuple[date, list[PricePoint], str, bool]:
    """
    Haalt prijzen op voor de gevraagde dag.

    Bij refresh=True:
    - wordt de cache voor de gevraagde dag genegeerd;
    - wordt de dag opnieuw via ENTSO-E opgehaald;
    - wordt de bestaande cachedag overschreven.

    Als de gevraagde dag niet beschikbaar is:
    - wordt één kalenderdag teruggevallen;
    - voor die vorige dag mag de bestaande cache wel gebruikt worden.
    """

    points, source = get_day(
        day=day,
        cache_path=cache_path,
        api_key=api_key,
        timeout=timeout,
        refresh=refresh,
    )

    if points:
        return day, points, source, False

    previous_day = day - timedelta(days=1)

    previous_points, previous_source = get_day(
        day=previous_day,
        cache_path=cache_path,
        api_key=api_key,
        timeout=timeout,
        refresh=False,
    )

    return previous_day, previous_points, previous_source, True


def sparkline(values: list[float]) -> str:
    chars = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    low, high = min(values), max(values)
    if low == high:
        return chars[3] * len(values)
    return "".join(
        chars[round((value - low) / (high - low) * (len(chars) - 1))]
        for value in values
    )


def bar(value: float, low: float, high: float, width: int = 22) -> str:
    if low == high:
        return "█" * (width // 2)
    size = max(1, round((value - low) / (high - low) * width))
    return "█" * size


def summary(points: list[PricePoint]) -> dict[str, Any]:
    cheapest = min(points, key=lambda p: p.price_eur_mwh)
    expensive = max(points, key=lambda p: p.price_eur_mwh)
    prices = [p.price_eur_mwh for p in points]
    return {
        "average": mean(prices),
        "minimum": cheapest,
        "maximum": expensive,
        "negative_count": sum(p.price_eur_mwh < 0 for p in points),
        "count": len(points),
    }


def render_plain(
    requested: date,
    shown: date,
    points: list[PricePoint],
    source: str,
    fallback: bool,
    show_chart: bool,
) -> None:
    info = summary(points)
    prices = [p.price_eur_mwh for p in points]
    print()
    print("ENTSO-E Day-Ahead Prijzen België")
    print("=" * 62)
    print(f"Gevraagd      : {requested.isoformat()}")
    print(f"Getoond       : {shown.isoformat()}")
    print(f"Bron          : {source}")
    if fallback:
        print("Terugval      : gevraagde dag niet beschikbaar, vorige dag getoond")
    print(f"Resolutie     : {info['count']} prijsintervallen")
    print(f"Gemiddelde    : {info['average']:.2f} EUR/MWh ({info['average']/10:.3f} ct/kWh)")
    print(f"Minimum       : {info['minimum'].local_time:%H:%M}  {info['minimum'].price_eur_mwh:.2f} EUR/MWh")
    print(f"Maximum       : {info['maximum'].local_time:%H:%M}  {info['maximum'].price_eur_mwh:.2f} EUR/MWh")
    print(f"Negatief      : {info['negative_count']} interval(len)")
    print(f"Prijsprofiel  : {sparkline(prices)}")
    print()
    print(f"{'Lokale tijd':<18}{'EUR/MWh':>12}{'ct/kWh':>12}  Grafiek")
    print("-" * 74)
    low, high = min(prices), max(prices)
    for point in points:
        graph = bar(point.price_eur_mwh, low, high) if show_chart else ""
        marker = " < NEGATIEF" if point.price_eur_mwh < 0 else ""
        print(
            f"{point.local_time:%d/%m %H:%M}      "
            f"{point.price_eur_mwh:>10.2f}"
            f"{point.price_ct_kwh:>12.3f}  {graph}{marker}"
        )
    print()


def render_rich(
    requested: date,
    shown: date,
    points: list[PricePoint],
    source: str,
    fallback: bool,
    show_chart: bool,
) -> None:
    from rich import box
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    console = Console()
    info = summary(points)
    prices = [p.price_eur_mwh for p in points]
    fallback_text = (
        "\n[yellow]Gevraagde dag niet beschikbaar. De vorige dag wordt getoond.[/yellow]"
        if fallback else ""
    )
    body = (
        f"[bold]Gevraagd:[/bold] {requested.isoformat()}\n"
        f"[bold]Getoond:[/bold] {shown.isoformat()}\n"
        f"[bold]Bron:[/bold] {source}\n"
        f"[bold]Gemiddelde:[/bold] {info['average']:.2f} EUR/MWh "
        f"({info['average']/10:.3f} ct/kWh)\n"
        f"[green]Minimum:[/green] {info['minimum'].local_time:%H:%M} | "
        f"{info['minimum'].price_eur_mwh:.2f} EUR/MWh\n"
        f"[red]Maximum:[/red] {info['maximum'].local_time:%H:%M} | "
        f"{info['maximum'].price_eur_mwh:.2f} EUR/MWh\n"
        f"[bold]Negatieve intervallen:[/bold] {info['negative_count']}\n"
        f"[bold]Prijsprofiel:[/bold] [cyan]{sparkline(prices)}[/cyan]"
        f"{fallback_text}"
    )
    console.print(Panel(body, title="⚡ ENTSO-E Day-Ahead België", border_style="cyan"))

    table = Table(box=box.SIMPLE_HEAVY, header_style="bold cyan")
    table.add_column("Lokale tijd", style="bold")
    table.add_column("EUR/MWh", justify="right")
    table.add_column("ct/kWh", justify="right")
    if show_chart:
        table.add_column("Relatieve prijs")

    low, high = min(prices), max(prices)
    q1 = sorted(prices)[max(0, len(prices) // 4 - 1)]
    q3 = sorted(prices)[min(len(prices) - 1, 3 * len(prices) // 4)]
    for point in points:
        value = point.price_eur_mwh
        if value < 0:
            style = "bold magenta"
        elif value <= q1:
            style = "green"
        elif value >= q3:
            style = "red"
        else:
            style = "yellow"
        row = [
            point.local_time.strftime("%d/%m %H:%M"),
            Text(f"{value:.2f}", style=style),
            Text(f"{point.price_ct_kwh:.3f}", style=style),
        ]
        if show_chart:
            row.append(Text(bar(value, low, high), style=style))
        table.add_row(*row)
    console.print(table)


def export_json(path: Path, shown: date, points: list[PricePoint]) -> None:
    payload = {
        "area": "BE",
        "local_date": shown.isoformat(),
        "timezone": "Europe/Brussels",
        "unit": "EUR/MWh",
        "prices": [
            {
                "timestamp_utc": p.timestamp_utc.isoformat().replace("+00:00", "Z"),
                "timestamp_local": p.local_time.isoformat(),
                "price_eur_mwh": p.price_eur_mwh,
                "price_ct_kwh": p.price_ct_kwh,
            }
            for p in points
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    try:
        requested = requested_day(args)
    except ValueError as exc:
        print(f"Fout: {exc}", file=sys.stderr)
        return 2

    api_key = args.api_key or os.getenv("ENTSOE_API_KEY")
    try:
        shown, points, source, fallback = get_with_previous_day_fallback(
            day=requested,
            cache_path=args.cache,
            api_key=api_key,
            timeout=args.timeout,
            refresh=args.refresh,
        )
    except (RuntimeError, ET.ParseError) as exc:
        print(f"Fout bij ophalen van ENTSO-E-data: {exc}", file=sys.stderr)
        return 1

    if not points:
        print(
            f"Geen prijzen gevonden voor {requested.isoformat()} of "
            f"{(requested - timedelta(days=1)).isoformat()}.",
            file=sys.stderr,
        )
        if not api_key:
            print(
                "Geef een API-key mee via --api-key of ENTSOE_API_KEY, "
                "of gebruik een gevulde --cache.",
                file=sys.stderr,
            )
        return 1

    if args.export_json:
        export_json(args.export_json, shown, points)

    if args.no_rich:
        render_plain(requested, shown, points, source, fallback, not args.no_chart)
        return 0

    try:
        render_rich(requested, shown, points, source, fallback, not args.no_chart)
    except ImportError:
        render_plain(requested, shown, points, source, fallback, not args.no_chart)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
