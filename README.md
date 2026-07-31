# football-calendar-sync

Sincroniza automaticamente os jogos do **Sporting CP** e do **FC Penafiel** com o Google
Calendar. Sempre que um jogo é agendado (normalmente 10–15 dias antes), é criado um evento
no calendário. Se o horário mudar, o evento é atualizado. Se o jogo for cancelado, o evento
é removido.

Os jogos vêm do **zerozero.pt** (scraping da página de jogos de cada equipa, ver
`zerozero_scraper.py`) — todas as competições oficiais listadas na página, sem limite de
datas: a época toda, do primeiro ao último jogo agendado.

Corre automaticamente **4x por dia** via GitHub Actions (a cada 6h), sem qualquer servidor
ou custo — ver [Custo](#custo-total-0).

---

## Stack — tudo gratuito

| Componente | Tecnologia | Custo |
|---|---|---|
| Dados de futebol | scraping de zerozero.pt (`requests` + `beautifulsoup4`) | Gratuito |
| Calendário | Google Calendar API v3 | Gratuito |
| Autenticação Google | Service Account (OAuth2) | Gratuito |
| Linguagem | Python 3.12 | Gratuito |
| Scheduler | GitHub Actions (cron) | Gratuito |
| Persistência de estado | `fixtures_state.json` no repositório | Gratuito |

**Consumo de pedidos:** 4 execuções/dia × 1 pedido por equipa configurada em `TEAMS` ao
zerozero.pt (sem limite formal, ver [Uso responsável](#uso-responsável) abaixo).

## Estrutura do repositório

```
football-calendar-sync/
├── .github/workflows/
│   ├── sync.yml              ← cron job automático (4x por dia)
│   └── test.yml               ← corre os testes em PRs para main
├── sync.py                   ← script principal: lógica de sincronização com o Calendar
├── zerozero_scraper.py       ← scraping do zerozero.pt (fonte dos jogos)
├── test_sync.py               ← testes da lógica de sincronização (mocks, sem tocar em nada real)
├── fixtures_state.json       ← estado persistido (commitado no repo)
├── requirements.txt          ← dependências Python
├── requirements-dev.txt      ← dependências extra para testes (pytest)
└── .gitignore                ← protege credenciais de serem commitadas
```

## Como funciona o estado (`fixtures_state.json`)

Este ficheiro é o "cérebro" do sistema. Guarda a correspondência entre o ID do jogo no
zerozero.pt e o ID do evento no Google Calendar:

```json
{
  "zz-12278243": {
    "date": "2026-12-27T15:30:00+00:00",
    "event_id": "abc123def456ghi789",
    "home": "Benfica",
    "away": "Sporting",
    "competition": "zz-Liga Portugal Betclic 26/27"
  }
}
```

A cada execução:
1. Vai buscar os jogos de cada equipa em `TEAMS` (`zerozero_scraper.fetch_team_matches`)
2. Compara `match_id` com os que estão no state
3. **Novo ID** → cria evento + adiciona ao state
4. **ID existente mas data diferente** → atualiza evento + atualiza state
5. **ID no state mas não na fonte** → remove evento + apaga do state
6. Faz commit do state atualizado de volta ao repositório

O estado é guardado mesmo que a sincronização falhe a meio (ex: erro de rede num jogo
específico), para não perder o registo de eventos já criados e evitar duplicados na
execução seguinte.

---

## A fonte de dados (zerozero.pt)

`zerozero_scraper.fetch_team_matches()` lê a tabela `#team_games` da página
`zerozero.pt/equipa/.../jogos` de cada equipa (HTML estático, sem precisar de JavaScript —
confirmado a olhar para o HTML real em 2026-07-31) e devolve os jogos ainda por realizar,
já convertidos para um dict com uma forma fixa (`id`, `utcDate`, `status`, `homeTeam`,
`awayTeam`, `competition`, `matchday`, `stage`, `venue`, `colorId`). `sync.py` não sabe nem
precisa de saber que os dados vêm de scraping — trata todos os jogos da mesma forma.

Cada equipa em `TEAMS` é isolada num try/except em `fetch_matches()` — se o zerozero.pt
mudar a estrutura da página e partir o scraping de uma equipa, isso não impede a
sincronização das outras.

### Seguir outra equipa

```python
TEAMS = [
    {
        "nome": "Sporting",
        "url": "https://www.zerozero.pt/equipa/sporting/jogos",
        "colorId": "10",
    },
    {
        "nome": "FC Penafiel",
        "url": "https://www.zerozero.pt/equipa/fc-penafiel/30/jogos",
        "colorId": "5",
    },
]
```

Para encontrar o URL certo de outra equipa, pesquisa-a em zerozero.pt/pesquisa — várias
entidades podem ter nomes parecidos (ex: existem vários "Penafiel"), por isso confirma que
o URL aponta à equipa certa antes de o usares. `colorId` é a cor do Google Calendar (1–11,
ver tabela em `sync.py`) usada em todos os jogos dessa equipa.

### Se o scraping deixar de funcionar

Se `fetch_matches()` passar a devolver sempre 0 jogos para uma equipa, o zerozero.pt
provavelmente mudou a estrutura da página. Passo a passo:

1. Abre a página `jogos` da equipa (ex: `zerozero.pt/equipa/sporting/jogos`) no browser
2. Botão direito num jogo da tabela "Todos os jogos" → Inspecionar (F12)
3. Confirma se a tabela ainda tem `id="team_games"` e se a ordem das colunas de cada `<tr>`
   continua a ser: h2h, data, hora, indicador casa/fora (`(C)`/`(F)`), logo do adversário,
   nome do adversário, resultado, competição, jornada, h2h
4. Atualiza `SELETOR_LINHA_JOGO` e os índices em `celulas[...]` em `zerozero_scraper.py`

### Uso responsável

- `sync.py` faz no máximo 1 pedido por equipa por execução (4 execuções/dia agendadas)
- Não corras o script em loop apertado — é scraping de um site real, não uma API pública
  com limites documentados

---

## Configuração inicial

### 1. Google Calendar API (~20 min)

1. Cria um projeto em [console.cloud.google.com](https://console.cloud.google.com)
2. **APIs e serviços → Biblioteca** → pesquisa "Google Calendar API" → **Ativar**
3. **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço**
   - Nome: `football-sync-bot` → não é preciso atribuir papéis → **Concluído**
4. Na conta de serviço criada: separador **Chaves → Adicionar chave → JSON → Criar**
   — guarda o ficheiro descarregado

   > ⚠️ **Nunca commites este ficheiro JSON no Git.** O `.gitignore` já o protege, mas
   > confirma sempre antes de fazer push.

5. Partilha o teu calendário com a service account: no [Google Calendar](https://calendar.google.com),
   três pontos no calendário → **Definições e partilha → Partilhar com pessoas específicas →
   + Adicionar pessoas** → cola o email da service account (formato
   `football-sync-bot@<projeto>.iam.gserviceaccount.com`) → permissão **Fazer alterações a eventos**

   > ⚠️ **Não uses `CALENDAR_ID = "primary"`.** Isso refere-se ao calendário da própria
   > service account (uma conta "robô" sem calendário visível para ti), não ao teu
   > calendário pessoal — o evento é criado na mesma, só que fica invisível para ti.
   >
   > Usa antes o **ID do calendário que partilhaste**: para o teu calendário principal do
   > Google, o ID é o teu próprio email. No `sync.py`:
   > ```python
   > CALENDAR_ID = "o_teu_email@gmail.com"
   > ```
   > Se preferires um calendário separado (recomendado), cria um novo calendário
   > (ex: "⚽ Futebol"), partilha-o da mesma forma, e usa o **Calendar ID** desse
   > calendário (nas definições, formato `algo@group.calendar.google.com`).

### 2. Repositório GitHub

Cria um repositório **privado** (recomendado — contém o teu estado de jogos) e faz push
deste código.

### 3. Secrets no GitHub

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|---|---|
| `GOOGLE_CREDENTIALS` | o conteúdo **completo** do JSON da service account (incluindo `{}`) |

### 4. Testar localmente (opcional mas recomendado)

```bash
pip install -r requirements.txt

# Cria um .env local (nunca commitado) com:
#   GOOGLE_CREDENTIALS={"type": "service_account", ...}   # JSON completo, numa linha

python sync.py
```

Devias ver algo como:
```
2026-07-31 16:19:39 [INFO] === Football Calendar Sync iniciado ===
2026-07-31 16:19:39 [INFO] A autenticar na Google Calendar API...
2026-07-31 16:19:39 [INFO] Estado carregado: 68 jogos em memória
2026-07-31 16:19:39 [INFO] A ir buscar jogos ao zerozero.pt...
2026-07-31 16:19:39 [INFO] zerozero.pt: 34 jogo(s) futuro(s) encontrados para Sporting
2026-07-31 16:19:40 [INFO] zerozero.pt: 34 jogo(s) futuro(s) encontrados para FC Penafiel
2026-07-31 16:19:40 [INFO] Total de jogos obtidos: 68
2026-07-31 16:19:41 [INFO] ✅ CRIADO  [16/05/2027 15:30] ⚽ Santa Clara vs Sporting — 8s6h7fjq98muddp01b2pbvtkb0
...
2026-07-31 16:20:17 [INFO] Sincronização concluída — ✅ criados: 34 | 🔄 atualizados: 0 | 🗑️  removidos: 34 | ⏭️  ignorados: 34
```

#### Testes automatizados

```bash
pip install -r requirements-dev.txt
python -m pytest test_sync.py -v
```

Usam mocks — não tocam no zerozero.pt real nem no teu Google Calendar.

### 5. Ativar o cron no GitHub Actions

No repositório → separador **Actions** → (se pedir) **I understand my workflows, go ahead
and enable them** → **Football Calendar Sync → Run workflow** para testar manualmente a
primeira vez.

A partir daí corre sozinho, 4x por dia (ver [Mudar a frequência do cron](#mudar-a-frequência-do-cron)
para ajustar).

---

## Personalização

### Seguir outra equipa

Ver [Seguir outra equipa](#seguir-outra-equipa) em cima — edita a lista `TEAMS` em `sync.py`.

### Usar um calendário separado para futebol (recomendado)

Cria um calendário dedicado no Google Calendar, partilha-o com a service account (passo
1 acima) e usa o **Calendar ID** desse calendário:
```python
CALENDAR_ID = "c_abc123xyz@group.calendar.google.com"
```

### Mudar a duração estimada dos jogos

```python
MATCH_DURATION_MINUTES = 110  # 90 min + intervalo
```

### Mudar o lembrete

```python
REMINDER_MINUTES = 30  # lembrete 30 min antes
```

### Mudar a frequência do cron

Em `.github/workflows/sync.yml`:
```yaml
- cron: '0 8,14,20,2 * * *'   # 4x/dia — 8h,14h,20h,2h UTC = 9h,15h,21h,3h Lisboa
```
Sintaxe cron: `minuto hora dia-mês mês dia-semana`. Cada horário adicional soma ~1
pedido/dia ao zerozero.pt por equipa e ~2 min/execução à quota do GitHub Actions (limite
gratuito: 2.000 min/mês).

---

## Troubleshooting

**"GOOGLE_CREDENTIALS não definida"** — confirma o Secret `GOOGLE_CREDENTIALS` no GitHub
(ou a variável de ambiente/`.env`, se testares localmente) e que contém o JSON completo.

**Eventos não aparecem no calendário:**
1. **`CALENDAR_ID = "primary"` é o erro mais comum** — isso é o calendário da service
   account, não o teu. O script não dá erro nenhum neste caso (o evento é criado na mesma,
   só que num calendário que não vês), por isso é fácil passar despercebido.
2. Confirma que o calendário foi partilhado com o email da service account
3. Confirma que as permissões são "Fazer alterações a eventos" (não só "Ver eventos")

**"403 Forbidden" da Google Calendar API** — a service account não tem permissão para
escrever no calendário; volta ao passo 1 e confirma a partilha.

**`fetch_matches()` devolve sempre 0 jogos para uma equipa** — o zerozero.pt provavelmente
mudou a estrutura da página. Ver [Se o scraping deixar de funcionar](#se-o-scraping-deixar-de-funcionar).

**O workflow não corre automaticamente** — GitHub pode atrasar crons em repositórios com
pouca atividade; um commit qualquer "acorda" o repositório. Podes sempre correr
manualmente em **Actions → Run workflow**.

---

## Segurança

- **Nunca commites** o ficheiro JSON da service account
- Usa sempre **GitHub Secrets** para credenciais
- Mantém o repositório como **privado**
- O `.gitignore` já está configurado para proteger ficheiros de credenciais (`.env`,
  `*.json` de service account, etc.)
- A service account só tem acesso ao calendário que tu partilhaste — não tem acesso a mais
  nada da tua conta Google

## Custo total: 0€

| Serviço | Plano | Limite gratuito | Uso estimado |
|---|---|---|---|
| zerozero.pt (scraping) | — | sem limite formal | ~4 pedidos/dia por equipa |
| Google Calendar API | Free | Sem limite prático para uso pessoal | ~5 operações/dia |
| GitHub Actions | Free | 2.000 min/mês | ~4 min/dia = ~120 min/mês |
