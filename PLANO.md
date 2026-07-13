# Football Calendar Sync — Plano Completo de Implementação

## O que este projeto faz

Sincroniza automaticamente os jogos do **Sporting CP** com o teu Google Calendar.
Sempre que um jogo é agendado (normalmente 10–15 dias antes), é criado um evento no calendário.
Se o horário mudar, o evento é atualizado. Se o jogo for cancelado, o evento é removido.

**Competições cobertas (plano gratuito da football-data.org):**
- Primeira Liga Portuguesa
- Champions League

Os jogos vêm diretamente do endpoint `/v4/teams/{id}/matches` da equipa (Sporting CP),
por isso não é preciso filtrar nada localmente — tudo o que a API devolve já é do clube.

---

## Stack tecnológico — tudo gratuito

| Componente | Tecnologia | Custo |
|---|---|---|
| Dados de futebol | football-data.org API v4 | Gratuito — 10 pedidos/minuto |
| Calendário | Google Calendar API v3 | Gratuito |
| Autenticação Google | Service Account (OAuth2) | Gratuito |
| Linguagem | Python 3.12 | Gratuito |
| Scheduler | GitHub Actions (cron) | Gratuito |
| Persistência de estado | `fixtures_state.json` no repositório | Gratuito |

**Consumo de requests:** 1 execução/dia × 1 pedido (`/v4/teams/{id}/matches` já traz as duas competições de uma vez) = 1 request/dia (do limite de 10/min).

---

## Estrutura do repositório

```
football-calendar-sync/
├── .github/
│   └── workflows/
│       └── sync.yml          ← cron job automático (2× por dia)
├── sync.py                   ← script principal de sincronização
├── test_sync.py              ← testes da lógica de sincronização (mocks, sem tocar em APIs reais)
├── fixtures_state.json       ← estado persistido (commitado no repo)
├── requirements.txt          ← dependências Python
├── requirements-dev.txt      ← dependências extra para testes (pytest)
├── .gitignore                ← protege credenciais de serem commitadas
└── PLANO.md                  ← este ficheiro
```

---

## Fase 1 — Criar conta na football-data.org

**Tempo estimado: 5 minutos**

