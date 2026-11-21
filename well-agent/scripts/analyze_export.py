"""Analyze an existing TPL without launching OLGA or calling an LLM."""
import argparse
import json
import shutil
from pathlib import Path
from src.results import analyze_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tpl', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.tpl.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((Path(__file__).resolve().parents[1] / 'mcp_server/cases/mbsnu_bypass_96h.json').read_text(encoding='utf-8'))
    destination = args.output / manifest['expected_outputs']['trend']
    if destination.resolve() != source:
        if destination.exists():
            parser.error('Выберите новую папку --output: файл результата уже существует.')
        shutil.copy2(source, destination)
    result = analyze_run(args.output, manifest, {'mode': 'existing_export', 'source': str(source)})
    print('Анализ сохранённого результата. Новый расчёт НЕ выполнялся.')
    for artifact in result['artifacts']:
        print(artifact['kind'], artifact['path'])
    print(json.dumps(result['assessment'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
