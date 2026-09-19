"""LTA DataMall advisory context service.

Design rules
------------
* The DataMall account key is read from settings, sent only as the
  ``AccountKey`` header on the DataMall host, and never returned or logged.
* With no key every method returns an ``unconfigured`` state without touching
  the network.
* Only public reference codes are ever sent: mapped line codes (``DTL``,
  ``CCL``, ``CEL``), a validated ``YYYYMM`` period, or nothing at all. The
  service never uploads instance data or solver output.
* The monthly Passenger Volume APIs return a presigned archive link. The
  archive is downloaded without the account key so the secret is never sent to
  the archive host. A hard byte cap protects memory.
* Responses are cached in process with their retrieval time and source status.
* A DataMall outage or non-200 is captured into an ``error`` source and never
  propagates to another endpoint.
"""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, datetime
from functools import lru_cache
from typing import NamedTuple

import httpx

from app.core.config import Settings, get_settings
from app.modules.datamall import mapping
from app.modules.datamall.schemas import (
    UNAVAILABLE_NETWORK_REASON,
    UNCONFIGURED_REASON,
    CrowdDensityRecord,
    CrowdDensityResponse,
    DatamallMappingResponse,
    DatamallSource,
    DatamallStatusResponse,
    MappingNetworkRead,
    MappingStationRead,
    NetworkContextResponse,
    OdVolumeRecord,
    OdVolumeResponse,
    PassengerVolumeRecord,
    PassengerVolumeResponse,
    TrainAlertRecord,
    TrainAlertsResponse,
)

SOURCE_URL = (
    "https://datamall.lta.gov.sg/content/dam/datamall/datasets/"
    "LTA_DataMall_API_User_Guide.pdf"
)
ACCOUNT_KEY_HEADER = "AccountKey"


class _SourceInfo(NamedTuple):
    endpoint: str
    title: str
    interval: str


SOURCE_INFO: dict[str, _SourceInfo] = {
    "pv_train": _SourceInfo("PV/Train", "Passenger Volume by Train Stations", "Monthly"),
    "pv_od_train": _SourceInfo(
        "PV/ODTrain", "Passenger Volume by Origin Destination Train Stations", "Monthly"
    ),
    "pcd_realtime": _SourceInfo(
        "PCDRealTime", "Station Crowd Density Real Time", "10 minutes"
    ),
    "pcd_forecast": _SourceInfo(
        "PCDForecast", "Station Crowd Density Forecast", "Daily"
    ),
    "train_service_alerts": _SourceInfo(
        "TrainServiceAlerts", "Train Service Alerts", "Ad hoc"
    ),
}


class _DatamallHttpError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"LTA DataMall returned HTTP {status_code}")
        self.status_code = status_code


