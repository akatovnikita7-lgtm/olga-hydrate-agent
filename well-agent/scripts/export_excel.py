"""Make results.xlsx from an existing analysis directory."""
import argparse
from pathlib import Path

from src.results.excel import export_excel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, nargs='?')
    directory = parser.parse_args().directory
    if directory is None:
        runs = Path(__file__).resolve().parents[1] / 'runs'
        exports = list(runs.glob('*/model/analysis/series.csv'))
        if not exports:
            parser.error('No completed run found in runs. Pass the analysis directory explicitly.')
        directory = max(exports, key=lambda path: path.stat().st_mtime).parent
    path = export_excel(directory)
    print(path.resolve())


if __name__ == '__main__':
    main()