1. Vai a [football-data.org/client/register](https://www.football-data.org/client/register) e regista-te (grátis, sem cartão de crédito)
2. Vais receber o teu **API Token** por email — **confirma o email através do link enviado**,
   caso contrário a conta e os dados são apagados automaticamente ao fim de um tempo de inatividade
3. Testa no browser ou terminal para confirmar que funciona:
   ```bash
   curl -H "X-Auth-Token: o_teu_token" "https://api.football-data.org/v4/teams/498/matches?competitionIds=2017,2001&dateFrom=2026-08-01&dateTo=2027-06-01"
   ```
   (deves ver os próximos jogos do Sporting CP na Primeira Liga e na Champions League)

**IDs já confirmados e usados no `sync.py`:**
| Recurso | ID |
|---|---|
| Sporting Clube de Portugal (equipa) | `498` |
| Primeira Liga Portuguesa (competição) | `2017` |
| UEFA Champions League (competição) | `2001` |

> 💡 Nota: a API distingue **código** (`PPL`, `CL` — usado em `/v4/competitions/{code}`)
> de **ID numérico** (`2017`, `2001` — exigido pelo parâmetro `competitionIds` do
> endpoint de jogos por equipa). Se precisares de outros IDs, consulta
> `/v4/competitions/{code}` (devolve o `id`) ou `/v4/competitions/{code}/teams` (lista
> equipas e os seus `id`).

**Rate limiting:** a API devolve o header `X-Requests-Available-Minute` com os pedidos que
ainda restam na janela atual, e um `Retry-After` quando responde 429. O `sync.py` lê estes
headers, regista a quota restante no log e, se apanhar um 429, espera o tempo indicado e
tenta uma vez mais — como o script só faz 1 pedido por execução isto raramente é necessário,
mas protege testes manuais repetidos em pouco tempo.

---

## Fase 2 — Configurar a Google Calendar API

**Tempo estimado: 20 minutos**

### 2.1 Criar projeto no Google Cloud

1. Vai a [console.cloud.google.com](https://console.cloud.google.com)
2. Clica em **Selecionar projeto** → **Novo projeto**
3. Nome: `football-calendar-sync` → **Criar**

### 2.2 Ativar a Calendar API

1. No menu lateral: **APIs e serviços** → **Biblioteca**
2. Pesquisa "Google Calendar API"
3. Clica em **Ativar**

### 2.3 Criar a Service Account

1. **APIs e serviços** → **Credenciais** → **Criar credenciais** → **Conta de serviço**
2. Nome: `football-sync-bot` → **Criar e continuar**
3. Não é preciso atribuir papéis → **Continuar** → **Concluído**
4. Clica na conta de serviço criada
5. Separador **Chaves** → **Adicionar chave** → **Criar nova chave** → **JSON** → **Criar**
6. Guarda o ficheiro JSON descarregado — vais precisar dele a seguir

> ⚠️ **Nunca commites este ficheiro JSON no Git.**
> O `.gitignore` já está configurado para o proteger,
> mas confirma sempre antes de fazer push.

### 2.4 Partilhar o teu calendário com a Service Account

1. Abre [Google Calendar](https://calendar.google.com)
2. No calendário que queres usar, clica nos **três pontos** → **Definições e partilha**
3. Em **Partilhar com pessoas específicas**, clica em **+ Adicionar pessoas**
4. Cola o email da Service Account (parecido com `football-sync-bot@football-calendar-sync.iam.gserviceaccount.com`)
5. Permissões: **Fazer alterações a eventos** → **Enviar**

> ⚠️ **Não uses `CALENDAR_ID = "primary"`.** Isso refere-se ao calendário da
> própria Service Account (uma conta "robô" sem calendário visível para ti) —
> não ao teu calendário pessoal, mesmo depois de o partilhares. Os eventos são
> criados na mesma, só que ficam invisíveis para ti.
>
> Usa antes o **ID do calendário que partilhaste**: para o teu calendário
> principal do Google, o ID é o teu próprio email do Google (o mesmo endereço
> com que fizeste a partilha no passo 4 acima). No `sync.py`:
> ```python
> CALENDAR_ID = "o_teu_email@gmail.com"
> ```
> Se preferires um calendário separado (recomendado para manter organizado),
> cria um novo calendário chamado "Sporting", partilha-o com a service account
> da mesma forma, e usa o **Calendar ID** desse calendário (visível nas
> definições do calendário, tem o formato `algo@group.calendar.google.com`).

---

## Fase 3 — Criar o repositório no GitHub

**Tempo estimado: 10 minutos**

1. Cria um repositório **privado** no GitHub (recomendado — contém o teu estado de jogos)
   - Nome: `football-calendar-sync`
   - Visibilidade: **Private**

2. Clona localmente e copia os ficheiros deste projeto:
   ```bash
   git clone https://github.com/o_teu_username/football-calendar-sync.git
   cd football-calendar-sync
   # Copia sync.py, test_sync.py, requirements*.txt, .gitignore, fixtures_state.json
   # e a pasta .github/ para aqui
   ```

3. Faz o primeiro commit:
   ```bash
   git add .
   git commit -m "feat: initial setup"
   git push
   ```

---

## Fase 4 — Configurar os Secrets no GitHub

**Tempo estimado: 5 minutos**

Os segredos são armazenados de forma segura no GitHub e nunca ficam expostos nos logs.

1. No repositório GitHub: **Settings** → **Secrets and variables** → **Actions**
2. Clica em **New repository secret** para cada um:

### Secret 1: `FOOTBALL_DATA_TOKEN`
- **Name:** `FOOTBALL_DATA_TOKEN`
- **Value:** o token que recebeste por email da football-data.org

### Secret 2: `GOOGLE_CREDENTIALS`
- **Name:** `GOOGLE_CREDENTIALS`
- **Value:** o conteúdo **completo** do ficheiro JSON da Service Account

  Abre o JSON no editor de texto e copia tudo, incluindo as chavetas `{}`:
  ```json
  {
    "type": "service_account",
    "project_id": "football-calendar-sync",
    "private_key_id": "...",
    "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
    "client_email": "football-sync-bot@...",
    ...
  }
  ```

---

## Fase 5 — Testar localmente (opcional mas recomendado)

Antes de deixar correr no GitHub Actions, é útil testar na tua máquina.

```bash
# Instalar dependências
pip install -r requirements.txt

# Definir variáveis de ambiente temporariamente
export FOOTBALL_DATA_TOKEN="o_teu_token_aqui"
export GOOGLE_CREDENTIALS='{ "type": "service_account", ... }' # JSON completo

# Correr o script
python sync.py
```

Se tudo correr bem, deves ver no terminal algo como:
```
2026-07-13 10:00:01 [INFO] === Football Calendar Sync iniciado ===
2026-07-13 10:00:01 [INFO] A autenticar na Google Calendar API...
2026-07-13 10:00:02 [INFO] A ir buscar jogos à football-data.org...
2026-07-13 10:00:02 [INFO] Pedidos disponíveis neste minuto (football-data.org): 9
2026-07-13 10:00:02 [INFO] Jogos encontrados para a equipa 498: 3
2026-07-13 10:00:03 [INFO] Total de jogos obtidos: 3
2026-07-13 10:00:04 [INFO] ✅ CRIADO  [22/03/2026 21:15] ⚽ Sporting CP vs SL Benfica — evt_abc123
...
2026-07-13 10:00:06 [INFO] Sincronização concluída — ✅ criados: 3 | 🔄 atualizados: 0 | 🗑️  removidos: 0 | ⏭️  ignorados: 0
```

E no teu Google Calendar aparecerão os eventos com cores diferentes por competição.

### Testar já com jogos reais (antes da Primeira Liga começar)

Como a Primeira Liga só começa em agosto, para testar já com jogos que estão mesmo a
acontecer (ex: Mundial 2026), muda temporariamente no `sync.py`:
```python
TEAM_ID = 760                          # Seleção Espanhola (tem jogos agora)
COMPETITIONS = {2000: "FIFA World Cup 🌍"}
COMPETITION_COLORS = {2000: "11"}
```
Corre `python sync.py`, confirma que os eventos aparecem no calendário, e depois reverte
para `TEAM_ID = 498` e as competições da Primeira Liga/Champions League.

### Correr os testes automatizados

```bash
pip install -r requirements-dev.txt
python -m pytest test_sync.py -v
```

Estes testes usam mocks — não tocam na API real nem no teu Google Calendar.

---

## Fase 6 — Ativar o cron no GitHub Actions

1. Vai ao repositório no GitHub
2. Clica no separador **Actions**
3. Se aparecer a mensagem "Workflows aren't being run on this forked repository", clica em **I understand my workflows, go ahead and enable them**
4. Clica em **Football Calendar Sync** no menu lateral
5. Clica em **Run workflow** → **Run workflow** para testar manualmente a primeira vez

A partir daí, corre automaticamente às **9h (Lisboa)**, todos os dias.

---

## Personalização

### Seguir outro clube

No `sync.py`, altera:
```python
TEAM_ID = 498  # Sporting CP
```
Para o ID da equipa que quiseres (consulta `/v4/competitions/{code}/teams` para encontrar o ID).

### Adicionar ou remover competições

No `sync.py`, edita o dicionário `COMPETITIONS` (usa os **IDs numéricos**, não os códigos —
consulta `/v4/competitions/{code}` para encontrar o `id` de uma competição):
```python
COMPETITIONS = {
    2017: "Primeira Liga 🇵🇹",
    2001: "Champions League 🏆",
    2146: "Liga Europa 🌍",    # Adicionar (verifica o ID exato na API)
}
```
E a cor correspondente em `COMPETITION_COLORS`:
```python
COMPETITION_COLORS = {
    2017: "10",
    2001: "3",
    2146: "7",    # Adicionar — cor pavão
}
```

### Usar um calendário separado para futebol (recomendado)

1. No Google Calendar, cria um novo calendário chamado "⚽ Sporting"
2. Partilha-o com a Service Account (como na Fase 2.4)
3. Nas definições do calendário, copia o **Calendar ID** (parece um email longo)
4. No `sync.py`, substitui:
   ```python
   CALENDAR_ID = "o_teu_email@gmail.com"
   ```
   Por:
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

No `.github/workflows/sync.yml`:
```yaml
- cron: '0 8 * * *'    # 8h UTC = 9h Lisboa

# Para voltar a correr 2x por dia, adiciona outra linha, ex:
# - cron: '0 18 * * *'   # 18h UTC = 19h Lisboa
```
Sintaxe cron: `minuto hora dia-mês mês dia-semana`

---

## Como funciona o estado (fixtures_state.json)

O ficheiro `fixtures_state.json` é o "cérebro" do sistema. Guarda a correspondência entre o ID do jogo na API e o ID do evento no Google Calendar:

```json
{
  "497583": {
    "date": "2026-03-22T21:15:00Z",
    "event_id": "abc123def456ghi789",
    "home": "Sporting CP",
    "away": "SL Benfica",
    "competition": 2017
  },
  "497601": {
    "date": "2026-03-26T19:00:00Z",
    "event_id": "xyz987uvw654rst321",
    "home": "FC Porto",
    "away": "Sporting CP",
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

O estado é guardado mesmo que a sincronização falhe a meio (ex: erro de rede num jogo específico),
para não perder o registo de eventos já criados e evitar duplicados na execução seguinte.

---

## Troubleshooting

### "FOOTBALL_DATA_TOKEN não definida"
Confirma que o Secret `FOOTBALL_DATA_TOKEN` está criado no GitHub (ou a variável de ambiente, se testares localmente).

### "GOOGLE_CREDENTIALS não definida"
Confirma que o Secret `GOOGLE_CREDENTIALS` está criado no GitHub e contém o JSON completo.

### Eventos não aparecem no calendário
1. **`CALENDAR_ID = "primary"` é o erro mais comum aqui** — isso é o calendário
   da Service Account, não o teu. Confirma que `CALENDAR_ID` está definido
   como o teu email do Google (ou o Calendar ID de um calendário dedicado).
   O script não dá erro nenhum neste caso (o evento é criado na mesma, só que
   num calendário que não vês), por isso é fácil passar despercebido.
2. Confirma que o calendário foi partilhado com o email da Service Account
3. Confirma que as permissões são "Fazer alterações a eventos" (não só "Ver eventos")
4. Confirma que `TEAM_ID` e os IDs em `COMPETITIONS` estão corretos — testa diretamente:
   `curl -H "X-Auth-Token: ..." "https://api.football-data.org/v4/teams/498/matches?competitionIds=2017,2001"`

### "403 Forbidden" da Google Calendar API
A Service Account não tem permissão para escrever no calendário.
Volta à Fase 2.4 e confirma a partilha com as permissões corretas.

### "429 Too Many Requests" da football-data.org
O `sync.py` já trata isto automaticamente: lê o `Retry-After` devolvido pela API, espera esse
tempo e tenta uma vez mais. Se mesmo assim continuar a falhar, é porque estás a correr o script
demasiadas vezes seguidas (ex: em loop de testes) — espera um minuto e tenta de novo.

### O workflow não corre automaticamente
- GitHub pode atrasar crons em repositórios com pouca atividade
- Faz um commit qualquer para "acordar" o repositório
- Podes sempre correr manualmente em Actions → Run workflow

---

## Segurança

- **Nunca commites** o ficheiro JSON da Service Account
- Usa sempre **GitHub Secrets** para credenciais
- Mantém o repositório como **privado**
- O `.gitignore` já está configurado para proteger ficheiros de credenciais
- A Service Account só tem acesso ao calendário que tu partilhaste — não tem acesso a mais nada da tua conta Google

---

## Custo total: 0€

| Serviço | Plano | Limite gratuito | Uso estimado |
|---|---|---|---|
| football-data.org | Free | 10 pedidos/minuto | ~1 pedido/dia |
| Google Calendar API | Free | Sem limite prático para uso pessoal | ~5 operações/dia |
| GitHub Actions | Free | 2.000 min/mês | ~2 min/dia = ~60 min/mês |

---

*Atualizado em Julho 2026 — football-data.org API v4 · Google Calendar API v3 · Python 3.12 · GitHub Actions*
