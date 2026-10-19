"""Validate invocation templates and suggest a skill without executing it.

This is a bounded lexical router, not general natural-language understanding.
Pass only the user's current invocation intent; attached or quoted source text
does not grant permission to generate media, install skills, or publish files.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

from validate_project import safe_path, _unique_json


def _normalise(value):
    return ''.join(unicodedata.normalize('NFKC', value).casefold().split())


def _relative_file(base, relative, report, location):
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or any(part in ('', '.', '..') for part in relative.split('/'))):
        report.fail('INVOCATION_PATH', location, 'Expected a canonical package-relative POSIX file path')
        return None
    return safe_path(base, relative, report, location)


def validate_registry(root, catalog, report, packages):
    """Return validated runtime entries; old catalogs may omit the registry."""
    if 'invocation_registry' not in catalog:
        return []
    initial_errors = len(report.errors)
    registry_path = _relative_file(root, catalog['invocation_registry'], report, 'invocation_registry')
    if registry_path is None:
        return []
    creator = next((package for package in packages if package.name == 'aigc-creator'), None)
    if creator is None or registry_path not in creator.files:
        report.fail('INVOCATION_PATH', registry_path, 'Registry must belong to the installable aigc-creator package')
        return []
    try:
        document = json.loads(registry_path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_json)
        if (not isinstance(document, dict) or type(document.get('schema_version')) is not int
                or document['schema_version'] != 1 or not isinstance(document.get('skills'), list)):
            raise ValueError('Expected schema_version=1 and a skills array')
        version = catalog.get('bundle_version')
        if not isinstance(version, str) or not version.strip() or document.get('bundle_version') != version:
            raise ValueError('Registry bundle_version must match the catalog bundle_version')
    except (OSError, UnicodeError, ValueError) as exc:
        report.fail('INVOCATION', registry_path, str(exc))
        return []
    entries = {entry['name']: entry for entry in catalog['skills']
               if isinstance(entry, dict) and isinstance(entry.get('name'), str)}
    package_map = {package.name: package for package in packages}
    names, aliases_seen, validated = set(), {}, []
    for item in document['skills']:
        if not isinstance(item, dict):
            report.fail('INVOCATION', registry_path, 'Every invocation must be an object')
            continue
        name = item.get('name')
        if not isinstance(name, str) or name not in entries or name in names:
            report.fail('INVOCATION', registry_path, f'Unknown or duplicate skill name: {name}')
            continue
        names.add(name)
        aliases = item.get('aliases')
        if (not isinstance(aliases, list) or not aliases
                or any(not isinstance(alias, str) or not _normalise(alias) for alias in aliases)):
            report.fail('INVOCATION', name, 'aliases must be a nonempty array of nonempty strings')
            continue
        for alias in aliases:
            normalised = _normalise(alias)
            if normalised in aliases_seen:
                report.fail('INVOCATION_ALIAS', name,
                            f'Alias duplicates {aliases_seen[normalised]} after case/whitespace normalisation: {alias}')
            else:
                aliases_seen[normalised] = name
        package = package_map.get(name)
        if package is None:
            report.fail('INVOCATION', name, 'Invocation has no valid installable package')
            continue
        usage = _relative_file(package.source, item.get('usage'), report, name)
        if usage is None:
            continue
        try:
            if usage.suffix.lower() != '.md' or usage not in package.files:
                raise ValueError('usage must name an existing Markdown file in this skill package')
            if not usage.read_text(encoding='utf-8-sig').strip():
                raise ValueError('usage Markdown must not be empty')
        except (OSError, UnicodeError, ValueError) as exc:
            report.fail('INVOCATION_USAGE', name, str(exc))
            continue
        validated.append(dict(name=name, aliases=aliases, group=entries[name].get('group'), usage_path=str(usage)))
    if names != set(entries):
        report.fail('INVOCATION', registry_path,
                    f'Registry must cover exactly the catalog skills; missing: {sorted(set(entries) - names)}')
    return validated if len(report.errors) == initial_errors else []


def routing_error(errors):
    return dict(ok=False, status='error', selected_skill=None, candidates=[], context_modules=[],
                usage_path=None, matched_aliases={}, read_only=True, reason='调用请求或调用索引无效。', errors=errors)


def route_text(text, invocations):
    """Resolve an explicit first-line template, then known natural aliases.

    Core node intents take precedence over topic modules. Multiple core intents
    remain visible to the orchestrator; the router never executes any action.
    """
    if not isinstance(text, str) or not text.strip():
        return routing_error(['调用文本必须是非空字符串。'])
    if not invocations:
        return routing_error(['此套件未配置可用的 invocation_registry；旧版校验仍可使用。'])
    by_name = {item['name']: item for item in invocations}
    first_line = next(line.strip() for line in text.splitlines() if line.strip())
    # Match only ASCII skill tokens on the invocation line. Chinese/ASCII
    # punctuation ends the token; a polite natural-language prefix is allowed.
    explicit_names = list(dict.fromkeys(re.findall(r'\$([A-Za-z0-9][A-Za-z0-9_-]*)', first_line)))
    normalised_text = _normalise(text)
    matched = [item for item in invocations
               if any(_normalise(alias) in normalised_text for alias in item['aliases'])]
    # Preserve the user's lexical order; orchestration still reads the original
    # request to decide dependencies rather than inferring them from this list.
    matched.sort(key=lambda item: min(normalised_text.index(_normalise(alias))
                                      for alias in item['aliases']
                                      if _normalise(alias) in normalised_text))
    modules = [item['name'] for item in matched if item['group'] == 'module']
    matched_aliases = {item['name']: [alias for alias in item['aliases']
                                    if _normalise(alias) in normalised_text] for item in matched}
    if explicit_names:
        unknown = [name for name in explicit_names if name not in by_name]
        if unknown:
            return routing_error([f'未知的显式 Skill 名称: {", ".join(unknown)}；未回退到自然语言别名。'])
        candidates = [by_name[name] for name in explicit_names]
        modules = list(dict.fromkeys([*modules, *(item['name'] for item in candidates
                                                 if item['group'] == 'module')]))
        if len(candidates) == 1:
            selected, status = candidates[0], 'explicit'
            reason = '采用当前调用文本首个非空行的显式 Skill 名称。'
        else:
            selected, status = by_name['aigc-creator'], 'multiple'
            reason = '首个非空行指定了多个 Skill，保留全部候选，交总控澄清或编排。'
    else:
        core = [item for item in matched if item['group'] == 'core']
        choices = core or [item for item in matched if item['group'] == 'module']
        if len(choices) == 1:
            selected, status, candidates = choices[0], 'matched', choices
            reason = '命中已登记的自然语言别名；题材模块保留为创作上下文。'
        elif len(choices) > 1:
            selected, status, candidates = by_name['aigc-creator'], 'multiple', choices
            reason = '命中多个同层请求，保留全部候选，交总控澄清或编排。'
        else:
            selected, candidates = by_name['aigc-creator'], []
            status = 'matched' if any(item['group'] == 'orchestrator' for item in matched) else 'fallback'
            reason = ('命中总控入口。' if status == 'matched'
                      else '未命中已登记别名，回到总控判断下一步；这不表示已理解全部自然语言。')
    return dict(ok=True, status=status, selected_skill=selected['name'],
                candidates=[dict(name=item['name'], usage_path=item['usage_path']) for item in candidates],
                context_modules=modules, usage_path=selected['usage_path'], matched_aliases=matched_aliases,
                read_only=True, reason=reason, errors=[])
