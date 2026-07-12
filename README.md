# football-calendar-sync

Sincroniza os jogos do Sporting CP (Primeira Liga, Champions League) com o Google Calendar.
Ver [PLANO.md](PLANO.md) para o guia completo de configuração.

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest test_sync.py -v
```

Os testes cobrem a lógica de sincronização (`sync()`) com mocks — não chamam nenhuma API real.
