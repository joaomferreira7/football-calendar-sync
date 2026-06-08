# Football Calendar Sync — Plano Completo de Implementação

## O que este projeto faz

Sincroniza automaticamente os jogos de futebol que te interessam com o teu Google Calendar.
Sempre que um jogo é agendado (normalmente 10–15 dias antes), é criado um evento no calendário.
Se o horário mudar, o evento é atualizado. Se o jogo for cancelado, o evento é removido.

**Ligas suportadas:**
- Primeira Liga Portuguesa
- Segunda Liga Portuguesa
- Champions League
- (opcional) filtro por equipa específica

---

## Stack tecnológico — tudo gratuito

| Componente | Tecnologia | Custo |
|---|---|---|
| Dados de futebol | API-Football (api-sports.io) | Gratuito — 100 req/dia |
| Calendário | Google Calendar API v3 | Gratuito |
| Autenticação Google | Service Account (OAuth2) | Gratuito |
| Linguagem | Python 3.12 | Gratuito |
| Scheduler | GitHub Actions (cron) | Gratuito |
| Persistência de estado | `fixtures_state.json` no repositório | Gratuito |

**Consumo de requests:** 2 execuções/dia × 3 ligas = 6 requests/dia (dos 100 disponíveis).

---

## Estrutura do repositório

```
football-calendar-sync/
├── .github/
│   └── workflows/
│       └── sync.yml          ← cron job automático (2× por dia)
├── sync.py                   ← script principal de sincronização
├── fixtures_state.json       ← estado persistido (commitado no repo)
├── requirements.txt          ← dependências Python
├── .gitignore                ← protege credenciais de serem commitadas
└── PLANO.md                  ← este ficheiro
```

---

## Fase 1 — Criar conta na API-Football

**Tempo estimado: 5 minutos**

