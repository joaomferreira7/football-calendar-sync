# football-calendar-sync

Sincroniza automaticamente os jogos do **Sporting CP** com o Google Calendar.
Sempre que um jogo é agendado (normalmente 10–15 dias antes), é criado um evento no calendário.
Se o horário mudar, o evento é atualizado. Se o jogo for cancelado, o evento é removido.

**Competições cobertas (plano gratuito da football-data.org):**
- Primeira Liga Portuguesa
- Champions League

Os jogos vêm diretamente do endpoint `/v4/teams/{id}/matches` da equipa (Sporting CP),
por isso não é preciso filtrar nada localmente — tudo o que a API devolve já é do clube.

Corre automaticamente **4x por dia** via GitHub Actions (a cada 6h), sem qualquer servidor
ou custo — ver [Custo](#custo-total-0).

---

## Stack — tudo gratuito

| Componente | Tecnologia | Custo |
|---|---|---|
| Dados de futebol | football-data.org API v4 | Gratuito — 10 pedidos/minuto |
| Calendário | Google Calendar API v3 | Gratuito |
| Autenticação Google | Service Account (OAuth2) | Gratuito |
| Linguagem | Python 3.12 | Gratuito |
| Scheduler | GitHub Actions (cron) | Gratuito |
| Persistência de estado | `fixtures_state.json` no repositório | Gratuito |

**Consumo de requests:** 4 execuções/dia × 1 pedido (`/v4/teams/{id}/matches` já traz as
duas competições de uma vez) = 4 requests/dia (do limite de 10/min).

## Estrutura do repositório

```
football-calendar-sync/
├── .github/workflows/sync.yml   ← cron job automático (4x por dia)
├── sync.py                      ← script principal de sincronização
├── test_sync.py                 ← testes da lógica de sincronização (mocks, sem tocar em APIs reais)
├── fixtures_state.json          ← estado persistido (commitado no repo)
├── requirements.txt             ← dependências Python
├── requirements-dev.txt         ← dependências extra para testes (pytest)
└── .gitignore                   ← protege credenciais de serem commitadas
```

## Como funciona o estado (`fixtures_state.json`)

Este ficheiro é o "cérebro" do sistema. Guarda a correspondência entre o ID do jogo na API
e o ID do evento no Google Calendar:

```json
{
  "497583": {
    "date": "2026-03-22T21:15:00Z",
    "event_id": "abc123def456ghi789",
    "home": "Sporting CP",
    "away": "SL Benfica",
    "competition": 2017
  }
}
```

A cada execução:
1. Vai buscar os jogos do Sporting CP nas competições configuradas (`/v4/teams/498/matches`)
2. Compara `match_id` com os que estão no state
3. **Novo ID** → cria evento + adiciona ao state
4. **ID existente mas data diferente** → atualiza evento + atualiza state
5. **ID no state mas não na API** → remove evento + apaga do state
6. Faz commit do state atualizado de volta ao repositório

O estado é guardado mesmo que a sincronização falhe a meio (ex: erro de rede num jogo
específico), para não perder o registo de eventos já criados e evitar duplicados na
execução seguinte.

---

## Configuração inicial

### 1. Conta na football-data.org (~5 min)

1. Vai a [football-data.org/client/register](https://www.football-data.org/client/register) e regista-te (grátis, sem cartão de crédito)
2. Vais receber o teu **API Token** por email — **confirma o email através do link enviado**,
   caso contrário a conta e os dados são apagados automaticamente ao fim de um tempo de inatividade
3. Testa no terminal:
   ```bash
   curl -H "X-Auth-Token: o_teu_token" "https://api.football-data.org/v4/teams/498/matches?competitionIds=2017,2001"
   ```

**IDs já usados no `sync.py`:**

| Recurso | ID |
|---|---|
| Sporting Clube de Portugal (equipa) | `498` |
| Primeira Liga Portuguesa (competição) | `2017` |
| UEFA Champions League (competição) | `2001` |

> 💡 A API distingue **código** (`PPL`, `CL` — usado em `/v4/competitions/{code}`) de
> **ID numérico** (`2017`, `2001` — exigido pelo parâmetro `competitionIds`). Para outros
> IDs, consulta `/v4/competitions/{code}` (devolve o `id`) ou `/v4/competitions/{code}/teams`.

**Rate limiting:** a API devolve o header `X-Requests-Available-Minute` com os pedidos que
ainda restam na janela atual, e um `Retry-After` quando responde 429. O `sync.py` lê estes
headers, regista a quota restante no log e, se apanhar um 429, espera o tempo indicado e
tenta uma vez mais.

### 2. Google Calendar API (~20 min)

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
   > (ex: "⚽ Sporting"), partilha-o da mesma forma, e usa o **Calendar ID** desse
   > calendário (nas definições, formato `algo@group.calendar.google.com`).

### 3. Repositório GitHub

Cria um repositório **privado** (recomendado — contém o teu estado de jogos) e faz push
deste código.

### 4. Secrets no GitHub

No repositório: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Valor |
|---|---|
| `FOOTBALL_DATA_TOKEN` | o token recebido por email da football-data.org |
| `GOOGLE_CREDENTIALS` | o conteúdo **completo** do JSON da service account (incluindo `{}`) |

### 5. Testar localmente (opcional mas recomendado)

```bash
pip install -r requirements.txt

# Cria um .env local (nunca commitado) com:
#   FOOTBALL_DATA_TOKEN=o_teu_token
#   GOOGLE_CREDENTIALS={"type": "service_account", ...}   # JSON completo, numa linha

python sync.py
```

Devias ver algo como:
```
2026-07-13 10:00:01 [INFO] === Football Calendar Sync iniciado ===
2026-07-13 10:00:02 [INFO] Jogos encontrados para a equipa 498: 3
2026-07-13 10:00:04 [INFO] ✅ CRIADO  [22/03/2026 21:15] ⚽ Sporting CP vs SL Benfica — evt_abc123
...
2026-07-13 10:00:06 [INFO] Sincronização concluída — ✅ criados: 3 | 🔄 atualizados: 0 | 🗑️ removidos: 0 | ⏭️ ignorados: 0
```

**Testar já com jogos reais** (antes de a Primeira Liga começar): muda temporariamente
`TEAM_ID`/`COMPETITIONS`/`COMPETITION_COLORS` no `sync.py` para uma competição a decorrer
(ex: `TEAM_ID = 760` — Espanha, `COMPETITIONS = {2000: "FIFA World Cup 🌍"}`), corre, confirma
no calendário, e reverte.

#### Testes automatizados

```bash
pip install -r requirements-dev.txt
python -m pytest test_sync.py -v
```

Usam mocks — não tocam na API real nem no teu Google Calendar.

### 6. Ativar o cron no GitHub Actions

No repositório → separador **Actions** → (se pedir) **I understand my workflows, go ahead
and enable them** → **Football Calendar Sync → Run workflow** para testar manualmente a
primeira vez.

A partir daí corre sozinho, 4x por dia (ver [Personalização](#mudar-a-frequência-do-cron)
para ajustar).

---

## Personalização

### Seguir outro clube

```python
TEAM_ID = 498  # Sporting CP
```
Consulta `/v4/competitions/{code}/teams` para encontrar o ID da equipa pretendida.

### Adicionar ou remover competições

Usa sempre **IDs numéricos**, não os códigos (consulta `/v4/competitions/{code}` para
encontrar o `id`):
```python
COMPETITIONS = {
    2017: "Primeira Liga 🇵🇹",
    2001: "Champions League 🏆",
    2146: "Liga Europa 🌍",    # adicionar
}
COMPETITION_COLORS = {
    2017: "10",
    2001: "3",
    2146: "7",    # cor correspondente
}
```

### Usar um calendário separado para futebol (recomendado)

Cria um calendário dedicado no Google Calendar, partilha-o com a service account (passo
2 acima) e usa o **Calendar ID** desse calendário:
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
Sintaxe cron: `minuto hora dia-mês mês dia-semana`. Cada horário adicional soma ~1 request/dia
à quota da football-data.org (limite: 10/minuto) e ~2 min/execução à quota do GitHub Actions
(limite gratuito: 2.000 min/mês).

---

## Troubleshooting

**"FOOTBALL_DATA_TOKEN não definida"** — confirma o Secret `FOOTBALL_DATA_TOKEN` no GitHub
(ou a variável de ambiente/`.env`, se testares localmente).

**"GOOGLE_CREDENTIALS não definida"** — confirma o Secret `GOOGLE_CREDENTIALS` no GitHub e
que contém o JSON completo.

**Eventos não aparecem no calendário:**
1. **`CALENDAR_ID = "primary"` é o erro mais comum** — isso é o calendário da service
   account, não o teu. O script não dá erro nenhum neste caso (o evento é criado na mesma,
   só que num calendário que não vês), por isso é fácil passar despercebido.
2. Confirma que o calendário foi partilhado com o email da service account
3. Confirma que as permissões são "Fazer alterações a eventos" (não só "Ver eventos")
4. Confirma os IDs testando diretamente:
   `curl -H "X-Auth-Token: ..." "https://api.football-data.org/v4/teams/498/matches?competitionIds=2017,2001"`

**"403 Forbidden" da Google Calendar API** — a service account não tem permissão para
escrever no calendário; volta ao passo 2 e confirma a partilha.

**"429 Too Many Requests" da football-data.org** — o `sync.py` já trata isto
automaticamente (lê `Retry-After`, espera, tenta uma vez mais). Se persistir, o script está
a correr demasiadas vezes seguidas (ex: testes manuais em loop) — espera um minuto.

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
| football-data.org | Free | 10 pedidos/minuto | ~4 pedidos/dia |
| Google Calendar API | Free | Sem limite prático para uso pessoal | ~5 operações/dia |
| GitHub Actions | Free | 2.000 min/mês | ~4 min/dia = ~120 min/mês |
