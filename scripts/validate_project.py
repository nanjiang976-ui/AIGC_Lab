"""Read-only, standard-library checks for the AIGC project harness.

Evidence checks prove only that referenced files exist and are nonempty; they do
not establish media authenticity, aesthetics, copyright, or human approval.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime
import io
import json
import math
import ntpath
from pathlib import Path
import re
import stat
import string
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
SHOT_TOKEN = re.compile(r'(?<![A-Za-z0-9_])EP\d{2,}_SH\d{3,}(?![A-Za-z0-9_])')
CLIP_ID = re.compile(r'EP\d{2,}_CL\d{3,}\Z')
CLIP_TOKEN = re.compile(r'(?<![A-Za-z0-9_])EP\d{2,}_CL\d{3,}(?![A-Za-z0-9_])')
CLIP_FILE = '04_生成提示词/clips.json'
ENTRY_MODES = ('text_to_video', 'reference_to_video', 'first_frame', 'first_last_frames')
REFERENCE_ROLES = ('identity', 'scene', 'first_frame', 'last_frame', 'style', 'audio')
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff', '.avif')
TIME_EPSILON = 1e-6
MARKDOWN_ESCAPE = re.compile(r'\\([' + re.escape(string.punctuation) + r'])')


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


def inline_link_destinations(content: str):
    """Read inline destinations with balanced parentheses and Markdown escapes."""
    prefix = re.compile(r'\[(?:\\.|[^\]\\\n])*\]\(\s*')
    title_tail = re.compile(r'''\s+(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\((?:\\.|[^)\\])*\))\s*\)''')
    for match in prefix.finditer(content):
        preceding = match.start() - 1
        while preceding >= 0 and content[preceding] == '\\':
            preceding -= 1
        if (match.start() - preceding - 1) % 2:
            continue
        index = match.end()
        if index >= len(content):
            continue
        angled = content[index] == '<'
        if angled:
            index += 1
        start = index
        depth = 0
        while index < len(content):
            char = content[index]
            if char == '\\' and index + 1 < len(content) and content[index + 1] in string.punctuation:
                index += 2
                continue
            if angled:
                if char in '<>\r\n':
                    break
            elif char.isspace() or (char == ')' and depth == 0):
                break
            elif char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            index += 1
        if depth or index >= len(content):
            continue
        destination = content[start:index]
        if angled:
            if content[index] != '>':
                continue
            index += 1
        if re.match(r'\s*\)', content[index:]) or title_tail.match(content, index):
            yield MARKDOWN_ESCAPE.sub(r'\1', destination)


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
    for value in inline_link_destinations('\n'.join(lines)):
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
    for relative in ('spec', 'skills', *CONTENT_DIRS):
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
    layout = manifest.get('prompt_layout', 'per_shot')
    if layout not in ('per_shot', 'clips'):
        result.fail('SCHEMA', directory, 'prompt_layout 必须是 per_shot 或 clips')
    if layout == 'clips' and manifest.get('kind') not in ('video', 'comic'):
        result.fail('SCHEMA', directory, 'clips 发送布局仅适用于 video/comic')
    if 'clips_file' in manifest:
        safe_path(directory, manifest['clips_file'], result, directory / 'project.json')
        if layout != 'clips':
            result.fail('SCHEMA', directory, 'clips_file 仅用于 clips 布局，避免未校验的 Clip 台账')
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


def validate_shots(directory: Path, manifest: dict, gate: bool, result: Result) -> dict[str, float | None]:
    path = require_file(directory, '03_分镜表.csv', result, directory)
    if path is None:
        return {}
    content = read_text(path, result)
    if content is None:
        return {}
    if gate and PLACEHOLDER.search(content):
        result.fail('PLACEHOLDER', path, '提示词就绪门禁不允许占位内容')
    try:
        reader = csv.DictReader(io.StringIO(content, newline=''), strict=True)
        if reader.fieldnames is None or any(key not in reader.fieldnames for key in CSV_FIELDS) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            result.fail('CSV_HEADER', path, f'需要唯一字段: {",".join(CSV_FIELDS)}')
            return {}
        rows = list(reader)
    except csv.Error as exc:
        result.fail('CSV', path, str(exc))
        return {}
    required = gate
    rows = [row for row in rows if any(value for value in row.values())]
    if required and not rows:
        result.fail('SHOTS', path, '至少需要一个完整镜头')
    durations = {}
    for index, row in enumerate(rows, 2):
        location = f'{path}:{index}'
        if None in row or any(value is None for value in row.values()):
            result.fail('CSV_ROW', location, '行列数不匹配')
            continue
        for key, code in (('shot_id', 'SHOT_ID'), ('duration_seconds', 'DURATION')):
            if '\n' in row[key] or '\r' in row[key]:
                result.fail(code, location, f'{key} 必须是单行值，不允许内部换行')
        row = {key: value.strip() for key, value in row.items()}
        must_fill = ['shot_id', 'scene_id', 'description', 'duration_seconds']
        if manifest.get('prompt_layout', 'per_shot') == 'per_shot':
            must_fill.append('image_prompt')
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
            if shot in durations:
                result.fail('DUPLICATE_SHOT', location, f'重复镜头编号: {shot}')
            durations[shot] = None
        if row['duration_seconds']:
            try:
                duration = float(row['duration_seconds'])
                if not math.isfinite(duration) or duration < 0 or (manifest['kind'] != 'image' and duration == 0):
                    raise ValueError('时长范围错误')
                if shot:
                    durations[shot] = duration
            except ValueError:
                result.fail('DURATION', location, '图片时长须为有限非负数；视频/漫剧须为有限正数')
        for reference in row['reference_files'].split(';'):
            if reference.strip():
                require_file(directory, reference.strip(), result, location)
    return durations


def validate_sent_prompts(content: str, ids: list[str], path: Path, result: Result,
                          clips: bool = False) -> None:
    """Match each Shot/Clip heading to nonempty text; fenced IDs are not headings."""
    token = CLIP_TOKEN if clips else SHOT_TOKEN
    label = 'Clip' if clips else '镜头'
    code = 'SEND_CLIP' if clips else 'SEND_SHOT'
    groups = []
    current = None
    fence = None
    block = None
    comment = False
    for line in content.splitlines():
        if fence is not None:
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}[ \t]*', line):
                fence = None
                block = None
            elif block is not None:
                block.append(line)
            continue
        # Fenced text is literal input; HTML comments are hidden only outside it.
        visible = []
        while line:
            marker = '-->' if comment else '<!--'
            index = line.find(marker)
            if index < 0:
                if not comment:
                    visible.append(line)
                break
            if not comment:
                visible.append(line[:index])
            line = line[index + len(marker):]
            comment = not comment
        line = ''.join(visible)
        opening = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if opening:
            fence = opening.group(1)
            block = [] if current is not None else None
            if current is not None:
                current['blocks'].append(block)
            continue
        heading = re.match(r'^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$', line)
        if heading:
            level = len(heading.group(1))
            if clips and SHOT_TOKEN.search(heading.group(2) or ''):
                result.fail('SEND_CLIP', path, 'clips 布局不能混入逐 Shot 发送标题；镜头列表放 Clip 正文内')
            shots = token.findall(heading.group(2) or '')
            if shots:
                if len(shots) != 1:
                    result.fail(code, path, f'每个{label}标题只能包含一个{label}编号')
                current = dict(shot=shots[0], level=level, text=[], blocks=[])
                groups.append(current)
            elif current is not None and level <= current['level']:
                current = None
            continue
        if re.fullmatch(r' {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})', line):
            continue
        if current is not None:
            current['text'].append(line)
    if fence is not None:
        result.fail('SEND_FENCE', path, '发送正文代码块必须闭合')
    seen = set()
    expected = set(ids)
    for group in groups:
        shot = group['shot']
        if shot in seen:
            result.fail('SEND_DUPLICATE', path, f'重复{label}标题组: {shot}')
        seen.add(shot)
        if shot not in expected:
            result.fail('SEND_EXTRA', path, f'发送版含台账之外的{label}: {shot}')
        bodies = group['blocks'] or [group['text']]
        if any(not '\n'.join(body).strip() for body in bodies):
            result.fail('SEND_EMPTY', path, f'{label} {shot} 缺少非空可发送正文')
    for shot in ids:
        if shot not in seen:
            result.fail(code, path, f'本次发送.md 缺少{label}标题: {shot}')


def clip_text(record: dict, key: str, required: bool, result: Result,
              location: object, code: str = 'CLIP_SCHEMA') -> str:
    value = record.get(key, '')
    if not isinstance(value, str):
        result.fail(code, location, f'{key} 必须是字符串')
        return ''
    if not value.strip():
        if required:
            result.fail(code, location, f'{key} 不能为空')
        return ''
    if value != value.strip() or '\n' in value or '\r' in value:
        result.fail(code, location, f'{key} 须为无首尾空白的单行值')
    return value


def clip_number(record: dict, key: str, required: bool, result: Result,
                location: object, positive: bool = False) -> float | None:
    value = record.get(key, '')
    if value is None or value == '':
        if required:
            result.fail('CLIP_TIME', location, f'{key} 不能为空')
        return None
    try:
        if type(value) not in (int, float):
            raise ValueError('必须是 JSON 数值，不能是字符串或布尔值')
        number = float(value)
        if not math.isfinite(number) or number < 0 or (positive and number == 0):
            raise ValueError('必须有限且非负；时长和区间终点须大于零')
    except (ValueError, OverflowError) as exc:
        result.fail('CLIP_TIME', location, f'{key}: {exc}')
        return None
    return number


def same_time(first: float, second: float) -> bool:
    # Absolute tolerance only: large timestamps must not hide large omissions.
    return math.isclose(first, second, rel_tol=0, abs_tol=TIME_EPSILON)


def interval_can_precede(first: tuple[float | None, float | None],
                         second: tuple[float | None, float | None],
                         gap: bool = False) -> bool:
    """Can two positive, nonnegative intervals be disjoint in this order?

    Missing endpoints remain unknown. A missing end is strictly after its
    start, and a missing start is strictly before its end; it is not zero.
    """
    if first[1] is not None and second[0] is not None:
        return first[1] < second[0] if gap else first[1] <= second[0] + TIME_EPSILON
    lower = first[1] if first[1] is not None else (first[0] if first[0] is not None else 0)
    upper = second[0] if second[0] is not None else (second[1] if second[1] is not None else math.inf)
    return lower < upper


def validate_clip_references(clip: dict, mode: str, directory: Path,
                             gate: bool, result: Result, location: object) -> None:
    references = clip.get('references', [])
    if not isinstance(references, list):
        result.fail('CLIP_SCHEMA', location, 'references 必须是数组')
        return
    labels = set()
    ready_roles = set()
    for index, reference in enumerate(references, 1):
        item_location = f'{location}/references[{index}]'
        if not isinstance(reference, dict):
            result.fail('CLIP_SCHEMA', item_location, '参考条目必须是对象')
            continue
        label = clip_text(reference, 'label', gate, result, item_location, 'CLIP_REFERENCE')
        role = clip_text(reference, 'role', gate, result, item_location, 'CLIP_REFERENCE')
        file = clip_text(reference, 'file', gate, result, item_location, 'CLIP_REFERENCE')
        if label:
            if len(label.split()) != 1 or label in labels:
                result.fail('CLIP_REFERENCE', item_location, 'label 必须是本 Clip 内唯一的单个标识')
            labels.add(label)
        if role and role not in REFERENCE_ROLES:
            result.fail('CLIP_REFERENCE', item_location, f'未知参考用途: {role}')
        if file:
            target = require_file(directory, file, result, item_location)
            image_role = role in REFERENCE_ROLES and role != 'audio'
            if image_role and Path(file).suffix.lower() not in IMAGE_EXTENSIONS:
                result.fail('CLIP_REFERENCE', item_location, '图像用途引用须使用图像文件扩展名；实际内容另行审查')
            elif target is not None and label and role in REFERENCE_ROLES:
                ready_roles.add(role)
    if gate:
        if mode == 'text_to_video' and references:
            result.fail('CLIP_REFERENCE', location, 'text_to_video 的实际上传 references 必须为空；创作参考另存设计稿')
        needed = {'first_frame'} if mode == 'first_frame' else (
            {'first_frame', 'last_frame'} if mode == 'first_last_frames' else set())
        if needed - ready_roles:
            result.fail('CLIP_REFERENCE', location, f'{mode} 缺少实际输入用途: {sorted(needed - ready_roles)}')
        if mode == 'reference_to_video' and not ready_roles.intersection(('identity', 'scene', 'style')):
            result.fail('CLIP_REFERENCE', location, 'reference_to_video 须绑定至少一份身份/场景/风格图')


def validate_clip_segments(clip: dict, duration: float | None, shots: dict[str, float | None],
                           coverage: dict[str, list[tuple[float | None, float | None]]], gate: bool,
                           result: Result, location: object) -> None:
    segments = clip.get('segments', [])
    if not isinstance(segments, list):
        result.fail('CLIP_SCHEMA', location, 'segments 必须是数组')
        return
    if gate and not segments:
        result.fail('CLIP_MAPPING', location, '每条 Clip 至少包含一个 Shot 区间')
    end = 0.0
    complete = True
    preceding = []
    for index, segment in enumerate(segments, 1):
        item_location = f'{location}/segments[{index}]'
        if not isinstance(segment, dict):
            result.fail('CLIP_SCHEMA', item_location, '区间必须是对象')
            complete = False
            continue
        shot = clip_text(segment, 'shot_id', gate, result, item_location, 'CLIP_MAPPING')
        if shot and (not SHOT_ID.fullmatch(shot) or shot not in shots):
            result.fail('CLIP_MAPPING', item_location, f'引用不在分镜表中的 Shot: {shot}')
        values = [clip_number(segment, key, gate, result, item_location, positive=key.endswith('end_seconds'))
                  for key in ('shot_start_seconds', 'shot_end_seconds', 'clip_start_seconds', 'clip_end_seconds')]
        if any(value is None for value in values):
            complete = False
        shot_start, shot_end, clip_start, clip_end = values
        shot_interval = shot_start is not None and shot_end is not None
        clip_interval = clip_start is not None and clip_end is not None
        if shot_interval and shot_end <= shot_start:
            result.fail('CLIP_TIME', item_location, 'Shot 区间终点必须大于起点')
            shot_interval = False
        if clip_interval and clip_end <= clip_start:
            result.fail('CLIP_TIME', item_location, 'Clip 区间终点必须大于起点')
            clip_interval = False
        if shot_interval and clip_interval and not same_time(shot_end - shot_start, clip_end - clip_start):
            result.fail('CLIP_TIME', item_location, 'Shot 与 Clip 映射区间须等长；变速需另行设计')
        # In a draft, gaps may still need filling, but known overlaps and bounds are invalid.
        if clip_start is None or clip_end is None or clip_end > clip_start:
            current = (clip_start, clip_end)
            if any(not interval_can_precede(previous, current, gap=index - previous_index > 1)
                   for previous_index, previous in preceding):
                result.fail('CLIP_TIME', item_location, '已填端点与前段时间顺序冲突；缺失端点不能消除重叠')
            preceding.append((index, current))
        if clip_interval:
            if clip_start < end - TIME_EPSILON or (gate and not same_time(clip_start, end)):
                result.fail('CLIP_TIME', item_location, 'Clip 区间须按时间顺序衔接，不能重叠；就绪时不能漏段')
            end = clip_end
        if duration is not None and any(value is not None and value > duration + TIME_EPSILON
                                        for value in (clip_start, clip_end)):
            result.fail('CLIP_TIME', item_location, '区间超出 Clip 时长')
        if shot in shots:
            if shots[shot] is not None and any(value is not None and value > shots[shot] + TIME_EPSILON
                                              for value in (shot_start, shot_end)):
                result.fail('CLIP_MAPPING', item_location, f'区间超出 {shot} 计划时长')
            if (shot_start is not None or shot_end is not None) and (
                    shot_start is None or shot_end is None or shot_end > shot_start):
                coverage[shot].append((shot_start, shot_end))
    if gate and complete and duration is not None and not same_time(end, duration):
        result.fail('CLIP_TIME', location, 'Clip 区间须完整覆盖 0 至 duration_seconds')


def validate_clips(directory: Path, manifest: dict, shots: dict[str, float | None],
                   gate: bool, result: Result) -> list[str]:
    relative = manifest.get('clips_file', CLIP_FILE)
    path = safe_path(directory, relative, result, directory / 'project.json')
    if path is None or (not gate and not path.exists()):
        return []
    path = require_file(directory, relative, result, directory / 'project.json')
    if path is None:
        return []
    content = read_text(path, result)
    if content is None:
        return []
    try:
        payload = json.loads(content, object_pairs_hook=_unique_json,
                             parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f'非法数值: {value}')))
    except (ValueError, RecursionError) as exc:
        result.fail('JSON', path, str(exc))
        return []
    if not isinstance(payload, dict):
        result.fail('CLIP_SCHEMA', path, 'clips.json 顶层必须是对象')
        return []
    if type(payload.get('schema_version')) is not int or payload['schema_version'] != 1:
        result.fail('CLIP_SCHEMA', path, 'Clip schema_version 必须是整数 1')
    if payload.get('revision') != manifest['revision']:
        result.fail('REVISION', path, 'Clip 台账 revision 必须匹配当前作品 revision')
    clips = payload.get('clips')
    if not isinstance(clips, list):
        result.fail('CLIP_SCHEMA', path, 'clips 必须是数组')
        return []
    if gate and not clips:
        result.fail('CLIP_SCHEMA', path, '就绪门禁至少需要一条 Clip')
    identities = []
    coverage = {shot: [] for shot in shots}
    for index, clip in enumerate(clips, 1):
        location = f'{path}/clips[{index}]'
        if not isinstance(clip, dict):
            result.fail('CLIP_SCHEMA', location, 'Clip 必须是对象')
            continue
        identity = clip_text(clip, 'clip_id', gate, result, location, 'CLIP_ID')
        if identity:
            if not CLIP_ID.fullmatch(identity):
                result.fail('CLIP_ID', location, f'无效 Clip 编号: {identity}')
            if identity in identities:
                result.fail('DUPLICATE_CLIP', location, f'重复 Clip 编号: {identity}')
            identities.append(identity)
        duration = clip_number(clip, 'duration_seconds', gate, result, location, positive=True)
        mode = clip_text(clip, 'entry_mode', gate, result, location)
        if mode and mode not in ENTRY_MODES:
            result.fail('CLIP_SCHEMA', location, f'未知 entry_mode: {mode}')
        validate_clip_references(clip, mode, directory, gate, result, location)
        validate_clip_segments(clip, duration, shots, coverage, gate, result, location)
    for shot, intervals in coverage.items():
        for index, current in enumerate(intervals):
            if any((None in current or None in previous)
                   and not interval_can_precede(previous, current)
                   and not interval_can_precede(current, previous)
                   for previous in intervals[:index]):
                result.fail('CLIP_MAPPING', path, f'{shot} 已填端点确定重叠，不能靠缺失端点绕过检查')
        completed_intervals = [(start, stop) for start, stop in intervals if start is not None and stop is not None]
        if gate and not completed_intervals:
            result.fail('CLIP_MAPPING', path, f'{shot} 没有任何 Clip 映射区间')
        end = 0.0
        for start, stop in sorted(completed_intervals):
            if start < end - TIME_EPSILON or (gate and not same_time(start, end)):
                result.fail('CLIP_MAPPING', path, f'{shot} 跨 Clip 覆盖重叠或漏段')
            end = max(end, stop)
        if gate and shots[shot] is not None and not same_time(end, shots[shot]):
            result.fail('CLIP_MAPPING', path, f'{shot} 未完整覆盖计划时长 {shots[shot]} 秒')
    return identities


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
                if gate and not content.strip():
                    result.fail('EMPTY', path, '就绪门槛要求必填文档正文非空白')
                if gate and relative != '06_修改与验收.md' and PLACEHOLDER.search(content):
                    result.fail('PLACEHOLDER', path, '提示词就绪门禁不允许占位内容')
    shots = validate_shots(directory, manifest, gate, result)
    clips = manifest.get('prompt_layout', 'per_shot') == 'clips'
    ids = validate_clips(directory, manifest, shots, gate, result) if clips else list(shots)
    if gate:
        sent = contents.get('04_生成提示词/本次发送.md', '')
        validate_sent_prompts(sent, ids, directory / '04_生成提示词/本次发送.md', result, clips=clips)
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
