"""Read-only invocation routing; fixtures are retained without recursive cleanup."""
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import skill_bundle as bundle
import validate_project


class SkillInvocationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2] / '.harness-tests' / ('invocations-' + uuid4().hex)
        self.root.mkdir(parents=True)
        self.entries = []
        self.invocations = []
        for name, group, aliases in (
                ('aigc-creator', 'orchestrator', ['继续创作']),
                ('aigc-blocking', 'core', ['写完整镜头调度']),
                ('aigc-video-prompts', 'core', ['调度转Clip']),
                ('aigc-script', 'core', ['写剧情脚本']),
                ('aigc-iteration', 'core', ['复盘创作']),
                ('aigc-narrative', 'module', ['剧情短片'])):
            relative = f'skills/{name}' if group == 'orchestrator' else f'skills/{group}/{name}'
            self.entries.append(dict(name=name, path=relative, group=group,
                                     dependencies=[] if group == 'orchestrator' else ['aigc-creator']))
            self.write(self.root / relative / 'SKILL.md',
                       f'---\nname: {name}\ndescription: "Test invocation skill."\n---\n# Skill\n')
            self.write(self.root / relative / 'references/usage.md', '# 使用方法\n\n调用正文。\n')
            self.invocations.append(dict(name=name, aliases=aliases, usage='references/usage.md'))
        self.registry_relative = 'skills/aigc-creator/references/invocations.json'
        self.catalog_document = dict(schema_version=1, bundle_version='1.1.1',
                                     invocation_registry=self.registry_relative, skills=self.entries)
        self.registry_document = dict(schema_version=1, bundle_version='1.1.1', skills=self.invocations)
        self.save()

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def save(self):
        self.write(self.root / 'skills/catalog.json', json.dumps(self.catalog_document, ensure_ascii=False))
        self.write(self.root / self.registry_relative, json.dumps(self.registry_document, ensure_ascii=False))

    def route(self, text):
        self.assertTrue(hasattr(bundle, 'route_bundle'), 'Read-only invocation routing is missing')
        return bundle.route_bundle(self.root, text)

    def assert_registry_error(self):
        errors = bundle.validate_bundle(self.root).errors
        self.assertTrue(errors, 'Invalid invocation registry was accepted')
        return errors

    def test_valid_registry_covers_all_catalog_skills(self):
        self.assertEqual([], bundle.validate_bundle(self.root).errors)

    def test_legacy_catalog_still_validates_without_registry(self):
        self.catalog_document.pop('invocation_registry')
        self.save()
        self.assertEqual([], bundle.validate_bundle(self.root).errors)

    def test_registry_bundle_version_must_match(self):
        self.registry_document['bundle_version'] = '1.0.0'
        self.save()
        self.assert_registry_error()

    def test_bad_catalog_group_reports_errors_without_crashing(self):
        self.entries[1].pop('group')
        self.save()
        self.assert_registry_error()

    def test_malformed_registry_and_duplicate_json_keys_are_rejected(self):
        for content in ('{"schema_version":1,"schema_version":1,"skills":[]}',
                        '{"schema_version":true,"skills":[]}', '[]', '{invalid'):
            with self.subTest(content=content):
                self.write(self.root / self.registry_relative, content)
                self.assert_registry_error()

    def test_registry_must_cover_exact_catalog_set(self):
        self.invocations.pop()
        self.save()
        self.assert_registry_error()

    def test_duplicate_skill_and_unknown_skill_are_rejected(self):
        self.invocations.append(dict(self.invocations[0]))
        self.invocations.append(dict(name='aigc-absent', aliases=['未知入口'], usage='references/usage.md'))
        self.save()
        self.assert_registry_error()

    def test_aliases_must_be_nonempty_strings(self):
        for aliases in ([], ['  '], [None], '写调度'):
            with self.subTest(aliases=aliases):
                self.invocations[1]['aliases'] = aliases
                self.save()
                self.assert_registry_error()

    def test_alias_collision_ignores_case_and_whitespace(self):
        self.invocations[1]['aliases'] = ['  调度转 cLiP  ']
        self.save()
        self.assert_registry_error()

    def test_missing_empty_or_non_markdown_usage_is_rejected(self):
        for usage, content in (('references/missing.md', None),
                               ('references/empty.md', ' \n\t'),
                               ('references/usage.txt', '# Usage')):
            with self.subTest(usage=usage):
                self.invocations[1]['usage'] = usage
                if content is not None:
                    self.write(self.root / self.entries[1]['path'] / usage, content)
                self.save()
                self.assert_registry_error()

    def test_usage_cannot_leave_its_own_installable_package(self):
        for usage in ('../../../aigc-creator/references/usage.md',
                      '/outside.md', 'C:/outside.md', 'references\\usage.md'):
            with self.subTest(usage=usage):
                self.invocations[1]['usage'] = usage
                self.save()
                self.assert_registry_error()

    def test_registry_path_cannot_escape_repository(self):
        self.catalog_document['invocation_registry'] = '../outside.json'
        self.save()
        self.assert_registry_error()

    def test_reparse_usage_is_rejected_before_read(self):
        suspicious = self.root / self.entries[1]['path'] / 'references/usage.md'
        original = validate_project._reparse
        with patch.object(validate_project, '_reparse', side_effect=lambda p: p == suspicious or original(p)):
            self.assert_registry_error()

    def test_first_line_explicit_name_has_priority(self):
        result = self.route('\n$aigc-blocking\n剧情短片，之后调度转Clip。')
        self.assertTrue(result['ok'], result)
        self.assertEqual('explicit', result['status'])
        self.assertEqual('aigc-blocking', result['selected_skill'])
        self.assertEqual(['aigc-narrative'], result['context_modules'])
        self.assertTrue(Path(result['usage_path']).is_file())

    def test_real_template_prefix_and_chinese_period_resolve_explicit_skill(self):
        result = self.route('请使用本项目源码中的 $aigc-blocking。\n请随后调度转Clip。')
        self.assertEqual('explicit', result['status'])
        self.assertEqual('aigc-blocking', result['selected_skill'])

    def test_short_template_prefix_with_module_skill_resolves_explicit_skill(self):
        result = self.route('请使用 $aigc-narrative。\n写完整镜头调度。')
        self.assertEqual('explicit', result['status'])
        self.assertEqual('aigc-narrative', result['selected_skill'])

    def test_unknown_prefixed_explicit_name_with_punctuation_is_rejected(self):
        result = self.route('请使用本项目源码中的 $aigc-absent，写完整镜头调度。')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['selected_skill'])

    def test_multiple_explicit_names_on_first_line_are_all_retained(self):
        result = self.route('请使用 $aigc-blocking、$aigc-video-prompts 和 $aigc-narrative。')
        self.assertEqual('multiple', result['status'])
        self.assertEqual('aigc-creator', result['selected_skill'])
        self.assertEqual({'aigc-blocking', 'aigc-video-prompts', 'aigc-narrative'},
                         {item['name'] for item in result['candidates']})
        self.assertIn('aigc-narrative', result['context_modules'])

    def test_multiple_explicit_names_with_unknown_name_do_not_partially_route(self):
        result = self.route('请使用 $aigc-blocking 和 $aigc-absent。')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['selected_skill'])

    def test_repeated_same_explicit_name_remains_a_single_intent(self):
        result = self.route('请使用 $aigc-blocking，即 $aigc-blocking。')
        self.assertEqual('explicit', result['status'])
        self.assertEqual('aigc-blocking', result['selected_skill'])

    def test_unknown_explicit_name_is_rejected_without_alias_fallback(self):
        result = self.route('$aigc-absent\n写完整镜头调度')
        self.assertFalse(result['ok'])
        self.assertEqual('error', result['status'])
        self.assertIsNone(result['selected_skill'])

    def test_chinese_alias_selects_core_with_module_context(self):
        result = self.route('请给剧情短片写完整镜头调度。')
        self.assertEqual('matched', result['status'])
        self.assertEqual('aigc-blocking', result['selected_skill'])
        self.assertEqual(['aigc-narrative'], result['context_modules'])

    def test_multiple_core_intents_are_retained_for_orchestration(self):
        result = self.route('剧情短片，写完整镜头调度，然后调度转Clip。')
        self.assertEqual('multiple', result['status'])
        self.assertEqual('aigc-creator', result['selected_skill'])
        self.assertEqual({'aigc-blocking', 'aigc-video-prompts'},
                         {item['name'] for item in result['candidates']})
        self.assertEqual(['aigc-narrative'], result['context_modules'])

    def test_natural_candidates_follow_first_alias_position_not_registry_order(self):
        self.invocations[4]['aliases'] = ['稍后复盘', '复盘创作']
        self.save()
        result = self.route('先复盘创作，再写剧情脚本，稍后复盘。')
        self.assertEqual('multiple', result['status'])
        self.assertEqual(['aigc-iteration', 'aigc-script'],
                         [item['name'] for item in result['candidates']])

    def test_explicit_candidates_follow_text_order_reverse_to_registry(self):
        result = self.route('请先使用 $aigc-iteration，再使用 $aigc-script。')
        self.assertEqual('multiple', result['status'])
        self.assertEqual(['aigc-iteration', 'aigc-script'],
                         [item['name'] for item in result['candidates']])

    def test_unmatched_request_falls_back_without_claiming_recognition(self):
        result = self.route('这个片段还差一点。')
        self.assertEqual('fallback', result['status'])
        self.assertEqual('aigc-creator', result['selected_skill'])
        self.assertEqual([], result['candidates'])
        self.assertTrue(result['read_only'])

    def test_legacy_catalog_requires_registry_for_routing(self):
        self.catalog_document.pop('invocation_registry')
        self.save()
        result = self.route('写完整镜头调度')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['selected_skill'])

    def test_empty_input_is_rejected(self):
        result = self.route(' \n\t')
        self.assertFalse(result['ok'])
        self.assertIsNone(result['selected_skill'])

    def test_module_alias_can_select_its_own_entry(self):
        result = self.route('剧情短片：火车站道别。')
        self.assertEqual('aigc-narrative', result['selected_skill'])

    def test_dollar_names_inside_body_are_not_explicit_directives(self):
        result = self.route('请写完整镜头调度。\n参考原文含 $aigc-video-prompts。')
        self.assertEqual('aigc-blocking', result['selected_skill'])

    def test_route_does_not_modify_files(self):
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.route('$aigc-blocking\n写完整镜头调度。')
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_route_command_prints_json(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = bundle.main(['route', '--root', str(self.root), '--text', '写完整镜头调度'])
        self.assertEqual(0, status)
        self.assertEqual('aigc-blocking', json.loads(output.getvalue())['selected_skill'])


if __name__ == '__main__':
    unittest.main()