1. Vai a [api-sports.io](https://api-sports.io) e clica em **Register**
2. Cria conta gratuita (não precisa de cartão de crédito)
3. No dashboard, vai a **API-Football** e copia a tua **API Key**
4. Testa no browser para confirmar que funciona:
   ```
   https://v3.football.api-sports.io/leagues?id=94
   ```
   (deves ver a Primeira Liga Portuguesa)

**IDs úteis das ligas:**
| Liga | ID |
|---|---|
| Primeira Liga Portuguesa | 94 |
| Segunda Liga Portuguesa | 95 |
| Champions League | 2 |
| Liga Europa | 3 |
| Liga Conferência | 848 |

**IDs de equipas portuguesas:**
| Equipa | ID |
|---|---|
| FC Porto | 212 |
| SL Benfica | 228 |
| Sporting CP | 229 |
| SC Braga | 217 |
| Vitória SC | 230 |

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

> 💡 O `CALENDAR_ID = "primary"` no `sync.py` refere-se ao calendário principal.
> Se quiseres usar um calendário separado (recomendado para manter organizado),
> cria um novo calendário chamado "Futebol", partilha-o com a service account,
> e substitui `"primary"` pelo ID do calendário (visível nas definições do calendário).

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
   # Copia sync.py, requirements.txt, .gitignore, fixtures_state.json
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

### Secret 1: `API_FOOTBALL_KEY`
- **Name:** `API_FOOTBALL_KEY`
- **Value:** a tua API key da api-sports.io (ex: `abc123def456...`)

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
export API_FOOTBALL_KEY="a_tua_chave_aqui"
export GOOGLE_CREDENTIALS='{ "type": "service_account", ... }' # JSON completo

# Correr o script
python sync.py
```

Se tudo correr bem, deves ver no terminal algo como:
```
2025-03-15 10:00:01 [INFO] === Football Calendar Sync iniciado ===
2025-03-15 10:00:01 [INFO] A autenticar na Google Calendar API...
2025-03-15 10:00:02 [INFO] Liga 94 (Primeira Liga 🇵🇹): 8 jogos encontrados
2025-03-15 10:00:03 [INFO] Liga 95 (Segunda Liga 🇵🇹): 6 jogos encontrados
2025-03-15 10:00:04 [INFO] Liga 2 (Champions League 🏆): 4 jogos encontrados
2025-03-15 10:00:05 [INFO] ✅ CRIADO  [22/03/2025 21:15] ⚽ FC Porto vs Benfica — evt_abc123
...
2025-03-15 10:00:10 [INFO] Sincronização concluída — ✅ criados: 18 | 🔄 atualizados: 0 | 🗑️  removidos: 0 | ⏭️  ignorados: 0
```

E no teu Google Calendar aparecerão os eventos com cores diferentes por competição.

---

## Fase 6 — Ativar o cron no GitHub Actions

1. Vai ao repositório no GitHub
2. Clica no separador **Actions**
3. Se aparecer a mensagem "Workflows aren't being run on this forked repository", clica em **I understand my workflows, go ahead and enable them**
4. Clica em **Football Calendar Sync** no menu lateral
5. Clica em **Run workflow** → **Run workflow** para testar manualmente a primeira vez

A partir daí, corre automaticamente às **9h e às 19h (Lisboa)** todos os dias.

---

## Personalização

### Seguir só uma equipa específica

No `sync.py`, altera a linha:
```python
TEAM_ID = None
```
Para, por exemplo, FC Porto:
```python
TEAM_ID = 212
```
Isto filtra os resultados para jogos em que o Porto participa (em todas as ligas configuradas).

### Adicionar ou remover ligas

No `sync.py`, edita o dicionário `LEAGUES`:
```python
LEAGUES = {
    94: "Primeira Liga 🇵🇹",
    95: "Segunda Liga 🇵🇹",
    2:  "Champions League 🏆",
    3:  "Liga Europa 🌍",    # Adicionar
}
```
E a cor correspondente em `LEAGUE_COLORS`:
```python
LEAGUE_COLORS = {
    94: "10",
    95: "6",
    2:  "3",
    3:  "7",    # Adicionar — cor pavão
}
```

### Usar um calendário separado para futebol (recomendado)

1. No Google Calendar, cria um novo calendário chamado "⚽ Futebol"
2. Partilha-o com a Service Account (como na Fase 2.4)
3. Nas definições do calendário, copia o **Calendar ID** (parece um email longo)
4. No `sync.py`, substitui:
   ```python
   CALENDAR_ID = "primary"
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

No `sync.yml`:
```yaml
- cron: '0 8 * * *'    # 8h UTC = 9h Lisboa
- cron: '0 18 * * *'   # 18h UTC = 19h Lisboa
```
Sintaxe cron: `minuto hora dia-mês mês dia-semana`

---

## Como funciona o estado (fixtures_state.json)

O ficheiro `fixtures_state.json` é o "cérebro" do sistema. Guarda a correspondência entre o ID do jogo na API e o ID do evento no Google Calendar:

```json
{
  "1035847": {
    "date": "2025-03-22T21:15:00+00:00",
    "event_id": "abc123def456ghi789",
    "home": "FC Porto",
    "away": "SL Benfica",
    "league": 94
  },
  "1035901": {
    "date": "2025-03-26T19:00:00+00:00",
    "event_id": "xyz987uvw654rst321",
    "home": "Sporting CP",
    "away": "SC Braga",
    "league": 94
  }
}
```

A cada execução:
1. Vai buscar os jogos à API
2. Compara `fixture_id` com os que estão no state
3. **Novo ID** → cria evento + adiciona ao state
4. **ID existente mas data diferente** → atualiza evento + atualiza state
5. **ID no state mas não na API** → remove evento + apaga do state
6. Faz commit do state atualizado de volta ao repositório

---

## Troubleshooting

### "GOOGLE_CREDENTIALS não definida"
Confirma que o Secret `GOOGLE_CREDENTIALS` está criado no GitHub e contém o JSON completo.

### "API_FOOTBALL_KEY não definida"
Confirma que o Secret `API_FOOTBALL_KEY` está criado no GitHub.

### Eventos não aparecem no calendário
1. Confirma que o calendário foi partilhado com o email da Service Account
2. Confirma que as permissões são "Fazer alterações a eventos" (não só "Ver eventos")
3. Se usas `CALENDAR_ID` personalizado, confirma que o ID está correto

### "403 Forbidden" da Google Calendar API
A Service Account não tem permissão para escrever no calendário.
Volta à Fase 2.4 e confirma a partilha com as permissões corretas.

### "429 Too Many Requests" da API-Football
Atingiste o limite de 100 requests/dia. Verifica se o cron não está a correr mais vezes do que o esperado ou se tens muitas ligas configuradas.

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
| api-sports.io | Free | 100 req/dia | ~6 req/dia |
| Google Calendar API | Free | Sem limite prático para uso pessoal | ~20 operações/dia |
| GitHub Actions | Free | 2.000 min/mês | ~2 min/dia = ~60 min/mês |

---

*Gerado em Junho 2026 — API-Football v3 · Google Calendar API v3 · Python 3.12 · GitHub Actions*
