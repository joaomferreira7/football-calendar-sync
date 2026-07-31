"""
Testes para a lógica de sincronização em sync.py.

Não tocam em nenhuma API real: o serviço da Google Calendar é um MagicMock
e os "jogos" são dicionários construídos à mão na forma que zerozero_scraper
devolve (ver zerozero_scraper.fetch_team_matches).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

import sync


def make_match(match_id, date, status="SCHEDULED", home="Sporting", away="SL Benfica",
                competition_name="Primeira Liga", matchday=1, color_id="10"):
    return {
        "id": match_id,
        "utcDate": date,
        "status": status,
        "matchday": matchday,
        "stage": "REGULAR_SEASON",
        "venue": "",
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "competition": {"id": f"zz-{competition_name}", "name": competition_name},
        "colorId": color_id,
    }


def make_service(insert_id="evt_new"):
    """MagicMock que imita o objeto `service` da Google Calendar API."""
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {
        "id": insert_id,
        "summary": "⚽ Jogo",
    }
    service.events.return_value.update.return_value.execute.return_value = {
        "summary": "⚽ Jogo atualizado",
    }
    service.events.return_value.delete.return_value.execute.return_value = {}
    return service


def http_error(status):
    resp = SimpleNamespace(status=status, reason="error")
    return HttpError(resp=resp, content=b"{}")


def test_creates_event_for_new_match():
    service = make_service(insert_id="evt_123")
    matches = [make_match("m1", "2026-03-22T21:15:00Z")]
    state = {}

    sync.sync(matches, state, service)

    service.events.return_value.insert.assert_called_once()
    assert state["m1"]["event_id"] == "evt_123"
    assert state["m1"]["date"] == "2026-03-22T21:15:00Z"


def test_skips_match_already_in_state_with_same_date():
    service = make_service()
    matches = [make_match("m1", "2026-03-22T21:15:00Z")]
    state = {"m1": {"date": "2026-03-22T21:15:00Z", "event_id": "evt_old",
                     "home": "Sporting CP", "away": "SL Benfica", "competition": 2017}}

    sync.sync(matches, state, service)

    service.events.return_value.insert.assert_not_called()
    service.events.return_value.update.assert_not_called()


def test_updates_event_when_date_changes():
    service = make_service()
    matches = [make_match("m1", "2026-03-23T18:00:00Z")]
    state = {"m1": {"date": "2026-03-22T21:15:00Z", "event_id": "evt_old",
                     "home": "Sporting CP", "away": "SL Benfica", "competition": 2017}}

    sync.sync(matches, state, service)

    service.events.return_value.update.assert_called_once()
    call_kwargs = service.events.return_value.update.call_args.kwargs
    assert call_kwargs["eventId"] == "evt_old"
    assert state["m1"]["date"] == "2026-03-23T18:00:00Z"


def test_recreates_event_when_update_target_is_gone():
    service = make_service(insert_id="evt_recreated")
    service.events.return_value.update.return_value.execute.side_effect = http_error(404)
    matches = [make_match("m1", "2026-03-23T18:00:00Z")]
    state = {"m1": {"date": "2026-03-22T21:15:00Z", "event_id": "evt_deleted",
                     "home": "Sporting CP", "away": "SL Benfica", "competition": 2017}}

    sync.sync(matches, state, service)

    service.events.return_value.insert.assert_called_once()
    assert state["m1"]["event_id"] == "evt_recreated"
    assert state["m1"]["date"] == "2026-03-23T18:00:00Z"


def test_deletes_event_for_match_no_longer_in_api():
    service = make_service()
    state = {"m1": {"date": "2026-03-22T21:15:00Z", "event_id": "evt_old",
                     "home": "Sporting CP", "away": "SL Benfica", "competition": 2017}}

    sync.sync([], state, service)

    service.events.return_value.delete.assert_called_once()
    assert "m1" not in state


def test_keeps_match_in_state_when_delete_fails():
    service = make_service()
    service.events.return_value.delete.return_value.execute.side_effect = RuntimeError("network blip")
    state = {"m1": {"date": "2026-03-22T21:15:00Z", "event_id": "evt_old",
                     "home": "Sporting CP", "away": "SL Benfica", "competition": 2017}}

    sync.sync([], state, service)

    # Não foi possível remover — tem de continuar no state para se tentar
    # de novo na próxima execução, em vez de ficar órfão no calendário.
    assert "m1" in state


def test_ignores_finished_matches():
    service = make_service()
    matches = [make_match("m1", "2026-03-22T21:15:00Z", status="FINISHED")]
    state = {}

    sync.sync(matches, state, service)

    service.events.return_value.insert.assert_not_called()
    assert "m1" not in state


def test_creation_failure_does_not_crash_the_whole_batch():
    service = make_service()
    service.events.return_value.insert.return_value.execute.side_effect = [
        RuntimeError("boom"),
        {"id": "evt_ok", "summary": "⚽ Jogo"},
    ]
    matches = [
        make_match("broken", "2026-03-22T21:15:00Z"),
        make_match("fine", "2026-03-23T21:15:00Z"),
    ]
    state = {}

    sync.sync(matches, state, service)

    assert "broken" not in state
    assert state["fine"]["event_id"] == "evt_ok"


def test_build_event_body_uses_match_color_and_summary():
    match = make_match("m1", "2026-03-22T21:15:00Z", color_id="5")

    body = sync.build_event_body(match)

    assert body["summary"] == "⚽ Sporting vs SL Benfica"
    assert body["colorId"] == "5"


def test_build_event_body_falls_back_to_default_color_when_missing():
    match = make_match("m1", "2026-03-22T21:15:00Z")
    del match["colorId"]

    body = sync.build_event_body(match)

    assert body["colorId"] == "1"
