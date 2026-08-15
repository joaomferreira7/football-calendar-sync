"""Scraper de jogos do zerozero.pt — fonte de dados de sync.py para todas as
equipas seguidas (ver TEAMS em sync.py). Cada jogo é normalizado para um
dict com uma forma fixa e estável ("match": id, utcDate, status, homeTeam,
awayTeam, competition, matchday, stage, venue, colorId), para que o resto do
sync.py não precise de saber nada sobre a origem dos dados.

A tabela de jogos vem no HTML estático da página, dentro de
<div id="team_games"><table class="zztable stats">. Cada <tr> tem (pelo
menos) 8 <td> filhos diretos, nesta ordem: h2h, data, hora, indicador
casa/fora ("(C)" ou "(F)"), logo do adversário, nome do adversário,
resultado, competição. Estrutura confirmada em 2026-07-31 a olhar para o
HTML real devolvido pelo site (ver zerozero-scraper/README.md para o
passo-a-passo caso deixe de bater certo).
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

LISBOA = ZoneInfo("Europe/Lisbon")

SELETOR_LINHA_JOGO = "#team_games table.zztable tbody tr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _texto_do_link(celula):
    link = celula.find("a")
    return link.get_text(strip=True) if link else celula.get_text(strip=True)


def fetch_team_matches(nome_exibicao: str, url: str, color_id: str) -> list:
    """Vai buscar TODOS os próximos jogos (ainda sem resultado) de uma
    equipa ao zerozero.pt — sem limite de dias à frente.

    Devolve uma lista de dicts na forma de "match" usada por sync.py (id,
    utcDate, status, homeTeam, awayTeam, competition, matchday, stage,
    venue), mais um "colorId" explícito por equipa.
    """
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    linhas = soup.select(SELETOR_LINHA_JOGO)

    agora = datetime.now(LISBOA)

    matches = []
    for linha in linhas:
        match_id = linha.get("id")
        if not match_id:
            # A página tem dois elementos com id="team_games" (HTML
            # inválido): o segundo é a tabela de jogos que queremos, mas o
            # primeiro é uma tabela de resumo por competição (jogos, vitórias,
            # pontos, ...) que o seletor acima também apanha. As suas linhas
            # não têm id, ao contrário das linhas de jogos reais — usa-se
            # isso para as ignorar, em vez de depender da ordem das tabelas.
            continue

        celulas = linha.find_all("td", recursive=False)
        if len(celulas) < 8:
            continue

        data_txt = celulas[1].get_text(strip=True)
        hora_txt = celulas[2].get_text(strip=True)
        if not hora_txt:
            # Hora ainda por confirmar pelo zerozero.pt — não dá para criar
            # um evento fiável no calendário, por isso ignora-se este jogo
            # (a próxima sincronização apanha-o assim que a hora aparecer).
            continue

        try:
            kickoff_naive = datetime.strptime(f"{data_txt} {hora_txt}", "%Y-%m-%d %H:%M")
        except ValueError:
            log.warning("zerozero.pt: data/hora com formato inesperado: %r %r", data_txt, hora_txt)
            continue
        kickoff = kickoff_naive.replace(tzinfo=LISBOA)

        if kickoff < agora:
            continue

        resultado = _texto_do_link(celulas[6])
        if resultado and resultado != "-":
            # já tem resultado -> já foi jogado (ou está a decorrer)
            continue

        indicador = celulas[3].get_text(strip=True)
        adversario = _texto_do_link(celulas[5])
        competicao = _texto_do_link(celulas[7])
        jornada = celulas[8].get_text(strip=True) if len(celulas) > 8 else ""

        if "C" in indicador:
            home, away = nome_exibicao, adversario
        else:
            home, away = adversario, nome_exibicao

        matches.append(
            {
                # Prefixo "zz-" para deixar claro, no fixtures_state.json,
                # que este id pertence ao espaço de ids do zerozero.pt.
                "id": f"zz-{match_id}",
                "utcDate": kickoff.isoformat(),
                "status": "SCHEDULED",
                "homeTeam": {"name": home},
                "awayTeam": {"name": away},
                "competition": {"id": f"zz-{competicao}", "name": competicao},
                "matchday": None,
                "stage": jornada,
                "venue": "",
                "colorId": color_id,
            }
        )

    log.info("zerozero.pt: %d jogo(s) futuro(s) encontrados para %s", len(matches), nome_exibicao)
    return matches
