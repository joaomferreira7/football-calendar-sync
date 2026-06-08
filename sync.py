"""
football-calendar-sync
Sincroniza jogos de futebol (Primeira Liga, Segunda Liga, Champions)
com o Google Calendar, detetando novos jogos e alterações de horário.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração — edita aqui as tuas preferências
# ---------------------------------------------------------------------------

# IDs das ligas na API-Football
LEAGUES = {
    94: "Primeira Liga 🇵🇹",
    95: "Segunda Liga 🇵🇹",
    2:  "Champions League 🏆",
}

# Equipa específica a seguir (None = todas as equipas das ligas acima)
# Exemplos: 212 = FC Porto, 228 = Benfica, 229 = Sporting CP
TEAM_ID = None  # Substitui pelo ID da tua equipa se quiseres filtrar

# Janela de dias à frente a ir buscar jogos
DAYS_AHEAD = 45

# Temporada atual
SEASON = 2025

# Cores dos eventos no Google Calendar por liga (1–11)
# 1 lavanda, 2 sálvia, 3 uva, 4 flamingo, 5 banana, 6 tangerina,
# 7 pavão, 8 mirtilos, 9 mirtilo escuro, 10 basil, 11 tomate
LEAGUE_COLORS = {
    94: "10",  # verde  — Primeira Liga
    95: "6",   # laranja — Segunda Liga
    2:  "3",   # uva    — Champions
}

# Duração estimada de um jogo (minutos)
MATCH_DURATION_MINUTES = 110  # 90 + intervalo

# Lembrete antes do jogo (minutos)
REMINDER_MINUTES = 30

# Ficheiro de estado local
STATE_FILE = "fixtures_state.json"

# Calendário onde criar os eventos ("primary" = calendário principal)
CALENDAR_ID = "primary"

# ---------------------------------------------------------------------------
# Autenticação Google Calendar
# ---------------------------------------------------------------------------

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def get_calendar_service():
    """Cria e devolve o serviço da Google Calendar API."""
    credentials_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not credentials_json:
        raise EnvironmentError(
            "Variável de ambiente GOOGLE_CREDENTIALS não definida.\n"
            "Deve conter o JSON completo da Service Account."
        )
    credentials_info = json.loads(credentials_json)
    credentials = service_account.Credentials.from_service_account_info(
        credentials_info, scopes=SCOPES
    )
    # Se usares impersonation (domain-wide delegation), descomenta:
    # credentials = credentials.with_subject("o_teu_email@gmail.com")
    return build("calendar", "v3", credentials=credentials)


# ---------------------------------------------------------------------------
# API-Football
# ---------------------------------------------------------------------------

API_BASE = "https://v3.football.api-sports.io"


def _api_headers():
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise EnvironmentError("Variável de ambiente API_FOOTBALL_KEY não definida.")
    return {"x-apisports-key": key}


def fetch_fixtures_for_league(league_id: int) -> list:
    """Vai buscar os próximos jogos de uma liga na janela configurada."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")

    params = {
        "league": league_id,
        "season": SEASON,
        "from": today,
        "to": future,
    }
    if TEAM_ID:
        params["team"] = TEAM_ID

    resp = requests.get(
        f"{API_BASE}/fixtures",
        headers=_api_headers(),
        params=params,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    errors = data.get("errors", {})
    if errors:
        raise RuntimeError(f"Erro da API-Football: {errors}")

    fixtures = data.get("response", [])
    log.info("Liga %s (%s): %d jogos encontrados", league_id, LEAGUES[league_id], len(fixtures))
    return fixtures


def fetch_all_fixtures() -> list:
    """Agrega os jogos de todas as ligas configuradas."""
    all_fixtures = []
    for league_id in LEAGUES:
        try:
            fixtures = fetch_fixtures_for_league(league_id)
            all_fixtures.extend(fixtures)
        except Exception as e:
            log.error("Erro ao ir buscar liga %s: %s", league_id, e)
    return all_fixtures


# ---------------------------------------------------------------------------
# Estado local (fixtures_state.json)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Carrega o estado guardado. Devolve {} se o ficheiro não existir."""
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict):
    """Guarda o estado no ficheiro JSON."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    log.info("Estado guardado em %s", STATE_FILE)


# ---------------------------------------------------------------------------
# Helpers de data
# ---------------------------------------------------------------------------

def add_duration(iso_date: str) -> str:
    """Adiciona a duração do jogo à data de início e devolve o fim."""
    dt = datetime.fromisoformat(iso_date)
    end = dt + timedelta(minutes=MATCH_DURATION_MINUTES)
    return end.isoformat()


def friendly_date(iso_date: str) -> str:
    dt = datetime.fromisoformat(iso_date)
    return dt.strftime("%d/%m/%Y %H:%M")


# ---------------------------------------------------------------------------
# Google Calendar — operações
# ---------------------------------------------------------------------------

def build_event_body(fixture: dict) -> dict:
    """Constrói o corpo do evento para a Google Calendar API."""
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    league_id = fixture["league"]["id"]
    league_name = fixture["league"]["name"]
    round_name = fixture["league"]["round"]
    venue = fixture["fixture"]["venue"].get("name") or ""
    city = fixture["fixture"]["venue"].get("city") or ""
    start_dt = fixture["fixture"]["date"]

    location = f"{venue}, {city}".strip(", ") if venue else city

    description_lines = [
        f"🏆 {league_name}",
        f"🗓️ {round_name}",
    ]
    if venue:
        description_lines.append(f"🏟️ {venue}")
    if city:
        description_lines.append(f"📍 {city}")
    description_lines.append("")
    description_lines.append("Sincronizado automaticamente por football-calendar-sync")

    return {
        "summary": f"⚽ {home} vs {away}",
        "description": "\n".join(description_lines),
        "location": location,
        "start": {
            "dateTime": start_dt,
            "timeZone": "Europe/Lisbon",
        },
        "end": {
            "dateTime": add_duration(start_dt),
            "timeZone": "Europe/Lisbon",
        },
        "colorId": LEAGUE_COLORS.get(league_id, "1"),
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": REMINDER_MINUTES},
            ],
        },
    }


def create_calendar_event(service, fixture: dict) -> str:
    """Cria um evento no Google Calendar e devolve o event_id."""
    body = build_event_body(fixture)
    event = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    event_id = event["id"]
    log.info(
        "✅ CRIADO  [%s] %s — %s",
        friendly_date(fixture["fixture"]["date"]),
        event["summary"],
        event_id,
    )
    return event_id


def update_calendar_event(service, event_id: str, fixture: dict):
    """Atualiza um evento existente com a nova data/hora."""
    body = build_event_body(fixture)
    service.events().update(
        calendarId=CALENDAR_ID, eventId=event_id, body=body
    ).execute()
    log.info(
        "🔄 ATUALIZADO [%s] %s — %s",
        friendly_date(fixture["fixture"]["date"]),
        body["summary"],
        event_id,
    )


def delete_calendar_event(service, event_id: str, fixture_id: str):
    """Remove um evento do Google Calendar."""
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        log.info("🗑️  REMOVIDO  fixture_id=%s event_id=%s", fixture_id, event_id)
    except HttpError as e:
        if e.resp.status == 410:
            log.warning("Evento %s já não existe no calendário (410 Gone)", event_id)
        else:
            raise


# ---------------------------------------------------------------------------
# Lógica de sincronização principal
# ---------------------------------------------------------------------------

def sync(fixtures: list, state: dict, service) -> dict:
    """
    Compara os jogos da API com o estado guardado e sincroniza o Google Calendar.

    Casos tratados:
    - Novo jogo encontrado       → cria evento + guarda no estado
    - Horário alterado           → atualiza evento
    - Jogo cancelado/desapareceu → remove evento + limpa estado
    """
    api_fixture_ids = set()
    created = updated = deleted = skipped = 0

    for fixture in fixtures:
        fid = str(fixture["fixture"]["id"])
        api_fixture_ids.add(fid)
        new_date = fixture["fixture"]["date"]
        status = fixture["fixture"]["status"]["short"]

        # Ignorar jogos já terminados ou em curso
        if status in ("FT", "AET", "PEN", "LIVE", "HT", "1H", "2H", "ET", "BT", "P"):
            skipped += 1
            continue

        if fid not in state:
            # Jogo novo — criar evento
            try:
                event_id = create_calendar_event(service, fixture)
                state[fid] = {
                    "date": new_date,
                    "event_id": event_id,
                    "home": fixture["teams"]["home"]["name"],
                    "away": fixture["teams"]["away"]["name"],
                    "league": fixture["league"]["id"],
                }
                created += 1
            except HttpError as e:
                log.error("Erro ao criar evento para fixture %s: %s", fid, e)

        elif state[fid]["date"] != new_date:
            # Horário alterado — atualizar evento
            try:
                update_calendar_event(service, state[fid]["event_id"], fixture)
                state[fid]["date"] = new_date
                updated += 1
            except HttpError as e:
                if e.resp.status == 404:
                    log.warning("Evento não encontrado no Calendar, a recriar...")
                    event_id = create_calendar_event(service, fixture)
                    state[fid]["event_id"] = event_id
                    state[fid]["date"] = new_date
                    created += 1
                else:
                    log.error("Erro ao atualizar evento para fixture %s: %s", fid, e)
        else:
            skipped += 1

    # Jogos que desapareceram da API (cancelados ou adiados indefinidamente)
    for fid in list(state.keys()):
        if fid not in api_fixture_ids:
            try:
                delete_calendar_event(service, state[fid]["event_id"], fid)
                deleted += 1
            except HttpError as e:
                log.error("Erro ao remover evento para fixture %s: %s", fid, e)
            del state[fid]

    log.info(
        "Sincronização concluída — ✅ criados: %d | 🔄 atualizados: %d | 🗑️  removidos: %d | ⏭️  ignorados: %d",
        created, updated, deleted, skipped,
    )
    return state


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main():
    log.info("=== Football Calendar Sync iniciado ===")

    # 1. Autenticar Google Calendar
    log.info("A autenticar na Google Calendar API...")
    service = get_calendar_service()

    # 2. Carregar estado anterior
    state = load_state()
    log.info("Estado carregado: %d jogos em memória", len(state))

    # 3. Ir buscar jogos à API
    log.info("A ir buscar jogos à API-Football...")
    fixtures = fetch_all_fixtures()
    log.info("Total de jogos obtidos: %d", len(fixtures))

    if not fixtures:
        log.warning("Nenhum jogo encontrado. A terminar sem alterações.")
        return

    # 4. Sincronizar
    log.info("A sincronizar com o Google Calendar...")
    updated_state = sync(fixtures, state, service)

    # 5. Guardar estado atualizado
    save_state(updated_state)

    log.info("=== Concluído ===")


if __name__ == "__main__":
    main()
