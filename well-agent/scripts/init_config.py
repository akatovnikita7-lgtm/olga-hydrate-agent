"""Create local configuration once; preserve an existing file."""
import secrets
from pathlib import Path
root = Path(__file__).resolve().parents[1]
target = root / '.env'
if not target.exists():
    template = (root / '.env.example').read_text(encoding='utf-8')
    template = template.replace('OLGA_APPROVAL_SECRET=\n', 'OLGA_APPROVAL_SECRET=' + secrets.token_hex(32) + '\n')
    target.write_text(template, encoding='utf-8')
    print('Created .env. Fill in LLM_API_KEY and OLGA paths locally.')
else:
    print('Existing .env preserved.')
