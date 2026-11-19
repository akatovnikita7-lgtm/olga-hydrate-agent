# MCP-сервер OLGA (участник 2): настройка, контракт, ограничения

Ветка: `feat/olga-adapter`. Владелец: участник 2. Каталог: `well-agent/mcp_server/`.

## 1. Статус проверки

| Что | real (OLGA) | fake (тестовый адаптер) |
|---|---|---|
| Инструменты MCP по stdio, список, схемы | не проверено | проверено (`tests/server/test_mcp_stdio.py`) |
| Отказ до запуска: отрицательное время, неизвестный case_id, чужое время | не проверено | проверено |
| Подтверждение: нет/чужой токен → `APPROVAL_REQUIRED` | не проверено | проверено |
| Изменённая модель → `FINGERPRINT_MISMATCH` | не проверено | проверено |
| Копия в `runs/<run_id>/model`, оригинал не меняется | не проверено | проверено |
| Повтор `start_run` → тот же `run_id` | не проверено | проверено |
| Окончание: код возврата + `NORMAL STOP` + тренд до ENDTIME | не проверено | проверено |
| Реальный расчёт OLGA через MCP | **интеграция не проверена** | — |
| Признаки `LICENSE_BUSY`, `NO_SOLUTION` | **шаблоны не заданы** (нужны реальные сообщения OLGA) | проверено на тестовых текстах |

Разбор расписания проверен на реальном `case1_obhod.genkey` (вне репозитория):
VALVE-2 `(0,0,1)`, VALVE Separator `(1,1,0)`, Pump `9.989051 → 0 kg/s`, время `(0, 172800, 172860) s`, ENDTIME `345600 s`.

## 2. Инструменты (контракт v1)

Каждый ответ — JSON-конверт: `ok`, `schema_version`, `adapter_mode` (`real`/`fake`), `adapter_version`, `trace_id`, данные или `error`.
Клиент обязан проверять `ok`. Ошибка: `code, message, field, received_value, expected_rule, retryable`.

| Инструмент | Что делает | Запускает OLGA? |
|---|---|---|
| `get_server_status(trace_id)` | конфигурация и её проблемы (без путей и секретов) | нет |
| `read_case_manifest(case_id, trace_id)` | манифест, отпечаток комплекта, расписание, прочитанное из модели | нет |
| `prepare_scenario(case_id, event_time_s, transition_s, end_time_s, trace_id)` | проверка входов, план, `plan_id`, `requires_approval=true` | нет |
| `start_run(plan_id, approval_token, trace_id)` | копия комплекта, обратное чтение расписания, запуск launcher | да |
| `get_run_status(run_id, trace_id)` | `QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED`, коды, проверка файлов; процента нет | нет |
| `read_run_results(run_id, trace_id)` | артефакты этого `run_id`, метрики от модуля участника 3, три статуса | нет |

Все инструменты принимают необязательный `call_id` клиента; он попадает в журнал.

Три разных статуса в `read_run_results.statuses`: `execution` (процесс), `results_read` (файлы прочитаны),
`engineering_assessment` (`OK` / `OUT_OF_TOLERANCE` / `NOT_ASSESSED`). Пока нет `src/results`, оценка — `NOT_ASSESSED` с причиной, `metrics=[]`.

Коды ошибок: `INVALID_INPUT`, `UNIT_AMBIGUOUS`, `UNSUPPORTED_SCENARIO_PARAMETER`, `APPROVAL_REQUIRED`,
`PLAN_NOT_FOUND`, `PLAN_EXPIRED`, `FINGERPRINT_MISMATCH`, `MODEL_SCHEDULE_MISMATCH`, `CASE_KIT_INVALID`,
`SIMULATOR_UNAVAILABLE`, `RUN_LIMIT_REACHED`, `LICENSE_BUSY`, `TIMEOUT`, `NO_SOLUTION`, `SIMULATION_FAILED`,
`INCOMPLETE_RESULT`, `RESULT_PARSE_ERROR`, `RUN_NOT_FOUND`, `RUN_NOT_FINISHED`, `INTERNAL_ERROR`.