def _as_int(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def _split_codes(value: object) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    for separator in (";", "|", ","):
        text = text.replace(separator, ",")
    return [token.strip() for token in text.split(",") if token.strip()]


def _extract_link(payload: object) -> str | None:
    """Pull the archive link out of a Passenger Volume API response."""

    if not isinstance(payload, dict):
        return None
    value = payload.get("value")
    if isinstance(value, list) and value and isinstance(value[0], dict):
        link = value[0].get("Link")
        if link:
            return str(link)
    if isinstance(value, dict) and value.get("Link"):
        return str(value["Link"])
    if payload.get("Link"):
        return str(payload["Link"])
    return None


class DatamallService:
    """Optional, read-only LTA DataMall client with an in-process cache."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._client_instance: httpx.Client | None = None
        self._cache: dict[str, tuple[datetime, object]] = {}
        self._last: dict[str, DatamallSource] = {}

    @property
    def configured(self) -> bool:
        return bool(self._settings.lta_datamall_account_key)

    # ------------------------------------------------------------------ client

    def _client(self) -> httpx.Client:
        if self._client_instance is None:
            self._client_instance = httpx.Client(
                base_url=self._settings.lta_datamall_base_url,
                timeout=self._settings.lta_datamall_timeout_seconds,
                transport=self._transport,
            )
        return self._client_instance

    def _account_headers(self) -> dict[str, str]:
        # The key is attached only here and only to the DataMall host.
        return {
            ACCOUNT_KEY_HEADER: self._settings.lta_datamall_account_key or "",
            "accept": "application/json",
        }

    def close(self) -> None:
        if self._client_instance is not None:
            self._client_instance.close()
            self._client_instance = None

    # ------------------------------------------------------------------- cache

    def _cached(self, key: str, builder):
        now = datetime.now(UTC)
        entry = self._cache.get(key)
        if entry is not None:
            stored_at, response = entry
            age = (now - stored_at).total_seconds()
            if age < self._settings.lta_datamall_cache_ttl_seconds:
                clone = response.model_copy(deep=True)  # type: ignore[attr-defined]
                clone.source.cached = True
                return clone
        response = builder()
        if response.source.state in ("ok", "empty"):
            self._cache[key] = (now, response)
        self._last[response.source.dataset] = response.source
        return response

    # ------------------------------------------------------------- source info

    def _source(
        self,
        dataset_key: str,
        *,
        state: str,
        available: bool,
        reason: str | None = None,
        http_status: int | None = None,
        retrieved_at: datetime | None = None,
    ) -> DatamallSource:
        info = SOURCE_INFO[dataset_key]
        return DatamallSource(
            dataset=info.endpoint,
            source=info.title,
            source_url=SOURCE_URL,
            interval=info.interval,
            state=state,  # type: ignore[arg-type]
            available=available,
            configured=self.configured,
            retrieved_at=retrieved_at,
            cached=False,
            http_status=http_status,
            reason=reason,
        )

    def _unconfigured(self, dataset_key: str) -> DatamallSource:
        return self._source(
            dataset_key,
            state="unconfigured",
            available=False,
            reason=UNCONFIGURED_REASON,
        )

    def _error(
        self, dataset_key: str, reason: str, http_status: int | None = None
    ) -> DatamallSource:
        return self._source(
            dataset_key,
            state="error",
            available=False,
            reason=reason,
            http_status=http_status,
        )

    # ------------------------------------------------------------- HTTP helpers

    def _get_json(
        self, endpoint: str, params: dict[str, str] | None = None
    ) -> tuple[object, int]:
        response = self._client().get(
            f"/{endpoint}", params=params, headers=self._account_headers()
        )
        if response.status_code != 200:
            raise _DatamallHttpError(response.status_code)
        return response.json(), response.status_code

    def _fetch_archive_link(self, endpoint: str, params: dict[str, str] | None) -> str:
        payload, _ = self._get_json(endpoint, params)
        link = _extract_link(payload)
        if not link:
            raise ValueError("LTA DataMall did not return a passenger volume archive link")
        return link

    def _download_archive(self, link: str) -> bytes:
        if not link.startswith("https://"):
            raise ValueError("LTA DataMall archive link was not HTTPS")
        cap = self._settings.lta_datamall_max_archive_bytes
        # No AccountKey header: the presigned archive lives on a different host.
        with self._client().stream("GET", link) as response:
            if response.status_code != 200:
                raise _DatamallHttpError(response.status_code)
            content = bytearray()
            for chunk in response.iter_bytes():
                content.extend(chunk)
                if len(content) > cap:
                    raise ValueError("LTA DataMall archive exceeded the configured size cap")
        return bytes(content)

    def _read_csv_rows(self, content: bytes) -> list[dict[str, str]]:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            member = next(
                (
                    name
                    for name in archive.namelist()
                    if name.lower().endswith(".csv") and not name.startswith("__MACOSX")
                ),
                None,
            )
            if member is None:
                raise ValueError("LTA DataMall archive contained no CSV")
            text = archive.read(member).decode("utf-8-sig", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows: list[dict[str, str]] = []
        for row in reader:
            rows.append({(key or "").strip(): (value or "") for key, value in row.items()})
        return rows

    # ---------------------------------------------------------------- datasets

    def _build_passenger_volume(self, period: str | None) -> PassengerVolumeResponse:
        if not self.configured:
            return PassengerVolumeResponse(
                source=self._unconfigured("pv_train"), period=period
            )
        try:
            params = {"Date": period} if period else None
            link = self._fetch_archive_link("PV/Train", params)
            rows = self._read_csv_rows(self._download_archive(link))
        except _DatamallHttpError as exc:
            source = self._error(
                "pv_train",
                f"LTA DataMall passenger volume request returned HTTP {exc.status_code}",
                http_status=exc.status_code,
            )
            return PassengerVolumeResponse(source=source, period=period)
        except (httpx.HTTPError, ValueError, zipfile.BadZipFile) as exc:
            return PassengerVolumeResponse(
                source=self._error("pv_train", f"LTA DataMall passenger volume unavailable: {exc}"),
                period=period,
            )
        records = self._aggregate_passenger_volume(rows)
        if not records:
            return PassengerVolumeResponse(
                source=self._source(
                    "pv_train",
                    state="empty",
                    available=True,
                    reason="LTA returned no rows for the mapped stations",
                    retrieved_at=datetime.now(UTC),
                ),
                period=period,
            )
        return PassengerVolumeResponse(
            source=self._source(
                "pv_train", state="ok", available=True, retrieved_at=datetime.now(UTC)
            ),
            period=period,
            records=records,
        )

    def passenger_volume(self, period: str | None = None) -> PassengerVolumeResponse:
        key = f"pv_train:{period or 'latest'}"
        return self._cached(key, lambda: self._build_passenger_volume(period))

    def _build_od_volume(self, period: str | None) -> OdVolumeResponse:
        if not self.configured:
            return OdVolumeResponse(source=self._unconfigured("pv_od_train"), period=period)
        try:
            params = {"Date": period} if period else None
            link = self._fetch_archive_link("PV/ODTrain", params)
            rows = self._read_csv_rows(self._download_archive(link))
        except _DatamallHttpError as exc:
            source = self._error(
                "pv_od_train",
                f"LTA DataMall OD volume request returned HTTP {exc.status_code}",
                http_status=exc.status_code,
            )
            return OdVolumeResponse(source=source, period=period)
        except (httpx.HTTPError, ValueError, zipfile.BadZipFile) as exc:
            return OdVolumeResponse(
                source=self._error(
                    "pv_od_train", f"LTA DataMall OD volume unavailable: {exc}"
                ),
                period=period,
            )
        records = self._aggregate_od_volume(rows)
        if not records:
            return OdVolumeResponse(
                source=self._source(
                    "pv_od_train",
                    state="empty",
                    available=True,
                    reason="LTA returned no mapped origin destination pairs",
                    retrieved_at=datetime.now(UTC),
                ),
                period=period,
            )
        return OdVolumeResponse(
            source=self._source(
                "pv_od_train", state="ok", available=True, retrieved_at=datetime.now(UTC)
            ),
            period=period,
            records=records,
        )

    def od_volume(self, period: str | None = None) -> OdVolumeResponse:
        key = f"pv_od_train:{period or 'latest'}"
        return self._cached(key, lambda: self._build_od_volume(period))

    def _build_crowd(
        self, dataset_key: str, endpoint: str, line: str
    ) -> CrowdDensityResponse:
        if not self.configured:
            return CrowdDensityResponse(
                source=self._unconfigured(dataset_key), line=line
            )
        try:
            payload, _ = self._get_json(endpoint, {"TrainLine": line})
        except _DatamallHttpError as exc:
            source = self._error(
                dataset_key,
                f"LTA DataMall {endpoint} request returned HTTP {exc.status_code}",
                http_status=exc.status_code,
            )
            return CrowdDensityResponse(source=source, line=line)
        except (httpx.HTTPError, ValueError) as exc:
            return CrowdDensityResponse(
                source=self._error(dataset_key, f"LTA DataMall {endpoint} unavailable: {exc}"),
                line=line,
            )
        value = payload.get("value") if isinstance(payload, dict) else None
        rows = value if isinstance(value, list) else []
        records = self._crowd_records(rows, line)
        if not records:
            return CrowdDensityResponse(
                source=self._source(
                    dataset_key,
                    state="empty",
                    available=True,
                    reason=f"LTA returned no mapped {line} stations",
                    retrieved_at=datetime.now(UTC),
                ),
                line=line,
            )
        return CrowdDensityResponse(
            source=self._source(
                dataset_key, state="ok", available=True, retrieved_at=datetime.now(UTC)
            ),
            line=line,
            records=records,
        )

    def crowd_density(self, line: str) -> CrowdDensityResponse:
        key = f"pcd_realtime:{line}"
        return self._cached(key, lambda: self._build_crowd("pcd_realtime", "PCDRealTime", line))

    def crowd_forecast(self, line: str) -> CrowdDensityResponse:
        key = f"pcd_forecast:{line}"
        return self._cached(key, lambda: self._build_crowd("pcd_forecast", "PCDForecast", line))

    def _build_alerts(self) -> TrainAlertsResponse:
        if not self.configured:
            return TrainAlertsResponse(source=self._unconfigured("train_service_alerts"))
        try:
            payload, _ = self._get_json("TrainServiceAlerts")
        except _DatamallHttpError as exc:
            source = self._error(
                "train_service_alerts",
                f"LTA DataMall TrainServiceAlerts request returned HTTP {exc.status_code}",
                http_status=exc.status_code,
            )
            return TrainAlertsResponse(source=source)
        except (httpx.HTTPError, ValueError) as exc:
            return TrainAlertsResponse(
                source=self._error(
                    "train_service_alerts", f"LTA DataMall TrainServiceAlerts unavailable: {exc}"
                )
            )
        status, records = self._parse_alerts(payload)
        if not records:
            return TrainAlertsResponse(
                source=self._source(
                    "train_service_alerts",
                    state="empty",
                    available=True,
                    reason="No disruption reported on the mapped lines",
                    retrieved_at=datetime.now(UTC),
                ),
                status=status,
            )
        return TrainAlertsResponse(
            source=self._source(
                "train_service_alerts", state="ok", available=True, retrieved_at=datetime.now(UTC)
            ),
            status=status,
            records=records,
        )

    def train_service_alerts(self) -> TrainAlertsResponse:
        return self._cached("train_service_alerts", self._build_alerts)

    # -------------------------------------------------------------- aggregation

    def _aggregate_passenger_volume(
        self, rows: list[dict[str, str]]
    ) -> list[PassengerVolumeRecord]:
        totals: dict[str, dict[str, int]] = {}
        for row in rows:
            tokens = {token.strip() for token in row.get("PT_CODE", "").split("-") if token.strip()}
            if not tokens:
                continue
            day = (row.get("DAY_TYPE") or "").strip().upper()
            tap_in = _as_int(row.get("TOTAL_TAP_IN_VOLUME"))
            tap_out = _as_int(row.get("TOTAL_TAP_OUT_VOLUME"))
            for token in tokens:
                station = mapping.station_by_code(token)
                if station is None:
                    continue
                bucket = totals.setdefault(
                    token,
                    {
                        "in_wd": 0,
                        "out_wd": 0,
                        "in_we": 0,
                        "out_we": 0,
                    },
                )
                if day == "WEEKDAY":
                    bucket["in_wd"] += tap_in
                    bucket["out_wd"] += tap_out
                elif day.startswith("WEEKEND"):
                    bucket["in_we"] += tap_in
                    bucket["out_we"] += tap_out
        records: list[PassengerVolumeRecord] = []
        for code, station in mapping.STATION_BY_CODE.items():
            bucket = totals.get(code)
            if bucket is None:
                continue
            records.append(
                PassengerVolumeRecord(
                    station_code=code,
                    station_name=station.name,
                    solver_line=station.solver_line,
                    solver_station=station.solver_station,
                    datamall_line=station.datamall_line,
                    tap_in_weekday=bucket["in_wd"],
                    tap_out_weekday=bucket["out_wd"],
                    tap_in_weekend=bucket["in_we"],
                    tap_out_weekend=bucket["out_we"],
                    total_weekday=bucket["in_wd"] + bucket["out_wd"],
                    total_weekend=bucket["in_we"] + bucket["out_we"],
                )
            )
        return records

    def _aggregate_od_volume(
        self, rows: list[dict[str, str]], limit: int = 40
    ) -> list[OdVolumeRecord]:
        totals: dict[tuple[str, str], dict[str, int]] = {}
        for row in rows:
            origins = {
                token.strip()
                for token in row.get("ORIGIN_PT_CODE", "").split("-")
                if token.strip()
            }
            destinations = {
                token.strip()
                for token in row.get("DESTINATION_PT_CODE", "").split("-")
                if token.strip()
            }
            origin_codes = [code for code in origins if code in mapping.STATION_BY_CODE]
            destination_codes = [code for code in destinations if code in mapping.STATION_BY_CODE]
            if not origin_codes or not destination_codes:
                continue
            day = (row.get("DAY_TYPE") or "").strip().upper()
            trips = _as_int(row.get("TOTAL_TRIPS"))
            for origin in origin_codes:
                for destination in destination_codes:
                    if origin == destination:
                        continue
                    bucket = totals.setdefault((origin, destination), {"wd": 0, "we": 0})
                    if day == "WEEKDAY":
                        bucket["wd"] += trips
                    elif day.startswith("WEEKEND"):
                        bucket["we"] += trips
        records: list[OdVolumeRecord] = []
        for (origin, destination), bucket in totals.items():
            origin_station = mapping.station_by_code(origin)
            destination_station = mapping.station_by_code(destination)
            records.append(
                OdVolumeRecord(
                    origin_code=origin,
                    origin_name=origin_station.name if origin_station else None,
                    destination_code=destination,
                    destination_name=destination_station.name if destination_station else None,
                    weekday_trips=bucket["wd"],
                    weekend_trips=bucket["we"],
                )
            )
        records.sort(key=lambda record: -(record.weekday_trips + record.weekend_trips))
        return records[:limit]

    def _crowd_records(
        self, rows: list[object], line: str
    ) -> list[CrowdDensityRecord]:
        records: list[CrowdDensityRecord] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("Station") or "").strip()
            station = mapping.station_by_code(code)
            if station is None or code in seen:
                continue
            seen.add(code)
            level = str(row.get("CrowdLevel") or "NA").strip().lower()
            if level not in ("l", "m", "h", "na"):
                level = "na"
            start = row.get("StartTime") or row.get("Start")
            end = row.get("EndTime")
            records.append(
                CrowdDensityRecord(
                    station_code=code,
                    station_name=station.name,
                    solver_line=station.solver_line,
                    solver_station=station.solver_station,
                    datamall_line=line,
                    crowd_level=level,
                    interval_start=str(start) if start else None,
                    interval_end=str(end) if end else None,
                )
            )
        records.sort(key=lambda record: record.station_code)
        return records

    def _parse_alerts(self, payload: object) -> tuple[int | None, list[TrainAlertRecord]]:
        value = payload.get("value") if isinstance(payload, dict) else None
        entries: list[dict[str, object]] = []
        status: int | None = None
        message: str | None = None
        created_at: str | None = None
        if isinstance(value, dict):
            status = _as_int(value.get("Status")) or None
            segments = value.get("AffectedSegments")
            if isinstance(segments, list):
                entries = [segment for segment in segments if isinstance(segment, dict)]
            message_block = value.get("Message")
            if isinstance(message_block, dict):
                content = message_block.get("Content")
                created = message_block.get("CreatedDate")
                message = str(content) if content else None
                created_at = str(created) if created else None
        elif isinstance(value, list):
            entries = [entry for entry in value if isinstance(entry, dict)]
        records: list[TrainAlertRecord] = []
        for entry in entries:
            line = str(entry.get("Line") or "").strip()
            if line not in mapping.ALLOWED_ALERT_LINES:
                continue
            records.append(
                TrainAlertRecord(
                    line=line,
                    direction=str(entry.get("Direction")) if entry.get("Direction") else None,
                    stations=_split_codes(entry.get("Stations")),
                    free_public_bus=_split_codes(entry.get("FreePublicBus")),
                    free_mrt_shuttle=_split_codes(entry.get("FreeMRTShuttle")),
                    message=message,
                    created_at=created_at,
                )
            )
        return status, records

    # ------------------------------------------------------------------- status

    def status(self) -> DatamallStatusResponse:
        datasets: list[DatamallSource] = []
        for dataset_key, info in SOURCE_INFO.items():
            last = self._last.get(info.endpoint)
            if last is not None:
                datasets.append(last)
            elif not self.configured:
                datasets.append(self._unconfigured(dataset_key))
            else:
                datasets.append(
                    self._source(
                        dataset_key,
                        state="empty",
                        available=False,
                        reason="Not retrieved in this process yet",
                    )
                )
        return DatamallStatusResponse(
            configured=self.configured,
            enabled=self.configured,
            state="ok" if self.configured else "unconfigured",
            reason=None if self.configured else UNCONFIGURED_REASON,
            datasets=datasets,
        )

    def mapping(self) -> DatamallMappingResponse:
        networks = [
            MappingNetworkRead(
                key=network.key,
                label=network.label,
                solver_lines=list(network.solver_lines),
                crowd_lines=list(network.crowd_lines),
                alert_lines=list(network.alert_lines),
                stations=[
                    MappingStationRead(
                        solver_line=station.solver_line,
                        solver_station=station.solver_station,
                        name=station.name,
                        code=station.code,
                        datamall_line=station.datamall_line,
                    )
                    for station in network.stations
                ],
            )
            for network in mapping.all_networks()
        ]
        return DatamallMappingResponse(
            source=mapping.MAPPING_SOURCE,
            source_url=mapping.MAPPING_SOURCE_URL,
            caveat=mapping.MAPPING_CAVEAT,
            networks=networks,
        )

    # ---------------------------------------------------------------- aggregate

    def network_context(self, network_key: str) -> NetworkContextResponse:
        generated_at = datetime.now(UTC)
        network = mapping.get_network(network_key)
        if network is None:
            return NetworkContextResponse(
                network=network_key,
                supported=False,
                generated_at=generated_at,
                reason=UNAVAILABLE_NETWORK_REASON,
            )
        network_read = MappingNetworkRead(
            key=network.key,
            label=network.label,
            solver_lines=list(network.solver_lines),
            crowd_lines=list(network.crowd_lines),
            alert_lines=list(network.alert_lines),
            stations=[
                MappingStationRead(
                    solver_line=station.solver_line,
                    solver_station=station.solver_station,
                    name=station.name,
                    code=station.code,
                    datamall_line=station.datamall_line,
                )
                for station in network.stations
            ],
        )
        sources: list[DatamallSource] = []
        passenger_volume = self.passenger_volume()
        sources.append(passenger_volume.source)
        od_volume = self.od_volume()
        sources.append(od_volume.source)
        crowd_records: list[CrowdDensityRecord] = []
        for line in network.crowd_lines:
            response = self.crowd_density(line)
            sources.append(response.source)
            crowd_records.extend(response.records)
        forecast_records: list[CrowdDensityRecord] = []
        for line in network.crowd_lines:
            response = self.crowd_forecast(line)
            sources.append(response.source)
            forecast_records.extend(response.records)
        alerts = self.train_service_alerts()
        sources.append(alerts.source)
        return NetworkContextResponse(
            network=network.key,
            supported=True,
            generated_at=generated_at,
            mapping=network_read,
            sources=sources,
            passenger_volume=passenger_volume.records,
            od_volume=od_volume.records,
            crowd_density=crowd_records,
            crowd_forecast=forecast_records,
            alerts=alerts.records,
            alerts_status=alerts.status,
        )


@lru_cache
def get_datamall_service() -> DatamallService:
    """Return the process-wide DataMall service."""

    return DatamallService(get_settings())


__all__ = [
    "DatamallService",
    "get_datamall_service",
]
