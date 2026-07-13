"""
football-calendar-sync
Sincroniza os jogos do Sporting CP (Primeira Liga e Champions League)
com o Google Calendar, detetando novos jogos e alterações de horário.

Fonte de dados: football-data.org (plano gratuito).
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Em execução local, lê FOOTBALL_DATA_TOKEN/GOOGLE_CREDENTIALS de um ficheiro
# .env (procurado na pasta atual e nas pastas acima). No GitHub Actions isto
# não faz nada — não há .env no runner, as env vars vêm dos Secrets.
load_dotenv()

# Os logs usam emojis; a codepage por omissão do terminal do Windows (cp1252)
# não os consegue codificar e o script rebenta com UnicodeEncodeError.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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

# ID da equipa a seguir na football-data.org (endpoint /v4/teams/{id}/matches
# já devolve só os jogos desta equipa, não é preciso filtrar mais nada).
# Sporting CP = 498.
#
# Para testar com jogos que estejam mesmo a acontecer (ex: enquanto a
# Primeira Liga ainda não começou), troca temporariamente por:
#   TEAM_ID = 760                          # Seleção Espanhola
#   COMPETITIONS = {2000: "FIFA World Cup 🌍"}
TEAM_ID = 498

# IDs numéricos das competições a incluir — a API exige o ID aqui, não o
# código (ex: Primeira Liga é "PPL" como código mas 2017 como ID).
COMPETITIONS = {
    2017: "Primeira Liga 🇵🇹",
    2001: "Champions League 🏆",
}

# Janela de dias à frente a ir buscar jogos
DAYS_AHEAD = 45

# Cores dos eventos no Google Calendar por competição (1–11)
# 1 lavanda, 2 sálvia, 3 uva, 4 flamingo, 5 banana, 6 tangerina,
# 7 pavão, 8 mirtilos, 9 mirtilo escuro, 10 basil, 11 tomate
COMPETITION_COLORS = {
    2017: "10",  # verde — Primeira Liga
    2001: "3",   # uva   — Champions League
}

# Estados de jogo a ignorar (já aconteceram ou não vão realizar-se como previsto)
IGNORED_STATUSES = {"FINISHED", "IN_PLAY", "PAUSED", "CANCELLED"}

# Duração estimada de um jogo (minutos)
MATCH_DURATION_MINUTES = 110  # 90 + intervalo

# Lembrete antes do jogo (minutos)
REMINDER_MINUTES = 30

# Ficheiro de estado local
STATE_FILE = "fixtures_state.json"

# Calendário onde criar os eventos. NÃO uses "primary" — isso refere-se ao
# calendário da própria Service Account (que não é visível para ti), não ao
# teu calendário pessoal. Usa o ID do calendário que partilhaste (Fase 2.4):
# para um Google Calendar pessoal, o ID é o teu próprio email da Google.
CALENDAR_ID = "joaof89036@gmail.com"

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
# football-data.org
# ---------------------------------------------------------------------------

API_BASE = "https://api.football-data.org/v4"


def _api_headers():
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        raise EnvironmentError("Variável de ambiente FOOTBALL_DATA_TOKEN não definida.")
    return {"X-Auth-Token": token}


def _api_get(url: str, params: dict):
    """GET à football-data.org que respeita os headers de rate limit.

    A API expõe X-Requests-Available-Minute (pedidos que ainda restam
    na janela atual) e, num 429, Retry-After. Como só fazemos ~1 pedido
    por execução isto raramente entra em ação, mas protege execuções
    manuais/testes repetidos de seguida contra o rate limiter.
    """
    resp = requests.get(url, headers=_api_headers(), params=params, timeout=15)

    remaining = resp.headers.get("X-Requests-Available-Minute")
    if remaining is not None:
        log.info("Pedidos disponíveis neste minuto (football-data.org): %s", remaining)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 60))
        log.warning("Rate limit atingido (429). A aguardar %ds antes de repetir...", retry_after)
        time.sleep(retry_after)
        resp = requests.get(url, headers=_api_headers(), params=params, timeout=15)

    resp.raise_for_status()
    return resp


def fetch_all_matches() -> list:
    """Vai buscar, numa única chamada, os próximos jogos da equipa (TEAM_ID)
    nas competições configuradas."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    future = (datetime.now(timezone.utc) + timedelta(days=DAYS_AHEAD)).strftime("%Y-%m-%d")

    params = {
        "competitionIds": ",".join(str(c) for c in COMPETITIONS),
        "dateFrom": today,
        "dateTo": future,
    }

    resp = _api_get(f"{API_BASE}/teams/{TEAM_ID}/matches", params=params)
    data = resp.json()

    matches = data.get("matches", [])
    log.info("Jogos encontrados para a equipa %s: %d", TEAM_ID, len(matches))
    return matches


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