## 3. Подтверждение (для участника 1)

```python
from mcp_server.approval import make_approval_token   # только stdlib
token = make_approval_token(os.environ["OLGA_APPROVAL_SECRET"], plan["plan_id"], plan["model_fingerprint"], trace_id)
```

* `trace_id` — тот же, что передан в `prepare_scenario`.
* Токен вычисляет доверенный код CLI **после** явного «да» человека. Секрет не передаётся LLM и не печатается.
* Изменение модели или новый план → нужен новый токен.

## 4. Настройка на компьютере с OLGA (Windows)

Комплект модели хранится **вне** репозитория, например `C:\OLGA_data\MBSNU\` (`case1_obhod.genkey`, `Novosam_T1_HeaderFix.tab`, по желанию `case1_obhod.opi`).

```powershell
cd well-agent
$env:OLGA_ADAPTER_MODE   = "real"
$env:OLGA_CASE_KIT_DIR   = "C:\OLGA_data\MBSNU"
$env:OLGA_LAUNCHER       = "<ПРОВЕРЕННЫЙ путь к исполняемому файлу OLGA>"
$env:OLGA_LAUNCHER_ARGS  = '["{input}"]'          # ПРОВЕРИТЬ по вашей установке
$env:OLGA_APPROVAL_SECRET = "<длинная случайная строка, не коммитить>"
$env:OLGA_RUN_TIMEOUT_S  = "3600"
.\.venv\Scripts\python.exe -m scripts.smoke_client --plan-only
.\.venv\Scripts\python.exe -m scripts.smoke_client
```

Можно вместо переменных указать JSON-файл: `$env:OLGA_SERVER_CONFIG="C:\OLGA_data\olga_server.json"` (образец — `mcp_server/olga_server.example.json`). Сервер **не** читает `.env` сам.

Плейсхолдеры в `OLGA_LAUNCHER_ARGS`: `{input}` (имя .genkey), `{input_path}`, `{model_dir}`, `{run_dir}`. Другие отклоняются.
Рабочий каталог процесса — `runs/<run_id>/model`. `shell=False`.

### Блокер: команда пакетного запуска OLGA

Команда **не известна** и в коде не выдумана. Что сделать (стр. 12, шаги 2–4):

1. Найти в установке OLGA 2021.2 исполняемый файл расчётного ядра и способ пакетного запуска по документации установки или у преподавателя.
   Для справки: в `case1_obhod.out` GUI запускал ядро с аргументами `-nthreads -1 -tcp localhost 1971`; `-tcp` — канал связи с GUI, для пакетного запуска его, вероятно, не нужно. Это наблюдение, а не проверенная команда.
2. В **копии** комплекта выполнить команду вручную из `cmd`/PowerShell. Записать: exe, аргументы, рабочий каталог, время, код возврата (`$LASTEXITCODE`), какие файлы появились.
3. Убедиться, что `.out` содержит `NORMAL STOP IN EXECUTION`, а последняя строка `.tpl` ≈ 345600 с. Сравнить с ручным GUI-прогоном (длительность у автора ~833 с).
4. Если launcher завершается раньше решателя — `OLGA_LAUNCHER_DETACHES=true` (тогда состояние определяется по файлам).
5. Вызвать ошибку лицензии (например, без доступа к серверу лицензий) и вписать **точный** текст сообщения в `OLGA_LICENSE_ERROR_PATTERNS` (JSON-список regex). То же для отсутствия решения — `OLGA_NO_SOLUTION_PATTERNS`. Пока шаблонов нет, такие ошибки идут как `SIMULATION_FAILED`.

## 5. Как определяется успех

`SUCCEEDED` только если: код возврата 0 (если известен; `OLGA_REQUIRE_ZERO_EXIT_CODE`), в `.out` есть `NORMAL STOP IN EXECUTION`,
тренд доходит до `ENDTIME` (допуск 20 с), файлы созданы после старта этого запуска. Старые файлы другого запуска не принимаются: каждый запуск в своём каталоге.

## 6. Известные ограничения

* **Windows + stdio:** SDK MCP помещает процесс сервера в Job Object с `KILL_ON_JOB_CLOSE`. При закрытии клиента будет завершён и дочерний процесс OLGA. Для видео клиент должен оставаться открытым до конечного состояния. Запись `run.json` сохранится, и `get_run_status` после перезапуска сообщит `FAILED` с хвостом журнала. На macOS/Linux расчёт запускается в отдельной сессии и переживает клиент.
* **Окружение stdio-сервера:** SDK MCP передаёт серверу только короткий список системных переменных
  (на Windows — `PATH`, `SYSTEMROOT`, `TEMP`, `APPDATA` и ещё несколько). Переменные лицензии OLGA и, например,
  `COMPUTERNAME`/`PROGRAMDATA` иначе не дойдут до OLGA. `scripts/smoke_client.py` передаёт явно: `OLGA_*`,
  переменные с `LICENSE` в имени, системные пути и имена из `OLGA_PASSTHROUGH_ENV`. Клиент участника 1 должен
  делать так же (функцию `server_env()` можно взять из скрипта). Если ручной запуск работает, а через MCP — ошибка
  лицензии, первым делом сравните `set` в консоли и окружение сервера.
* Отмена расчёта не реализована: при `timeout_exceeded` сервер возвращает `pid` и инструкцию; процессы OLGA массово не завершаются.
* После перезапуска сервера код возврата неизвестен: решение принимается по файлам (`exit_code_note`).
* Лимит параллельности — `OLGA_MAX_CONCURRENT_RUNS` (по умолчанию 1).

## 7. Журнал

`logs/server.jsonl` (или `OLGA_LOG_DIR`): `tool_call_received`, `validation_passed`, `plan_created`, `approval_rejected/accepted`,
`kit_copied`, `schedule_verified_in_copy`, `process_started`, `process_exited`, `run_finalized`, `results_read`, `timeout_exceeded`, `tool_call_completed` (с `duration_ms`).
Каждое событие содержит `trace_id`; после появления — `plan_id`, `run_id`. Токен маскируется (`***`). Локальные пути заменяются на `<run_dir>`/`<path>`.

## 8. Подключение модуля участника 3

Функция по умолчанию: `src.results:analyze_run(model_dir: Path, manifest: dict, run_info: dict) -> dict`
с ключами `metrics`, `series`, `assessment`, `artifacts`. Изменить: `OLGA_RESULTS_ANALYZER="модуль:функция"`.
Контрольные точки и единицы — в `mcp_server/cases/mbsnu_bypass_96h.json` (`checkpoints`).

## 9. Тесты

```powershell
.\.venv\Scripts\python.exe -m pytest tests/server -q
```

Все серверные тесты используют синтетический мини-комплект и `mcp_server/testing/fake_olga.py`, явно помеченный как FAKE.
В режиме `real` сервер отказывается работать с fake_olga, в режиме `fake` — с любым другим launcher.

## 10. Наблюдения по комплекту модели (для участников 3 и 5)

* В трендах нет положения клапанов (VALVOP); состояние клапанов видно только по расписанию и расходам.
* `DTPLOT=10 с`: в окно перехода 60 с попадает ~6–7 точек. Для графика перехода этого мало; уточнить с автором модели.
* Профили (`.ppl`) сохранены только на 0 с и в конце.
* Подача Pump видна как `GT` ветви `PUMP TUBE - COPY` со знаком минус.
* По трендам прогона автора: сразу после переключения (≈172900 с) расход в ветви `AGZU 6 - AGZU 4` кратковременно отрицательный (≈ −0,36 кг/с); к 180000 с поток через байпас ≈ 10,19 кг/с, на АГЗУ-2 ≈ 10,39 кг/с, к 96 ч оба ≈ 10,15 кг/с. Это вопрос к инженерной проверке, а не к серверу.
