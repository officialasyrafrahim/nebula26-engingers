"""Tests for the optional LTA DataMall advisory context.

Every test mocks httpx with ``httpx.MockTransport``; no test touches the real
network. The suite covers the configured, unconfigured, cache and error paths
and asserts the account key never reaches a response or the archive host.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from app.core.config import Settings
from app.modules.datamall import mapping
from app.modules.datamall.schemas import (
    ADVISORY_LABEL,
    UNAVAILABLE_NETWORK_REASON,
)
from app.modules.datamall.service import DatamallService, get_datamall_service

TEST_KEY = "super-secret-datamall-key"

PV_CSV = (
    "YEAR_MONTH, DAY_TYPE, TIME_PER_HOUR, PT_TYPE, PT_CODE, "
    "TOTAL_TAP_IN_VOLUME, TOTAL_TAP_OUT_VOLUME\n"
    "2024-01, WEEKDAY, 8, TRAIN, DT11, 100, 90\n"
    "2024-01, WEEKDAY, 8, TRAIN, DT15-CC4, 200, 150\n"
    "2024-01, WEEKENDS/HOLIDAY, 8, TRAIN, DT11, 40, 35\n"
    "2024-01, WEEKDAY, 8, TRAIN, NE7, 500, 500\n"
)

OD_CSV = (
    "YEAR_MONTH, DAY_TYPE, TIME_PER_HOUR, PT_TYPE, ORIGIN_PT_CODE, "
    "DESTINATION_PT_CODE, TOTAL_TRIPS\n"
    "2024-01, WEEKDAY, 8, TRAIN, DT11, DT20, 50\n"
    "2024-01, WEEKDAY, 8, TRAIN, DT11, CC30, 30\n"
    "2024-01, WEEKDAY, 8, TRAIN, DT11, NE7, 999\n"
)

REALTIME_ROWS = {
    "DTL": [
        {"Station": "DT11", "CrowdLevel": "l", "StartTime": "2026-01-01T08:00:00+08:00"},
        {"Station": "DT20", "CrowdLevel": "h", "StartTime": "2026-01-01T08:00:00+08:00"},
        {"Station": "EW13", "CrowdLevel": "h", "StartTime": "2026-01-01T08:00:00+08:00"},
    ],
    "CCL": [{"Station": "CC4", "CrowdLevel": "m", "StartTime": "2026-01-01T08:00:00+08:00"}],
    "CEL": [{"Station": "CE1", "CrowdLevel": "NA", "StartTime": "2026-01-01T08:00:00+08:00"}],
}

FORECAST_ROWS = {
    "DTL": [
        {"Station": "DT11", "CrowdLevel": "m", "Start": "2026-01-02T08:00:00+08:00"},
    ],
    "CCL": [],
    "CEL": [],
}

ALERTS_PAYLOAD = {
    "value": {
        "Status": 2,
        "AffectedSegments": [
            {
                "Line": "DTL",
                "Direction": "Both",
                "Stations": "DT11,DT12",
                "FreePublicBus": "DT11",
                "FreeMRTShuttle": "",
            },
            {"Line": "NEL", "Direction": "Both", "Stations": "NE1"},
        ],
        "Message": {"Content": "DTL delay", "CreatedDate": "2026-01-01 08:00:00"},
    }
}


def _settings(key: str | None) -> Settings:
    return Settings(lta_datamall_account_key=key)


def _zip_bytes(csv_text: str, name: str = "transport_node_train_202401.csv") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(name, csv_text)
    return buffer.getvalue()


def _handler(record: list[httpx.Request]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        record.append(request)
        host = request.url.host
        path = request.url.path
        if host != "example.test":
            if path.endswith("/PV/Train"):
                return httpx.Response(
                    200, json={"value": [{"Link": "https://example.test/train.zip"}]}
                )
            if path.endswith("/PV/ODTrain"):
                return httpx.Response(
                    200, json={"value": [{"Link": "https://example.test/od.zip"}]}
                )
            if path.endswith("/PCDRealTime"):
                line = request.url.params.get("TrainLine", "")
                return httpx.Response(200, json={"value": REALTIME_ROWS.get(line, [])})
            if path.endswith("/PCDForecast"):
                line = request.url.params.get("TrainLine", "")
                return httpx.Response(200, json={"value": FORECAST_ROWS.get(line, [])})
            if path.endswith("/TrainServiceAlerts"):
                return httpx.Response(200, json=ALERTS_PAYLOAD)
        if path.endswith("/train.zip"):
            return httpx.Response(200, content=_zip_bytes(PV_CSV))
        if path.endswith("/od.zip"):
            return httpx.Response(200, content=_zip_bytes(OD_CSV, "od_train_202401.csv"))
        return httpx.Response(404)

    return httpx.MockTransport(handle)


def _service(
    record: list[httpx.Request], key: str | None = TEST_KEY, **overrides
) -> DatamallService:
    settings = Settings(lta_datamall_account_key=key, **overrides)
    return DatamallService(settings, transport=_handler(record))


def test_unconfigured_makes_no_outbound_request():
    record: list[httpx.Request] = []

    def explode(request: httpx.Request) -> httpx.Response:  # pragma: no cover - guard
        raise AssertionError("an unconfigured service must not call LTA")

    service = DatamallService(_settings(None), transport=httpx.MockTransport(explode))

    assert service.passenger_volume().source.state == "unconfigured"
    assert service.od_volume().source.state == "unconfigured"
    assert service.crowd_density("DTL").source.state == "unconfigured"
    assert service.crowd_forecast("DTL").source.state == "unconfigured"
    assert service.train_service_alerts().source.state == "unconfigured"
    context = service.network_context(mapping.DEMO_NETWORK_KEY)
    assert context.supported is True
    assert all(source.state == "unconfigured" for source in context.sources)
    assert record == []


def test_passenger_volume_parses_archive_and_filters_unmapped():
    record: list[httpx.Request] = []
    service = _service(record)
    response = service.passenger_volume()
    assert response.source.state == "ok"
    by_code = {row.station_code: row for row in response.records}
    assert set(by_code) == {"DT11", "DT15", "CC4"}
    assert by_code["DT11"].tap_in_weekday == 100
    assert by_code["DT11"].tap_out_weekday == 90
    assert by_code["DT11"].tap_in_weekend == 40
    # An interchange code is merged by LTA and attributed to both lines.
    assert by_code["DT15"].tap_in_weekday == 200
    assert by_code["CC4"].tap_in_weekday == 200
    assert "NE7" not in by_code


def test_passenger_volume_archive_download_omits_account_key():
    record: list[httpx.Request] = []
    service = _service(record)
    service.passenger_volume()
    api_requests = [r for r in record if r.url.host != "example.test"]
    archive_requests = [r for r in record if r.url.host == "example.test"]
    assert api_requests and all(r.headers.get("AccountKey") == TEST_KEY for r in api_requests)
    assert archive_requests and all("AccountKey" not in r.headers for r in archive_requests)


def test_od_volume_keeps_only_mapped_pairs():
    record: list[httpx.Request] = []
    service = _service(record)
    response = service.od_volume()
    assert response.source.state == "ok"
    pairs = {(row.origin_code, row.destination_code) for row in response.records}
    assert ("DT11", "DT20") in pairs
    assert ("DT11", "CC30") in pairs
    assert all("NE7" not in (o, d) for o, d in pairs)


def test_crowd_density_filters_to_mapped_stations():
    record: list[httpx.Request] = []
    service = _service(record)
    response = service.crowd_density("DTL")
    assert response.source.state == "ok"
    codes = {row.station_code for row in response.records}
    assert codes == {"DT11", "DT20"}
    assert response.records[0].station_name is not None


def test_crowd_forecast_parses_start_interval():
    record: list[httpx.Request] = []
    service = _service(record)
    response = service.crowd_forecast("DTL")
    assert response.source.state == "ok"
    assert response.records[0].station_code == "DT11"
    assert response.records[0].interval_start == "2026-01-02T08:00:00+08:00"
    assert response.records[0].interval_end is None


def test_train_alerts_filter_to_mapped_lines():
    record: list[httpx.Request] = []
    service = _service(record)
    response = service.train_service_alerts()
    assert response.status == 2
    assert [alert.line for alert in response.records] == ["DTL"]
    assert response.records[0].stations == ["DT11", "DT12"]


def test_non_200_degrades_to_error_without_raising():
    def failing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    service = DatamallService(
        _settings(TEST_KEY), transport=httpx.MockTransport(failing)
    )
    response = service.crowd_density("DTL")
    assert response.source.state == "error"
    assert response.source.available is False
    assert response.source.http_status == 503


def test_second_call_is_served_from_cache():
    record: list[httpx.Request] = []
    service = _service(record)
    first = service.passenger_volume()
    calls_after_first = len(record)
    second = service.passenger_volume()
    assert first.source.cached is False
    assert second.source.cached is True
    assert len(record) == calls_after_first
    assert second.source.retrieved_at == first.source.retrieved_at


def test_network_context_rejects_unsupported_network_without_request():
    record: list[httpx.Request] = []
    service = _service(record)
    context = service.network_context("hidden-instance")
    assert context.supported is False
    assert context.reason == UNAVAILABLE_NETWORK_REASON
    assert context.sources == []
    assert record == []


def test_network_context_aggregates_all_datasets():
    record: list[httpx.Request] = []
    service = _service(record)
    context = service.network_context(mapping.DEMO_NETWORK_KEY)
    assert context.supported is True
    assert context.mapping is not None
    assert context.advisory.label == ADVISORY_LABEL
    assert context.passenger_volume
    assert context.crowd_density
    assert context.crowd_forecast
    datasets = {source.dataset for source in context.sources}
    assert datasets == {
        "PV/Train",
        "PV/ODTrain",
        "PCDRealTime",
        "PCDForecast",
        "TrainServiceAlerts",
    }


def test_account_key_never_appears_in_payload():
    record: list[httpx.Request] = []
    service = _service(record)
    context = service.network_context(mapping.DEMO_NETWORK_KEY)
    serialised = context.model_dump_json()
    assert TEST_KEY not in serialised
    assert "AccountKey" not in serialised


def test_status_reports_configured_and_freshness():
    record: list[httpx.Request] = []
    service = _service(record)
    service.crowd_density("DTL")
    status = service.status()
    assert status.configured is True
    assert status.enabled is True
    realtime = next(source for source in status.datasets if source.dataset == "PCDRealTime")
    assert realtime.state == "ok"
    assert realtime.retrieved_at is not None


def test_mapping_endpoint_is_source_cited():
    record: list[httpx.Request] = []
    service = _service(record)
    response = service.mapping()
    assert response.source_url.startswith("https://datamall.lta.gov.sg/")
    assert "unverified" in response.caveat.lower()
    network = response.networks[0]
    codes = {station.code for station in network.stations}
    assert {"DT11", "DT20", "CC8", "CE1"}.issubset(codes)


# ------------------------------------------------------------------ API tests


def _override(client, service: DatamallService) -> None:
    client.app.dependency_overrides[get_datamall_service] = lambda: service


def test_api_unconfigured_context(client):
    service = DatamallService(_settings(None))
    _override(client, service)
    try:
        response = client.get(
            "/api/v1/context/datamall/context",
            params={"network": mapping.DEMO_NETWORK_KEY},
        )
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is True
    assert body["advisory"]["label"] == ADVISORY_LABEL
    assert all(source["state"] == "unconfigured" for source in body["sources"])
    assert body["passenger_volume"] == []


def test_api_configured_context_returns_records(client):
    record: list[httpx.Request] = []
    service = _service(record)
    _override(client, service)
    try:
        response = client.get(
            "/api/v1/context/datamall/context",
            params={"network": mapping.DEMO_NETWORK_KEY},
        )
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["passenger_volume"]
    assert body["crowd_density"]
    assert TEST_KEY not in response.text


def test_api_unknown_network_is_unavailable(client):
    service = DatamallService(_settings(TEST_KEY))
    _override(client, service)
    try:
        response = client.get(
            "/api/v1/context/datamall/context", params={"network": "nope"}
        )
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["supported"] is False
    assert body["reason"] == UNAVAILABLE_NETWORK_REASON


def test_api_rejects_unknown_crowd_line(client):
    service = DatamallService(_settings(TEST_KEY))
    _override(client, service)
    try:
        response = client.get(
            "/api/v1/context/datamall/crowd-density", params={"line": "NEL"}
        )
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 422


def test_api_rejects_malformed_date(client):
    service = DatamallService(_settings(TEST_KEY))
    _override(client, service)
    try:
        response = client.get(
            "/api/v1/context/datamall/passenger-volume", params={"date": "not-a-date"}
        )
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 422


def test_api_status_route(client):
    service = DatamallService(_settings(None))
    _override(client, service)
    try:
        response = client.get("/api/v1/context/datamall/status")
    finally:
        client.app.dependency_overrides.clear()
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["state"] == "unconfigured"


@pytest.mark.parametrize("key", [None, ""])
def test_blank_key_is_unconfigured(key):
    record: list[httpx.Request] = []
    service = _service(record, key=key)
    assert service.configured is False
    assert service.crowd_density("DTL").source.state == "unconfigured"
    assert record == []
