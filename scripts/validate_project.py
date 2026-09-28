"""Read-only, standard-library checks for the AIGC project harness.

Evidence checks prove only that referenced files exist and are nonempty; they do
not establish media authenticity, aesthetics, copyright, or human approval.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime
import json
import math
import ntpath
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit

CONTENT_DIRS = ('01_创作模板', '02_提示词库', '03_参考素材与风格',
                '04_作品项目', '05_工具与模型适配', '06_实验与复盘')
WORK_REQUIRED = ('project.json', '00_创作需求.md', '01_故事与角色设定.md',
                 '02_剧情脚本.md', '03_分镜表.csv', '04_生成提示词/本次发送.md',
                 '06_修改与验收.md')
ROOT_REQUIRED = ('README.md', 'AGENTS.md', 'spec/harness-engineering.md',
                 'spec/acceptance.md', 'spec/decisions.md',
                 *(f'{name}/README.md' for name in CONTENT_DIRS),
                 *(f'01_创作模板/{name}.md' for name in ('需求卡', '角色设定表', '分镜说明', '提示词交付模板')),
                 *(f'01_创作模板/作品模板/{name}' for name in (*WORK_REQUIRED, '05_生成结果/README.md')))
CSV_FIELDS = ('shot_id', 'duration_seconds', 'scene_id', 'character_ids',
              'description', 'dialogue', 'image_prompt', 'video_prompt', 'reference_files')
STATUSES = ('DRAFT', 'PROMPT_READY', 'GENERATED', 'ACCEPTED', 'ARCHIVED')
PLACEHOLDER = re.compile(r'\{\{.*?\}\}|待确认|\bTODO\b', re.IGNORECASE | re.DOTALL)
SHOT_ID = re.compile(r'EP\d{2,}_SH\d{3,}\Z')


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    work_count: int = 0

    def fail(self, code: str, location: object, message: str) -> None:
        self.errors.append(f'[{code}] {location}: {message}')


def _reparse(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))


def safe_path(base: Path, relative: object, result: Result, location: object) -> Path | None:
    """Reject traversal and links before reading any target outside base."""
    if not isinstance(relative, str) or not relative.strip():
        result.fail('PATH', location, '本地引用必须是非空相对路径')
        return None
    value = relative.replace('\\', '/')
    if ntpath.isabs(value) or ntpath.splitdrive(value)[0] or ':' in value or '\x00' in value:
        result.fail('PATH', location, f'不允许绝对路径或特殊路径: {relative}')
        return None
    parts = value.split('/')
    if '..' in parts:
        result.fail('PATH', location, f'不允许 .. 越界引用: {relative}')
        return None
    target = base
    try:
        for part in ('.', *parts):
            target = target / part
            if target.exists() or target.is_symlink():
                if _reparse(target):
                    result.fail('PATH', location, f'不允许符号链接或 Windows reparse point: {relative}')
                    return None
        return target
    except OSError as exc:
        result.fail('PATH', location, f'无法检查引用: {exc}')
        return None


def require_file(base: Path, relative: object, result: Result, location: object) -> Path | None:
    target = safe_path(base, relative, result, location)
    if target is None:
        return None
    try:
        if not target.is_file():
            result.fail('MISSING', location, f'缺少文件: {relative}')
            return None
        if target.stat().st_size == 0:
            result.fail('EMPTY', location, f'文件为空: {relative}')
            return None
    except OSError as exc:
        result.fail('READ', location, str(exc))
        return None
    return target


def read_text(path: Path, result: Result) -> str | None:
    try:
        return path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        result.fail('READ', path, f'无法按 UTF-8 读取: {exc}')
        return None


def validate_links(path: Path, root: Path, result: Result) -> None:
    """Check inline Markdown local links; skip fenced code, URLs and anchors."""
    content = read_text(path, result)
    if content is None:
        return
    lines = []
    fence = None
    for line in content.splitlines():
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None:
            lines.append(line)
    for match in re.finditer(r'\[[^\]\n]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+"[^"]*")?\s*\)', '\n'.join(lines)):
        value = match.group(1).strip('<>')
        if value.startswith('#'):
            continue
        if re.match(r'^(?:https?|mailto|data|app|codex)\:', value, re.IGNORECASE):
            continue
        if ntpath.isabs(value) or ntpath.splitdrive(value)[0]:
            result.fail('LINK_PATH', path, f'本地链接不能是绝对或驱动器相对路径: {value}')
            continue
        try:
            local = unquote(urlsplit(value).path)
        except ValueError:
            result.fail('LINK', path, f'无法解析链接: {value}')
            continue
        if not local:
            continue
        # Relative links may move up within the project; normalize lexically,
        # then use safe_path to inspect each component before target access.
        combined = path.parent.relative_to(root) / local
        if ntpath.isabs(local) or ntpath.splitdrive(local)[0] or ':' in local:
            result.fail('LINK_PATH', path, f'本地链接不能是绝对路径: {value}')
            continue
        normalized = []
        escaped = False
        for part in str(combined).replace('\\', '/').split('/'):
            if part == '..':
                if not normalized:
                    escaped = True
                    break
                normalized.pop()
            elif part not in ('', '.'):
                normalized.append(part)
        if escaped:
            result.fail('LINK_PATH', path, f'链接越出项目: {value}')
            continue
        target = safe_path(root, '/'.join(normalized) or '.', result, path)
        if target is not None and not target.exists():
            result.fail('LINK', path, f'本地链接目标不存在: {value}')


def _unique_json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f'重复 JSON key: {key}')
        value[key] = item
    return value


def validate_document_links(root: Path, result: Result) -> None:
    """Read all project Markdown, without following links or entering caches."""
    ignored = {'.git', '.harness-tests', '__pycache__', '.cache', '.pytest_cache',
               '.mypy_cache', '.ruff_cache', 'node_modules', 'cache', 'caches'}
    for path in root.iterdir():
        if path.suffix.lower() == '.md':
            checked = safe_path(root, path.name, result, path)
            if checked is not None and checked.is_file():
                validate_links(checked, root, result)
    for relative in ('spec', *CONTENT_DIRS):
        directory = safe_path(root, relative, result, root)
        if directory is None or not directory.is_dir():
            continue
        pending = [directory]
        while pending:
            for path in sorted(pending.pop().iterdir()):
                if path.name.lower() in ignored:
                    continue
                if _reparse(path):
                    result.fail('PATH', path, '不允许符号链接或 Windows reparse point；未跟随目标')
                elif path.is_dir():
                    pending.append(path)
                elif path.is_file() and path.suffix.lower() == '.md':
                    validate_links(path, root, result)


def read_manifest(directory: Path, result: Result) -> dict | None:
    path = require_file(directory, 'project.json', result, directory)
    if path is None:
        return None
    content = read_text(path, result)
    if content is None:
        return None
    try:
        manifest = json.loads(content, object_pairs_hook=_unique_json,
                              parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'非法数值: {value}')))
    except (ValueError, RecursionError) as exc:
        result.fail('JSON', path, str(exc))
        return None
    if not isinstance(manifest, dict):
        result.fail('SCHEMA', path, 'project.json 顶层必须是对象')
        return None
    return manifest


def validate_manifest(manifest: dict, directory: Path, result: Result) -> bool:
    start = len(result.errors)
    if type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1:
        result.fail('SCHEMA', directory, 'schema_version 必须是整数 1')
    checks = {'id': r'WORK-\d{3,}', 'revision': r'v\d{3,}'}
    for key in ('id', 'title', 'kind', 'scope', 'revision', 'status'):
        value = manifest.get(key)
        if not isinstance(value, str):
            result.fail('SCHEMA', directory, f'{key} 必须是字符串')
        elif key in checks and not re.fullmatch(checks[key], value):
            result.fail('SCHEMA', directory, f'{key} 格式错误: {value}')
    for key, allowed in (('kind', ('image', 'video', 'comic')), ('scope', ('prompts', 'media')), ('status', STATUSES)):
        if manifest.get(key) not in allowed:
            result.fail('SCHEMA', directory, f'{key} 必须属于 {allowed}')
    for key, extra in (('generation', ('tool', 'model', 'generated_at')), ('review', ('reviewer', 'reviewed_at'))):
        record = manifest.get(key)
        if not isinstance(record, dict):
            result.fail('SCHEMA', directory, f'{key} 必须是对象')
            continue
        if record.get('status') not in ('NOT_RUN', 'PASS', 'FAIL'):
            result.fail('SCHEMA', directory, f'{key}.status 无效')
        for name in ('revision', *extra):
            if not isinstance(record.get(name), str):
                result.fail('SCHEMA', directory, f'{key}.{name} 必须是字符串')
        evidence = record.get('evidence')
        if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
            result.fail('SCHEMA', directory, f'{key}.evidence 必须是路径字符串数组')
    return len(result.errors) == start


def validate_record(manifest: dict, key: str, directory: Path, result: Result) -> None:
    record = manifest[key]
    # References cannot be unsafe or nonexistent even before PASS.
    for relative in record['evidence']:
        require_file(directory, relative, result, f'{directory}/{key}.evidence')
    if record['status'] != 'PASS':
        return
    extra = ('tool', 'model', 'generated_at') if key == 'generation' else ('reviewer', 'reviewed_at')
    if any(not record[name].strip() or PLACEHOLDER.search(record[name]) for name in (*extra, 'revision')) or not record['evidence']:
        result.fail('PASS_FIELDS', directory, f'{key} PASS 必须提供完整真实信息与证据路径')
    if record['revision'] != manifest['revision']:
        result.fail('REVISION', directory, f'{key} 的 PASS 不属于当前 revision')
    date_key = 'generated_at' if key == 'generation' else 'reviewed_at'
    try:
        datetime.fromisoformat(record[date_key])
    except ValueError:
        result.fail('DATE', directory, f'{key}.{date_key} 必须是 ISO 日期时间')


def validate_shots(directory: Path, manifest: dict, gate: bool, result: Result) -> list[str]:
    path = require_file(directory, '03_分镜表.csv', result, directory)
    if path is None:
        return []
    content = read_text(path, result)
    if content is None:
        return []
    if gate and PLACEHOLDER.search(content):
        result.fail('PLACEHOLDER', path, '提示词就绪门禁不允许占位内容')
    try:
        reader = csv.DictReader(content.splitlines(), strict=True)
        if reader.fieldnames is None or any(key not in reader.fieldnames for key in CSV_FIELDS) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            result.fail('CSV_HEADER', path, f'需要唯一字段: {",".join(CSV_FIELDS)}')
            return []
        rows = list(reader)
    except csv.Error as exc:
        result.fail('CSV', path, str(exc))
        return []
    required = gate
    rows = [row for row in rows if any(value for value in row.values())]
    if required and not rows:
        result.fail('SHOTS', path, '至少需要一个完整镜头')
    ids = []
    for index, row in enumerate(rows, 2):
        location = f'{path}:{index}'
        if None in row or any(value is None for value in row.values()):
            result.fail('CSV_ROW', location, '行列数不匹配')
            continue
        row = {key: value.strip() for key, value in row.items()}
        must_fill = ['shot_id', 'scene_id', 'description', 'image_prompt', 'duration_seconds']
        if manifest['kind'] in ('video', 'comic'):
            must_fill.append('video_prompt')
        if required:
            for key in must_fill:
                if not row[key]:
                    result.fail('REQUIRED_VALUE', location, f'{key} 不能为空')
        shot = row['shot_id']
        if shot:
            if not SHOT_ID.fullmatch(shot):
                result.fail('SHOT_ID', location, f'无效镜头编号: {shot}')
            if shot in ids:
                result.fail('DUPLICATE_SHOT', location, f'重复镜头编号: {shot}')
            ids.append(shot)
        if row['duration_seconds']:
            try:
                duration = float(row['duration_seconds'])
                if not math.isfinite(duration) or duration < 0 or (manifest['kind'] != 'image' and duration == 0):
                    raise ValueError('时长范围错误')
            except ValueError:
                result.fail('DURATION', location, '图片时长须为有限非负数；视频/漫剧须为有限正数')
        for reference in row['reference_files'].split(';'):
            if reference.strip():
                require_file(directory, reference.strip(), result, location)
    return ids


def validate_work(directory: Path, manifest: dict, phase: str, result: Result) -> None:
    if not validate_manifest(manifest, directory, result):
        return
    gate = phase in ('prompts', 'delivery') or manifest['status'] in ('PROMPT_READY', 'GENERATED', 'ACCEPTED')
    delivery = phase == 'delivery' or manifest['status'] == 'ACCEPTED'
    if gate and (not manifest['title'].strip() or PLACEHOLDER.search(manifest['title'])):
        result.fail('PLACEHOLDER', directory, 'title 必须完整且不含占位内容')
    contents = {}
    for relative in WORK_REQUIRED:
        if relative in ('project.json', '03_分镜表.csv'):
            continue
        path = require_file(directory, relative, result, directory)
        if path is not None:
            content = read_text(path, result)
            if content is not None:
                contents[relative] = content
                if gate and relative != '06_修改与验收.md' and PLACEHOLDER.search(content):
                    result.fail('PLACEHOLDER', path, '提示词就绪门禁不允许占位内容')
    ids = validate_shots(directory, manifest, gate, result)
    if gate:
        sent = contents.get('04_生成提示词/本次发送.md', '')
        for shot in ids:
            if not re.search(r'(?<![A-Za-z0-9_])' + re.escape(shot) + r'(?![A-Za-z0-9_])', sent):
                result.fail('SEND_SHOT', directory, f'本次发送.md 缺少镜头: {shot}')
    for key in ('generation', 'review'):
        validate_record(manifest, key, directory, result)
    if manifest['status'] == 'GENERATED' and manifest['scope'] != 'media':
        result.fail('GENERATED_SCOPE', directory, 'GENERATED 仅适用于 scope=media')
    if (manifest['status'] == 'GENERATED' or (delivery and manifest['scope'] == 'media')) and manifest['generation']['status'] != 'PASS':
        result.fail('GENERATION_REQUIRED', directory, '此状态需要当前版本 generation PASS')
    if delivery and manifest['review']['status'] != 'PASS':
        result.fail('REVIEW_REQUIRED', directory, '交付需要当前版本 review PASS')


def validate_project(root: Path | str, work: str | None = None, phase: str = 'structure') -> Result:
    result = Result()
    root = Path(root).absolute()
    try:
        if phase not in ('structure', 'prompts', 'delivery'):
            result.fail('PHASE', root, '无效的验收阶段')
            return result
        if not root.exists() or _reparse(root) or not root.is_dir():
            result.fail('ROOT', root, '项目根目录不存在或属于符号链接/reparse point')
            return result
        for relative in ROOT_REQUIRED:
            require_file(root, relative, result, root)
        validate_document_links(root, result)
        selected = None
        if work is not None:
            selected = safe_path(root, work, result, '--work')
            if selected is None:
                return result
            if selected.parent != root / '04_作品项目' or not selected.is_dir():
                result.fail('WORK_SELECTION', work, '请选择 04_作品项目 下的一级作品目录')
                return result
        library = safe_path(root, '04_作品项目', result, root)
        directories = []
        if library is not None and library.is_dir():
            for child in sorted(library.iterdir()):
                if _reparse(child):
                    result.fail('PATH', child, '作品库不允许符号链接/reparse point')
                elif child.is_dir():
                    directories.append(child)
        seen = {}
        for directory in directories:
            manifest = read_manifest(directory, result)
            if manifest is None:
                continue
            identity = manifest.get('id')
            if isinstance(identity, str):
                if identity in seen:
                    result.fail('DUPLICATE_ID', directory, f'{identity} 已用于 {seen[identity]}')
                seen[identity] = directory
            if selected is None or directory == selected:
                result.work_count += 1
                validate_work(directory, manifest, phase, result)
        if phase != 'structure' and result.work_count == 0:
            result.fail('NO_WORK', root, 'prompts/delivery 门禁不能在没有作品时通过')
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        result.fail('READ', root, f'检查失败: {exc}')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='只读检查项目结构、提示词准备和交付证据。')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--work', help='04_作品项目 下一级作品的相对路径')
    parser.add_argument('--phase', choices=('structure', 'prompts', 'delivery'), default='structure')
    args = parser.parse_args()
    result = validate_project(args.root, args.work, args.phase)
    if result.errors:
        print(f'FAIL phase={args.phase} 作品数量={result.work_count} 错误数量={len(result.errors)}')
        for error in result.errors:
            print(f'- {error}')
    else:
        print(f'PASS phase={args.phase} 结构检查通过；作品数量={result.work_count}')
    print('检查仅验证文件、字段和关联；结构通过不代表已生成或已验收，也不验证媒体真实性或审美质量。')
    return 1 if result.errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
