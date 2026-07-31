"""
football-calendar-sync
Sincroniza os jogos do Sporting CP e do FC Penafiel (todas as competições
oficiais listadas na respetiva página do zerozero.pt) com o Google Calendar,
detetando novos jogos e alterações de horário.

Fonte de dados: zerozero.pt (scraping, ver zerozero_scraper.py). Cada equipa
em TEAMS é normalizada para a mesma forma de "match" antes de chegar a
sync(), que trata todos os jogos da mesma maneira independentemente da
equipa de onde vieram.
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import zerozero_scraper

# Em execução local, lê GOOGLE_CREDENTIALS de um ficheiro .env (procurado na
# pasta atual e nas pastas acima). No GitHub Actions isto não faz nada — não
# há .env no runner, a env var vem dos Secrets.
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

# Equipas seguidas via scraping do zerozero.pt. Cada jogo recebe sempre a
# mesma cor por equipa, independentemente da competição — mais simples do
# que mapear cores por competição, e suficiente para distinguir as equipas
# no calendário.
#
# Cores disponíveis no Google Calendar (1–11):
# 1 lavanda, 2 sálvia, 3 uva, 4 flamingo, 5 banana, 6 tangerina,
# 7 pavão, 8 mirtilos, 9 mirtilo escuro, 10 basil, 11 tomate
TEAMS = [
    {
        "nome": "Sporting",
        "url": "https://www.zerozero.pt/equipa/sporting/jogos",
        "colorId": "2",  # verde
    },
    {
        "nome": "FC Penafiel",
        "url": "https://www.zerozero.pt/equipa/fc-penafiel/30/jogos",
        "colorId": "11",  # banana
    },
]

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
# zerozero.pt
# ---------------------------------------------------------------------------

def fetch_matches() -> list:
    """Vai buscar os próximos jogos das equipas configuradas em TEAMS. Cada
    equipa é isolada num try/except — se o zerozero.pt mudar de estrutura e
    partir o scraping de uma equipa, isso não deve impedir a sincronização
    dos jogos das outras.
    """
    matches = []
    for equipa in TEAMS:
        try:
            matches.extend(
                zerozero_scraper.fetch_team_matches(
                    equipa["nome"], equipa["url"], equipa["colorId"]
                )
            )
        except requests.exceptions.RequestException as e:
            log.error("zerozero.pt: erro ao ir buscar jogos de %s: %s", equipa["nome"], e)
        except Exception as e:
            log.error("zerozero.pt: erro inesperado ao processar %s: %s", equipa["nome"], e)
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
        "colorId": match.get("colorId", "1"),
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
    Compara os jogos obtidos com o estado guardado e sincroniza o Google Calendar.

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

    # Jogos que desapareceram da fonte (cancelados ou adiados indefinidamente)
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

    # 3. Ir buscar jogos ao zerozero.pt
    log.info("A ir buscar jogos ao zerozero.pt...")
    matches = fetch_matches()
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