def build_event_body(match: dict) -> dict:
    """Constrói o corpo do evento para a Google Calendar API."""
    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    competition_id = match["competition"]["id"]
    competition_name = match["competition"]["name"]
    matchday = match.get("matchday")
    stage = match.get("stage")
    venue = match.get("venue") or ""
    start_dt = match["utcDate"]

    round_label = f"Jornada {matchday}" if matchday else (stage or "")

    description_lines = [f"🏆 {competition_name}"]
    if round_label:
        description_lines.append(f"🗓️ {round_label}")
    if venue:
        description_lines.append(f"🏟️ {venue}")
    description_lines.append("")
    description_lines.append("Sincronizado automaticamente por football-calendar-sync")

    return {
        "summary": f"⚽ {home} vs {away}",
        "description": "\n".join(description_lines),
        "location": venue,
        "start": {
            "dateTime": start_dt,
            "timeZone": "Europe/Lisbon",
        },
        "end": {
            "dateTime": add_duration(start_dt),
            "timeZone": "Europe/Lisbon",
        },
        "colorId": COMPETITION_COLORS.get(competition_id, "1"),
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": REMINDER_MINUTES},
            ],
        },
    }


def create_calendar_event(service, match: dict) -> str:
    """Cria um evento no Google Calendar e devolve o event_id."""
    body = build_event_body(match)
    event = service.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    event_id = event["id"]
    log.info(
        "✅ CRIADO  [%s] %s — %s",
        friendly_date(match["utcDate"]),
        event["summary"],
        event_id,
    )
    return event_id


def update_calendar_event(service, event_id: str, match: dict):
    """Atualiza um evento existente com a nova data/hora."""
    body = build_event_body(match)
    service.events().update(
        calendarId=CALENDAR_ID, eventId=event_id, body=body
    ).execute()
    log.info(
        "🔄 ATUALIZADO [%s] %s — %s",
        friendly_date(match["utcDate"]),
        body["summary"],
        event_id,
    )


def delete_calendar_event(service, event_id: str, match_id: str):
    """Remove um evento do Google Calendar."""
    try:
        service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
        log.info("🗑️  REMOVIDO  match_id=%s event_id=%s", match_id, event_id)
    except HttpError as e:
        if e.resp.status == 410:
            log.warning("Evento %s já não existe no calendário (410 Gone)", event_id)
        else:
            raise


# ---------------------------------------------------------------------------
# Lógica de sincronização principal
# ---------------------------------------------------------------------------

def sync(matches: list, state: dict, service) -> dict:
    """
    Compara os jogos da API com o estado guardado e sincroniza o Google Calendar.

    Casos tratados:
    - Novo jogo encontrado       → cria evento + guarda no estado
    - Horário alterado           → atualiza evento
    - Jogo cancelado/desapareceu → remove evento + limpa estado
    """
    api_match_ids = set()
    created = updated = deleted = skipped = 0

    for match in matches:
        mid = str(match["id"])
        api_match_ids.add(mid)
        new_date = match["utcDate"]
        status = match["status"]

        # Ignorar jogos já terminados, a decorrer ou cancelados
        if status in IGNORED_STATUSES:
            skipped += 1
            continue

        if mid not in state:
            # Jogo novo — criar evento
            try:
                event_id = create_calendar_event(service, match)
                state[mid] = {
                    "date": new_date,
                    "event_id": event_id,
                    "home": match["homeTeam"]["name"],
                    "away": match["awayTeam"]["name"],
                    "competition": match["competition"]["id"],
                }
                created += 1
            except Exception as e:
                log.error("Erro ao criar evento para jogo %s: %s", mid, e)

        elif state[mid]["date"] != new_date:
            # Horário alterado — atualizar evento
            try:
                update_calendar_event(service, state[mid]["event_id"], match)
                state[mid]["date"] = new_date
                updated += 1
            except HttpError as e:
                if e.resp.status == 404:
                    log.warning("Evento não encontrado no Calendar, a recriar...")
                    try:
                        event_id = create_calendar_event(service, match)
                        state[mid]["event_id"] = event_id
                        state[mid]["date"] = new_date
                        created += 1
                    except Exception as e2:
                        log.error("Erro ao recriar evento para jogo %s: %s", mid, e2)
                else:
                    log.error("Erro ao atualizar evento para jogo %s: %s", mid, e)
            except Exception as e:
                log.error("Erro ao atualizar evento para jogo %s: %s", mid, e)
        else:
            skipped += 1

    # Jogos que desapareceram da API (cancelados ou adiados indefinidamente)
    for mid in list(state.keys()):
        if mid not in api_match_ids:
            try:
                delete_calendar_event(service, state[mid]["event_id"], mid)
                deleted += 1
                del state[mid]
            except Exception as e:
                # Não apaga do state em caso de falha — assim a próxima
                # execução tenta remover o evento outra vez, em vez de
                # ficar órfão no calendário para sempre.
                log.error("Erro ao remover evento para jogo %s: %s", mid, e)

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
    log.info("A ir buscar jogos à football-data.org...")
    matches = fetch_all_matches()
    log.info("Total de jogos obtidos: %d", len(matches))

    if not matches:
        log.warning("Nenhum jogo encontrado. A terminar sem alterações.")
        return

    # 4. Sincronizar
    # `state` é atualizado in-place por sync(), por isso guardamo-lo sempre
    # no finally — mesmo que uma exceção interrompa o processo a meio,
    # não perdemos o registo dos eventos já criados/atualizados/removidos
    # (o que evitaria duplicados na próxima execução).
    log.info("A sincronizar com o Google Calendar...")
    try:
        sync(matches, state, service)
    finally:
        save_state(state)

    log.info("=== Concluído ===")


if __name__ == "__main__":
    main()
