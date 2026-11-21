"""Execute the reviewed plan using the OLGA adapter's actual protocol."""
import asyncio
import json
from time import monotonic

from mcp_server.approval import make_approval_token
from mcp_server.settings import Settings
from .tools import McpGatewayError


async def run_plan(session, request, journal, ask, show, poll_interval, timeout):
    async def call(name, **arguments):
        arguments['trace_id'] = journal.trace_id
        with journal.call('mcp', name, arguments) as response:
            payload = await session.call_tool(name, arguments, check_schema=True)
            response['result'] = payload
        if payload.get('trace_id') != journal.trace_id:
            raise McpGatewayError('TRACE_MISMATCH', 'Ответ относится к другому запросу.')
        return payload

    plan = await call('prepare_scenario', case_id=request.case_id, **request.schedule.model_dump())
    expected = request.schedule.model_dump()
    if (plan.get('case_id') != request.case_id or
        plan.get('model_fingerprint') != request.model_fingerprint or
        any(plan.get('normalized_parameters', {}).get(k) != v for k, v in expected.items())):
        raise McpGatewayError('PLAN_MISMATCH', 'План отличается от проверенного запроса.')
    journal.plan_id = plan['plan_id']
    show(f"Режим: {plan['adapter_mode'].upper()}. План {plan['plan_id']}")
    if plan['adapter_mode'] != 'real':
        show('СИНТЕТИЧЕСКИЙ ТЕСТ — физический расчёт OLGA не выполняется.')
    show(f"Переключение: {expected['event_time_s']/3600:g} ч, переход: {expected['transition_s']:g} с, конец: {expected['end_time_s']/3600:g} ч.")
    for action in plan['actions']:
        show(action)
    if not plan.get('ready_to_run'):
        raise McpGatewayError('NOT_CONFIGURED', '; '.join(plan['server_configuration_problems']))
    journal.write('needs_approval', plan=plan)
    try:
        approved = ask('Запустить этот план? [да/нет] ').strip().casefold() in {'да', 'yes'}
    except (EOFError, KeyboardInterrupt):
        approved = False
    journal.write('approval_decision', approved=approved)
    if not approved:
        return 'refused'
    secret = Settings.from_env().approval_secret
    if not secret:
        raise McpGatewayError('NOT_CONFIGURED', 'Не задан OLGA_APPROVAL_SECRET.')
    journal.secrets.add(secret)
    token = make_approval_token(secret, plan['plan_id'], plan['model_fingerprint'], journal.trace_id)
    journal.secrets.add(token)
    state = await call('start_run', plan_id=plan['plan_id'], approval_token=token)
    journal.run_id = state['run_id']
    started = monotonic()
    warned = False
    while True:
        if state.get('run_id') != journal.run_id:
            raise McpGatewayError('RUN_MISMATCH', 'Получен статус другого запуска.')
        status = state.get('state')
        show(f"{journal.run_id}: {status}; ожидание {monotonic()-started:.0f} с")
        journal.write('run_status', status=status, error=state.get('error'))
        if status == 'SUCCEEDED':
            break
        if status in {'FAILED', 'CANCELLED'}:
            show(json.dumps(state.get('error'), ensure_ascii=False))
            return status.lower()
        if status not in {'QUEUED', 'RUNNING'}:
            raise McpGatewayError('INVALID_STATE', str(status))
        if monotonic() - started > timeout and not warned:
            show('Расчёт длится дольше порога ожидания. Продолжаю опрос; окно нужно оставить открытым. Ctrl+C завершает клиент и может остановить дочерний расчёт.')
            journal.write('wait_threshold_exceeded')
            warned = True
        await asyncio.sleep(poll_interval)
        state = await call('get_run_status', run_id=journal.run_id)
    result = await call('read_run_results', run_id=journal.run_id)
    if result.get('run_id') != journal.run_id or result.get('run', {}).get('case_id') != request.case_id:
        raise McpGatewayError('RESULT_MISMATCH', 'Получены результаты другого запуска.')
    output = journal.path.with_suffix('.results.json')
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    show('Расчёт завершён. Результаты: ' + str(output.resolve()))
    show('Инженерная оценка: ' + json.dumps(result.get('assessment'), ensure_ascii=False))
    for artifact in result.get('artifacts', []):
        show(f"{artifact.get('kind')}: {artifact.get('path')}")
    journal.write('results_read', statuses=result.get('statuses'), artifacts=result.get('artifacts'))
    return 'ok'
