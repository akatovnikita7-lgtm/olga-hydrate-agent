# Черновик контракта MCP для сценария обхода МБСНУ

Рабочая команда `python -m mcp_server.server` открывает stdio и объявляет
`get_simulator_status()` и `run_simulation(case_id, parameters)`. Статус описывает
конфигурацию адаптера. Вызов `run_simulation` передаётся в `SimulatorClient.run_case`,
который пока возвращает ошибку конфигурации. Сценарные инструменты из таблицы нужно
сверить с тем, что объявит рабочий сервер через `list_tools`. На этапе 1
`read_case_manifest` проверяется на отдельном тестовом сервере.

## Предлагаемые инструменты

Все ответы в таблице передаются как объекты `structuredContent`. Имена ключей в
ответах предлагаются для согласования.

| Инструмент | Аргументы | Поля ответа |
| --- | --- | --- |
| `read_case_manifest` | `case_id: str`, `trace_id: str` | `schema_version`, `case_id`, `model_id`, `model_version`, `model_fingerprint`, `schedule` (с `event_time_s`, `transition_s`, `end_time_s`), `allowed_parameters`, `control_points` |
| `prepare_scenario` | `case_id: str`, `event_time_s: number`, `transition_s: number`, `end_time_s: number`, `trace_id: str` | `plan_id`, `case_id`, `model_version`, `model_fingerprint`, `parameters` (нормализованное расписание), `actions`, `model_copy`, `requires_approval` |
| `start_run` | `plan_id: str`, `approval_token: str`, `trace_id: str` | `run_id`, `status` |
| `get_run_status` | `run_id: str`, `trace_id: str` | `run_id`, `status` (`QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED` или `CANCELLED`), `error` при наличии |
| `read_run_results` | `run_id: str`, `trace_id: str` | `case_id`, `run_id`, `metrics` (значения, единицы, условия измерения и источник), `pressure_scale`, `time_basis`, `assessment`, `plots` (пути к графикам расхода и давления) |

Предлагаемый `case_id` — `mbsnu_bypass_96h`. Расписание тестового манифеста:
`event_time_s = 172800`, `transition_s = 60`, `end_time_s = 345600`. Идентификатор
сценария, допустимые изменения и контрольные точки рабочего запуска определяет
манифест команды.

Для ошибки инструмента предлагаем `isError: true` и объект `structuredContent`
с обязательными `code` и `message`. Уточняющие поля `field`, `received_value`,
`expected_rule` и `retryable` передаются при наличии. Ошибка самого протокола
передаётся через JSON-RPC.

## Согласование с участником 2

- Подтвердить имена инструментов, версию схемы, типы полей, единицы времени,
  идентификатор сценария, форму расписания, правила изменения параметров и
  контрольные точки. Согласовать `trace_id` и передачу `call_id` в аргументах
  или в метаданных MCP.
- Согласовать серверную проверку подтверждения. После явного согласия человека
  клиент должен передавать `approval_token` в `start_run`. Серверу нужно
  проверять привязку токена к `plan_id`, версии и fingerprint модели и вернуть
  тот же `run_id` при повторе подтверждённого запуска. Открыты способ выпуска
  и проверки токена, срок действия, область действия плана и поведение при
  потере ответа о запуске.
- Согласовать переходы состояний запуска, форму ошибок и доступ к артефактам
  после `SUCCEEDED`, включая размещение и срок доступности графиков.

## Согласование с участником 3

- Утвердить поля метрик и контрольные точки, условия измерения расхода,
  шкалу давления, базу отсчёта времени, единицы и причины отсутствия данных.
- Утвердить форму оценки `OK`, `OUT_OF_TOLERANCE` или `NOT_ASSESSED` и способ
  ссылки на графики и исходные данные.
