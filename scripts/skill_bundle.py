"""Validate and safely flatten the repository skill bundle using only stdlib.

Installation previews by default. Updates require --update and back up changed
files outside the discovery directory before any skill file is written. Nothing
is deleted. Preflight protects against known conflicts, not concurrent writers or
a power failure; stop other edits during installation. Partial I/O failures are
reported along with retained backups and completed writes.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import stat
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from validate_project import inline_link_destinations, _unique_json
from skill_invocations import validate_registry, route_text, routing_error


NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
RESERVED = {'con', 'prn', 'aux', 'nul', *(f'com{i}' for i in range(1, 10)),
            *(f'lpt{i}' for i in range(1, 10))}


@dataclass
class Package:
    name: str
    source: Path
    files: list[Path]
    directories: list[Path]


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    packages: list[Package] = field(default_factory=list, repr=False)
    invocations: list[dict] = field(default_factory=list, repr=False)
    backup_dir: str | None = None
    applied: bool = False
    written: list[str] = field(default_factory=list)
    attempted: list[str] = field(default_factory=list)

    def fail(self, code, location, message):
        self.errors.append(f'[{code}] {location}: {message}')


def _absolute(path):
    # Do not resolve links before examining every lexical ancestor.
    return Path(os.path.abspath(path))


def _reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 1024))


def _checked(path, report):
    """Inspect ancestors from the drive/root down, without following links."""
    path = _absolute(path)
    try:
        for component in (*reversed(path.parents), path):
            try:
                component.lstat()
            except FileNotFoundError:
                continue
            if _reparse(component):
                report.fail('PATH', component, 'Symbolic links and Windows reparse points are forbidden')
                return False
            if component != path and not component.is_dir():
                report.fail('PATH', component, 'A path ancestor is not a directory')
                return False
    except OSError as exc:
        report.fail('PATH', path, str(exc))
        return False
    return True


def _portable_component(value):
    return (value not in ('', '.', '..') and not value.endswith((' ', '.'))
            and not any(char in value for char in '\\/:*?"<>|\x00')
            and not any(ord(char) < 32 for char in value)
            and value.split('.')[0].lower() not in RESERVED)


def _source_path(root, value, report):
    if (not isinstance(value, str) or not value or ntpath.isabs(value)
            or ntpath.splitdrive(value)[0] or '\\' in value
            or not all(_portable_component(part) for part in value.split('/'))):
        report.fail('PATH', value, 'Source must be a canonical repository-relative POSIX path')
        return None
    path = root.joinpath(*value.split('/'))
    return path if _checked(path, report) else None


def _inventory(directory, report):
    """List only declared package trees; never read unknown target file content."""
    files, directories = [], []
    pending = [directory]
    while pending:
        current = pending.pop()
        if not _checked(current, report):
            continue
        try:
            children = sorted(current.iterdir(), key=lambda p: p.name.casefold())
            seen = set()
            for path in children:
                if not _portable_component(path.name) or path.name.casefold() in seen:
                    report.fail('PATH', path, 'Nonportable or case-colliding file name')
                    continue
                seen.add(path.name.casefold())
                if _reparse(path):
                    report.fail('PATH', path, 'Symbolic links and Windows reparse points are forbidden')
                elif path.is_dir():
                    directories.append(path)
                    pending.append(path)
                elif path.is_file():
                    files.append(path)
                else:
                    report.fail('PATH', path, 'Only regular files and directories are supported')
        except OSError as exc:
            report.fail('READ', current, str(exc))
    return sorted(files), sorted(directories)


def _yaml_string(value):
    """Accept quoted strings or conservative plain scalars, not full YAML."""
    value = value.strip()
    if value.startswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError('Expected a string')
        return parsed
    if value.startswith("'"):
        if not re.fullmatch(r"'(?:[^']|'')*'", value):
            raise ValueError('Unclosed quoted string')
        return value[1:-1].replace("''", "'")
    value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
    numeric = re.fullmatch(
        r'[-+]?(?:0x[0-9a-f_]+|0b[01_]+|0o[0-7_]+|'
        r'(?:[0-9][0-9_]*(?::[0-9_]+)*(?:\.[0-9_]*)?|\.[0-9_]+)(?:e[-+]?[0-9]+)?|\.(?:inf|nan))',
        value, flags=re.IGNORECASE)
    if (not value or value[0] in '[]{}!&*|>%@`,#' or re.search(r':(?:\s|$)', value)
            or re.match(r'^[-?](?:\s|$)', value)
            or value.lower() in ('true', 'false', 'null', '~', 'yes', 'no', 'on', 'off')
            or numeric or re.fullmatch(r'\d{4}-\d{1,2}-\d{1,2}(?:[Tt \t].*)?', value)):
        raise ValueError('Required fields must be YAML strings')
    return value


def _frontmatter(path, entry, report):
    try:
        text = path.read_text(encoding='utf-8-sig')
        match = re.match(r'\A---\s*\r?\n(.*?)\r?\n---\s*(?:\r?\n|\Z)', text, re.DOTALL)
        if not match:
            raise ValueError('Missing YAML frontmatter')
        values = {}
        lines = match.group(1).splitlines()
        index = 0
        allow_nested = False
        while index < len(lines):
            line = lines[index]
            index += 1
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            if line[0].isspace():
                if not allow_nested:
                    raise ValueError('Unexpected indentation after a scalar; quote it or use a block string')
                continue
            item = re.fullmatch(r'([A-Za-z_][\w-]*):\s*(.*)', line)
            if not item:
                raise ValueError('Unsupported frontmatter syntax')
            key, raw = item.groups()
            allow_nested = key not in ('name', 'description') and (not raw or bool(re.fullmatch(r'[>|][-+]?', raw)))
            if key in values:
                raise ValueError(f'Duplicate frontmatter field: {key}')
            if key not in ('name', 'description'):
                values[key] = raw
                continue
            if re.fullmatch(r'[>|][-+]?', raw):
                block = []
                while index < len(lines) and (not lines[index].strip() or lines[index][0].isspace()):
                    block.append(lines[index].strip())
                    index += 1
                values[key] = (' ' if raw[0] == '>' else '\n').join(block).strip()
            else:
                values[key] = _yaml_string(raw)
        if values.get('name') != entry['name']:
            raise ValueError('Frontmatter name must match catalog and folder name')
        if not values.get('description', '').strip():
            raise ValueError('Frontmatter description must be a nonempty string')
        if 'description' in entry and values['description'] != entry['description']:
            raise ValueError('Frontmatter description differs from the catalog')
    except (OSError, UnicodeError, ValueError) as exc:
        report.fail('FRONTMATTER', path, str(exc))


def _markdown_links(path, package, report):
    try:
        content = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError) as exc:
        report.fail('READ', path, str(exc))
        return
    lines, fence, list_indent = [], None, None
    for line in content.splitlines():
        marker = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if marker:
            run, tail = marker.groups()
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not tail.strip():
                fence = None
            continue
        if fence is None:
            expanded = line.expandtabs(4)
            indent = len(expanded) - len(expanded.lstrip())
            bullet = re.match(r'^\s*(?:[-+*]|\d+[.)])\s+', expanded)
            code_indent = list_indent + 4 if list_indent is not None else 4
            if expanded.strip() and indent >= code_indent:
                continue
            if bullet:
                list_indent = bullet.end()
            elif expanded.strip() and indent == 0:
                list_indent = None
            lines.append(line)
    content = re.sub(r'(`+)(.*?)\1', '', '\n'.join(lines), flags=re.DOTALL)
    destinations = list(inline_link_destinations(content))
    definitions = set()
    for definition in re.finditer(r'^\s{0,3}\[([^\]\n]+)\]:\s*(.+)$', content, flags=re.MULTILINE):
        label, destination = definition.groups()
        definitions.add(' '.join(label.casefold().split()))
        destinations.extend(inline_link_destinations(f'[reference]({destination})'))
    for link in re.finditer(r'(?<!!)\[([^\]\n]+)\]\[([^\]\n]*)\]', content):
        label = ' '.join((link.group(2) or link.group(1)).casefold().split())
        if label not in definitions:
            report.fail('LINK', path, f'Missing Markdown reference definition: {label}')
    for value in destinations:
        if value.startswith('#') or re.match(r'^(?:https?|mailto|data|app|codex|plugin):', value, re.IGNORECASE):
            continue
        try:
            local = unquote(urlsplit(value).path)
        except ValueError:
            report.fail('LINK', path, f'Invalid link: {value}')
            continue
        if not local:
            continue
        if ntpath.isabs(value) or ntpath.splitdrive(value)[0] or ntpath.isabs(local) or ':' in local or '\x00' in local:
            report.fail('LINK_PATH', path, f'Absolute or special local link is forbidden: {value}')
            continue
        destination = _absolute(path.parent / local.replace('\\', '/'))
        if not destination.is_relative_to(package):
            report.fail('LINK_PATH', path, f'Link leaves its installable package: {value}')
        elif _checked(destination, report) and not destination.exists():
            report.fail('LINK', path, f'Missing resource: {value}')


def validate_bundle(root):
    report = Report()
    root = _absolute(root)
    manifest = root / 'skills/catalog.json'
    if not _checked(manifest, report):
        return report
    try:
        document = json.loads(manifest.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_json)
        if (not isinstance(document, dict) or type(document.get('schema_version')) is not int
                or document['schema_version'] != 1 or not isinstance(document.get('skills'), list)
                or not document['skills']):
            raise ValueError('Expected schema_version=1 and a nonempty skills array')
    except (OSError, UnicodeError, ValueError) as exc:
        report.fail('CATALOG', manifest, str(exc))
        return report
    entries, paths = {}, []
    for entry in document['skills']:
        if not isinstance(entry, dict):
            report.fail('CATALOG', manifest, 'Every skill must be an object')
            continue
        name = entry.get('name')
        if (not isinstance(name, str) or len(name) > 64 or not NAME.fullmatch(name)
                or name in RESERVED or name in entries):
            report.fail('NAME', manifest, f'Illegal or duplicate skill name: {name}')
            continue
        entries[name] = entry
        if entry.get('group') not in ('orchestrator', 'core', 'module'):
            report.fail('CATALOG', name, 'Unknown skill group')
        dependencies = entry.get('dependencies')
        if (not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies)
                or (isinstance(dependencies, list) and len(set(dep for dep in dependencies if isinstance(dep, str))) != len(dependencies))):
            report.fail('DEPENDENCY', name, 'dependencies must be a unique array of skill names')
        source = _source_path(root, entry.get('path'), report)
        if source is None:
            continue
        if source.name != name:
            report.fail('NAME', source, 'Source folder name differs from skill name')
        if any(source == other or source.is_relative_to(other) or other.is_relative_to(source) for other in paths):
            report.fail('PATH', source, 'Source package directories overlap')
        paths.append(source)
        if not source.is_dir():
            report.fail('ENTRYPOINT', source, 'Source package directory is missing')
            continue
        files, directories = _inventory(source, report)
        entrypoint = source / 'SKILL.md'
        if entrypoint not in files:
            report.fail('ENTRYPOINT', entrypoint, 'Missing SKILL.md')
        else:
            _frontmatter(entrypoint, entry, report)
        for path in files:
            if path.suffix.lower() == '.md':
                _markdown_links(path, source, report)
        report.packages.append(Package(name, source, files, directories))
    orchestrators = [name for name, entry in entries.items() if entry.get('group') == 'orchestrator']
    if orchestrators != ['aigc-creator']:
        report.fail('DEPENDENCY', manifest, 'Exactly one aigc-creator orchestrator is required')
    graph = {}
    for name, entry in entries.items():
        dependencies = entry.get('dependencies')
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            continue
        graph[name] = dependencies
        if entry.get('group') == 'orchestrator' and dependencies:
            report.fail('DEPENDENCY', name, 'Orchestrator must have no dependencies')
        if entry.get('group') != 'orchestrator' and 'aigc-creator' not in dependencies:
            report.fail('DEPENDENCY', name, 'Non-orchestrator packages must depend on aigc-creator')
        for dependency in dependencies:
            if dependency not in entries:
                report.fail('DEPENDENCY', name, f'Missing dependency: {dependency}')
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            report.fail('CYCLE', name, 'Dependency cycle detected')
            return
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph.get(name, []):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for name in graph:
        visit(name)
    report.invocations = validate_registry(root, document, report, report.packages)
    return report


def route_bundle(root, text):
    """Read-only invocation suggestion; never generates, installs, or publishes."""
    report = validate_bundle(root)
    if report.errors:
        return routing_error(report.errors)
    return route_text(text, report.invocations)


def _digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(64 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _copy(source, destination, *, overwrite=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if overwrite and destination.stat().st_nlink > 1:
        raise OSError(f'Refusing to overwrite a hardlinked target: {destination}')
    with source.open('rb') as incoming, destination.open('wb' if overwrite else 'xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
    shutil.copystat(source, destination)


def install_bundle(root, target, *, apply=False, update=False):
    report = validate_bundle(root)
    if report.errors:
        return report
    target = _absolute(target)
    if not _checked(target, report):
        return report
    if target.exists() and not target.is_dir():
        report.fail('TARGET', target, 'Target must be a directory')
    for package in report.packages:
        if (target == package.source or target.is_relative_to(package.source)
                or package.source.is_relative_to(target)):
            report.fail('TARGET', target, 'Target overlaps a source package')
    if report.errors:
        return report
    for package in report.packages:
        destination = target / package.name
        if not _checked(destination, report):
            continue
        if destination.exists() and not destination.is_dir():
            report.fail('TARGET', destination, 'Skill destination must be a directory')
            continue
        existing_files, existing_directories = _inventory(destination, report) if destination.exists() else ([], [])
        expected_files = {path.relative_to(package.source) for path in package.files}
        expected_dirs = {path.relative_to(package.source) for path in package.directories}
        for path in (*existing_files, *existing_directories):
            relative = path.relative_to(destination)
            if relative not in expected_files and relative not in expected_dirs:
                report.extras.append(path.relative_to(target).as_posix())
        for relative in expected_dirs:
            path = destination / relative
            if _checked(path, report) and path.exists() and not path.is_dir():
                report.fail('TARGET', path, 'A file blocks a required directory')
        for source in package.files:
            path = destination / source.relative_to(package.source)
            if not _checked(path, report):
                continue
            try:
                action, old_hash = 'create', None
                if path.exists():
                    if not path.is_file():
                        report.fail('TARGET', path, 'A directory blocks a required file')
                        continue
                    if path.stat().st_nlink > 1:
                        report.fail('TARGET', path, 'Hardlinked target files cannot be safely overwritten')
                        continue
                    old_hash = _digest(path)
                    action = 'unchanged' if old_hash == _digest(source) else 'update'
                    if action == 'update' and not update:
                        report.fail('CONFLICT', path, 'Content differs; explicit --update is required')
                report.actions.append(dict(action=action, source=str(source), destination=str(path),
                                           source_sha256=_digest(source), target_sha256=old_hash))
            except OSError as exc:
                report.fail('READ', path, str(exc))
    changes = [item for item in report.actions if item['action'] != 'unchanged']
    updates = [item for item in changes if item['action'] == 'update']
    backup_base = target.parent / (target.name + '-backups')
    if updates:
        if backup_base.is_relative_to(target) or any(
                backup_base == p.source or backup_base.is_relative_to(p.source)
                or p.source.is_relative_to(backup_base) for p in report.packages):
            report.fail('BACKUP', backup_base, 'Backup location overlaps discovery or source directories')
        _checked(backup_base, report)
        if backup_base.exists() and not backup_base.is_dir():
            report.fail('BACKUP', backup_base, 'Backup base is not a directory')
    if report.errors or not apply:
        return report
    if updates:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        backup = backup_base / f'{stamp}-{uuid4().hex}'
        report.backup_dir = str(backup)
        try:
            for item in updates:
                path = Path(item['destination'])
                if not _checked(path, report) or not _checked(backup, report):
                    return report
                _copy(path, backup / path.relative_to(target))
        except OSError as exc:
            report.fail('BACKUP', backup, str(exc))
            return report
    # Recheck every planned content state before making the first install write.
    for item in report.actions:
        source, path = Path(item['source']), Path(item['destination'])
        if not _checked(source, report) or not _checked(path, report):
            continue
        try:
            if (_digest(source) != item['source_sha256']
                    or (path.exists() and (not path.is_file() or _digest(path) != item['target_sha256']))
                    or (not path.exists() and item['target_sha256'] is not None)):
                report.fail('CHANGED', path, 'Source or target changed after preflight; rerun the preview')
        except OSError as exc:
            report.fail('READ', path, str(exc))
    if report.errors:
        return report
    try:
        for item in changes:
            source, path = Path(item['source']), Path(item['destination'])
            if not _checked(source, report) or not _checked(path, report):
                return report
            report.attempted.append(str(path))
            _copy(source, path, overwrite=item['action'] == 'update')
            report.written.append(str(path))
        for package in report.packages:
            for directory in package.directories:
                path = target / package.name / directory.relative_to(package.source)
                if not _checked(path, report):
                    return report
                path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        report.fail('WRITE', path, f'{exc}; this target may be partially written; attempted writes and backups are retained')
        return report
    report.applied = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'install', 'route'):
        command_parser = subcommands.add_parser(command)
        command_parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
        if command == 'install':
            command_parser.add_argument('--target', type=Path, required=True)
            command_parser.add_argument('--apply', action='store_true', help='Write the preflighted installation')
            command_parser.add_argument('--update', action='store_true', help='Back up and replace changed known files')
        elif command == 'route':
            command_parser.add_argument('--text', required=True,
                                        help='Current user invocation intent only; suggestions do not execute actions')
    args = parser.parse_args(argv)
    if args.command == 'route':
        result = route_bundle(args.root, args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    if args.command == 'validate':
        report = validate_bundle(args.root)
        mode = 'validate'
    else:
        report = install_bundle(args.root, args.target, apply=args.apply, update=args.update)
        mode = 'apply' if args.apply else 'preview'
    print(json.dumps(dict(mode=mode, ok=not report.errors, package_count=len(report.packages),
                          errors=report.errors, actions=report.actions, extras_preserved=report.extras,
                          backup_dir=report.backup_dir, applied=report.applied,
                          written=report.written, attempted=report.attempted), ensure_ascii=False, indent=2))
    return 1 if report.errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
