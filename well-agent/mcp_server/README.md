# MCP-сервер OLGA

Сервер запускает подготовленный сценарий обхода МБСНУ в OLGA и отдаёт клиенту структурированные
статусы и результаты. Подробности, контракт и настройка — в [`docs/olga_adapter.md`](../docs/olga_adapter.md).

```text
server.py          инструменты MCP (тонкая обёртка)
service.py         логика: валидация, план, подтверждение, запуск, статусы, результаты
settings.py        настройки из OLGA_* / OLGA_SERVER_CONFIG
case_kit.py        манифест, хеши комплекта, обратное чтение расписания из .genkey
registry.py        устойчивое хранение планов и запусков (runs/)
launcher.py        запуск процесса (shell=False), проверка окончания и классификация ошибок
results_bridge.py  вызов модуля анализа участника 3
approval.py        HMAC-токен подтверждения (stdlib, можно импортировать в клиенте)
journal.py         серверный журнал JSONL
cases/             манифесты разрешённых сценариев
testing/fake_olga.py  ТЕСТОВЫЙ заменитель OLGA, только для режима fake
```

Запуск вручную обычно не нужен: stdio-клиент сам стартует `python -m mcp_server.server`.
stdout сервера занят протоколом MCP; служебные сообщения — в stderr, события — в `logs/server.jsonl`.

Проверка без LLM: `python -m scripts.smoke_client` (см. docstring скрипта).
