"""账号标识和批量导入解析，不依赖登录环境。"""
import csv
import hashlib
import io
import json
import re


def account_id(account: dict) -> str:
    identity = [str(account.get('tenant_name', '')).strip(),
                str(account.get('username') or account.get('user_id') or '').strip()]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()[:20]


def account_log_folder(account: dict) -> str:
    name = str(account.get('username') or account.get('user_id') or 'account')
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip('. ')[:64] or 'account'
    return f'{safe_name}_{account_id(account)}'


def valid_account(account: dict) -> bool:
    return bool(str(account.get('tenant_name', '')).strip() and
                (str(account.get('username', '')).strip() or
                 (account.get('user_id') and account.get('token'))))


def parse_accounts(text: str, school: str = '') -> tuple[list[dict], list[dict]]:
    """接受 Excel 粘贴的制表符、CSV 和空白分隔内容；错误信息不包含密码。"""
    rows, errors = [], []
    text = text.lstrip('\ufeff')
    school = school.strip()
    first_line = next((line for line in text.splitlines() if line.strip() and
                       not line.lstrip().startswith('#')), '')
    delimiter = next((char for char in ('\t', ',', '，', ';') if char in first_line), None)
    if delimiter:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    else:
        reader = (re.split(r'\s+', line.strip(), maxsplit=2) for line in text.splitlines())
    try:
        for line_number, cells in enumerate(reader, 1):
            if not cells or not any(cell.strip() for cell in cells) or cells[0].lstrip().startswith('#'):
                continue
            cells = [str(cell).strip() for cell in cells]
            user_headers = ('学号', '账号', '用户名', 'username')
            school_headers = ('学校', '学校名称', 'school', 'tenant_name')
            password_headers = ('密码', 'password')
            if ((len(cells) == 2 and cells[0].lower() in user_headers and cells[1].lower() in password_headers)
                    or (len(cells) == 3 and cells[0].lower() in school_headers and cells[1].lower() in user_headers)):
                continue
            if len(cells) == 3:
                tenant_name, username, password = cells
            elif len(cells) in (1, 2) and school:
                tenant_name, username = school, cells[0]
                password = cells[1] if len(cells) == 2 else ''
            else:
                errors.append({'line': line_number, 'message': '请填写默认学校，或使用“学校,学号,密码”三列格式。'})
                continue
            if not tenant_name or not username:
                errors.append({'line': line_number, 'message': '学校和学号不能为空。'})
                continue
            rows.append({'tenant_name': tenant_name, 'username': username,
                         'password': password or username})
    except csv.Error:
        errors.append({'line': getattr(reader, 'line_num', 0), 'message': 'CSV 引号或分隔符格式不正确。'})
    return rows, errors
