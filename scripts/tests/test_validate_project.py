"""Contract tests. Fixtures are retained under .harness-tests; no cleanup deletes files."""
import csv
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_project as validator
from validate_project import ROOT_REQUIRED, CSV_FIELDS, WORK_REQUIRED, validate_project


class ProjectValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2] / '.harness-tests' / uuid4().hex
        self.root.mkdir(parents=True)
        for relative in ROOT_REQUIRED:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('项目说明\n', encoding='utf-8')

    def work(self, name='001_测试', status='DRAFT', scope='prompts', kind='image'):
        directory = self.root / '04_作品项目' / name
        directory.mkdir(parents=True)
        for relative in ('00_创作需求.md', '01_故事与角色设定.md', '02_剧情脚本.md',
                         '04_生成提示词/本次发送.md', '06_修改与验收.md'):
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('内容完整。镜头 EP01_SH001。\n', encoding='utf-8')
        self.write_shots(directory)
        manifest = dict(schema_version=1, id='WORK-001', title='雨夜便利店', kind=kind,
                        scope=scope, revision='v001', status=status,
                        generation=dict(status='NOT_RUN', tool='', model='', generated_at='', revision='', evidence=[]),
                        review=dict(status='NOT_RUN', reviewer='', reviewed_at='', revision='', evidence=[]))
        self.save_manifest(directory, manifest)
        return directory, manifest

    def save_manifest(self, directory, manifest):
        (directory / 'project.json').write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')

    def write_shots(self, directory, **changes):
        row = dict(shot_id='EP01_SH001', duration_seconds='3', scene_id='SCENE-001',
                   character_ids='', description='雨夜的便利店', dialogue='',
                   image_prompt='便利店夜景', video_prompt='镜头缓缓推进', reference_files='')
        row.update(changes)
        self.write_rows(directory, [row])

    def write_rows(self, directory, rows):
        with (directory / '03_分镜表.csv').open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

    def approved(self, directory, manifest, field):
        evidence = directory / ('review.md' if field == 'review' else 'output.png')
        evidence.write_bytes(b'evidence')
        manifest[field].update(status='PASS', revision='v001', evidence=[evidence.name])
        if field == 'review':
            manifest[field].update(reviewer='NJ', reviewed_at='2026-09-28T12:00:00+08:00')
        else:
            manifest[field].update(tool='tool', model='model', generated_at='2026-09-28T12:00:00+08:00')
        self.save_manifest(directory, manifest)

    def assert_fails(self, code, **options):
        result = validate_project(self.root, **options)
        self.assertTrue(result.errors, 'Expected failure, got success')
        self.assertTrue(any(code in error for error in result.errors), result.errors)

    def test_empty_workspace_passes_structure_but_cannot_pass_prompts(self):
        result = validate_project(self.root)
        self.assertEqual([], result.errors)
        self.assertEqual(0, result.work_count)
        self.assert_fails('NO_WORK', phase='prompts')

    def test_missing_required_root_file_fails(self):
        # Rename one explicitly identified file; never delete fixture files.
        (self.root / 'spec/acceptance.md').rename(self.root / 'spec/acceptance.saved')
        self.assert_fails('MISSING')

    def test_work_directory_without_manifest_fails(self):
        (self.root / '04_作品项目/001_缺失').mkdir()
        self.assert_fails('MISSING')

    def test_draft_allows_empty_shots_and_placeholders(self):
        directory, manifest = self.work()
        manifest['title'] = '{{作品标题}}'
        self.save_manifest(directory, manifest)
        self.write_rows(directory, [])
        self.assertEqual([], validate_project(self.root).errors)

    def test_archived_unfinished_work_allows_empty_shots_but_rejects_fake_pass(self):
        directory, manifest = self.work(status='ARCHIVED')
        self.write_rows(directory, [])
        self.assertEqual([], validate_project(self.root).errors)
        manifest['review']['status'] = 'PASS'
        self.save_manifest(directory, manifest)
        self.assert_fails('PASS_FIELDS')

    def test_archived_incomplete_shots_still_reject_invalid_values(self):
        directory, _ = self.work(status='ARCHIVED')
        self.write_shots(directory, shot_id='invalid', image_prompt='', duration_seconds='nan')
        self.assert_fails('SHOT_ID')
        self.assert_fails('DURATION')

    def test_required_templates_are_checked(self):
        for relative in ('01_创作模板/需求卡.md', '01_创作模板/作品模板/project.json',
                         '01_创作模板/作品模板/05_生成结果/README.md'):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                path.rename(path.with_suffix('.saved'))
        self.assert_fails('MISSING')

    def test_nested_reference_markdown_links_are_checked(self):
        directory = self.root / '03_参考素材与风格' / 'nested'
        directory.mkdir()
        (directory / 'reference.md').write_text('[missing](absent.png)', encoding='utf-8')
        self.assert_fails('LINK')

    def test_reparse_directory_is_rejected_without_reading_its_contents(self):
        directory = self.root / '02_提示词库' / 'linked'
        directory.mkdir()
        (directory / 'outside.md').write_bytes(b'\xff\xfeinvalid-utf8')
        original = validator._reparse
        with patch('validate_project._reparse', side_effect=lambda path: path == directory or original(path)):
            result = validate_project(self.root)
        self.assertTrue(any('[PATH]' in error for error in result.errors), result.errors)
        self.assertFalse(any('[READ]' in error for error in result.errors), result.errors)

    def test_real_template_can_be_filled_and_pass_prompt_gate(self):
        source = Path(__file__).resolve().parents[2] / '01_创作模板' / '作品模板'
        directory = self.root / '04_作品项目' / '001_真实模板填写'
        for relative in (*WORK_REQUIRED, '05_生成结果/README.md'):
            target = directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            text = (source / relative).read_text(encoding='utf-8-sig')
            if relative.endswith('.md') and relative != '06_修改与验收.md':
                text = re.sub(r'\{\{.*?\}\}', '测试场景：雨夜便利店的静态画面', text, flags=re.DOTALL)
            target.write_text(text, encoding='utf-8')
        manifest = json.loads((directory / 'project.json').read_text(encoding='utf-8'))
        manifest.update(title='雨夜便利店', kind='image', scope='prompts', status='PROMPT_READY')
        self.save_manifest(directory, manifest)
        self.write_shots(directory, duration_seconds='0', video_prompt='不适用')
        sent = directory / '04_生成提示词/本次发送.md'
        sent.write_text('### EP01_SH001\n\n便利店夜景，雨滴映出暖色灯光。\n', encoding='utf-8')
        result = validate_project(self.root, phase='prompts')
        self.assertEqual([], result.errors)

    def test_ready_does_not_allow_placeholder_or_empty_shots(self):
        directory, manifest = self.work(status='PROMPT_READY')
        manifest['title'] = '待确认'
        self.save_manifest(directory, manifest)
        self.write_rows(directory, [])
        self.assert_fails('PLACEHOLDER')
        self.assert_fails('SHOTS')

    def test_explicit_prompt_gate_applies_to_draft(self):
        directory, _ = self.work()
        (directory / '00_创作需求.md').write_text('TODO', encoding='utf-8')
        self.assert_fails('PLACEHOLDER', phase='prompts')

    def test_prompt_gate_allows_unperformed_items_in_review_log(self):
        directory, _ = self.work(status='PROMPT_READY')
        (directory / '06_修改与验收.md').write_text('交付审查：待确认。TODO：生成后检查。', encoding='utf-8')
        self.assertEqual([], validate_project(self.root, phase='prompts').errors)

    def test_drive_relative_markdown_link_is_rejected(self):
        (self.root / 'README.md').write_text('[outside](C:spec/acceptance.md)', encoding='utf-8')
        self.assert_fails('LINK_PATH')

    def test_duplicate_shot_id_fails_even_draft(self):
        directory, _ = self.work()
        with (directory / '03_分镜表.csv').open(encoding='utf-8', newline='') as file:
            rows = list(csv.DictReader(file))
        self.write_rows(directory, rows + rows)
        self.assert_fails('DUPLICATE_SHOT')

    def test_duplicate_work_id_fails_when_selecting_one_work(self):
        self.work()
        self.work(name='002_测试')
        self.assert_fails('DUPLICATE_ID', work='04_作品项目/001_测试')

    def test_invalid_nonempty_shot_id_fails_even_draft(self):
        directory, _ = self.work()
        self.write_shots(directory, shot_id='bad-id')
        self.assert_fails('SHOT_ID')

    def test_bad_reference_paths_fail_even_draft(self):
        directory, _ = self.work()
        for value in ('../../outside.txt', 'C:/outside.txt', '/outside.txt', r'\\server\share\file'):
            with self.subTest(value=value):
                self.write_shots(directory, reference_files=value)
                self.assert_fails('PATH')

    def test_existing_reference_must_be_nonempty(self):
        directory, _ = self.work()
        (directory / 'empty.png').write_bytes(b'')
        self.write_shots(directory, reference_files='empty.png')
        self.assert_fails('EMPTY')

    def test_nonfinite_and_nonpositive_video_durations_fail(self):
        directory, _ = self.work(kind='video')
        for value in ('nan', 'inf', '-1', '0'):
            with self.subTest(value=value):
                self.write_shots(directory, duration_seconds=value)
                self.assert_fails('DURATION')

    def test_video_prompt_is_required_at_prompt_gate(self):
        directory, _ = self.work(status='PROMPT_READY', kind='comic')
        self.write_shots(directory, video_prompt='')
        self.assert_fails('REQUIRED_VALUE')

    def test_sendable_prompts_must_include_every_shot_id(self):
        directory, _ = self.work(status='PROMPT_READY')
        (directory / '04_生成提示词/本次发送.md').write_text('缺少镜头编号', encoding='utf-8')
        self.assert_fails('SEND_SHOT')

    def test_prompts_delivery_can_pass_without_generation(self):
        directory, manifest = self.work(status='ACCEPTED')
        self.approved(directory, manifest, 'review')
        self.assertEqual([], validate_project(self.root, phase='delivery').errors)

    def test_media_delivery_requires_generation(self):
        directory, manifest = self.work(status='ACCEPTED', scope='media')
        self.approved(directory, manifest, 'review')
        self.assert_fails('GENERATION_REQUIRED', phase='delivery')

    def test_media_delivery_passes_with_current_evidence(self):
        directory, manifest = self.work(status='ACCEPTED', scope='media')
        self.approved(directory, manifest, 'review')
        self.approved(directory, manifest, 'generation')
        self.assertEqual([], validate_project(self.root, phase='delivery').errors)

    def test_generated_state_requires_media_scope_and_generation(self):
        self.work(status='GENERATED')
        self.assert_fails('GENERATED_SCOPE')
        self.assert_fails('GENERATION_REQUIRED')

    def test_fake_pass_is_rejected_even_when_archived(self):
        directory, manifest = self.work(status='ARCHIVED')
        manifest['review']['status'] = 'PASS'
        self.save_manifest(directory, manifest)
        self.assert_fails('PASS_FIELDS')

    def test_old_review_and_generation_revisions_fail(self):
        directory, manifest = self.work(status='ACCEPTED', scope='media')
        self.approved(directory, manifest, 'generation')
        self.approved(directory, manifest, 'review')
        manifest['revision'] = 'v002'
        self.save_manifest(directory, manifest)
        self.assert_fails('REVISION')

    def test_pass_date_and_evidence_are_validated(self):
        directory, manifest = self.work(status='ACCEPTED')
        self.approved(directory, manifest, 'review')
        manifest['review']['reviewed_at'] = 'yesterday'
        manifest['review']['evidence'] = ['missing.md']
        self.save_manifest(directory, manifest)
        self.assert_fails('DATE')
        self.assert_fails('MISSING')

    def test_malformed_manifest_types_return_errors_not_exceptions(self):
        directory, manifest = self.work()
        for payload in ([], None, dict(manifest, generation=[]), dict(manifest, review='PASS'),
                        dict(manifest, id=[]), dict(manifest, schema_version=True)):
            with self.subTest(payload=payload):
                self.save_manifest(directory, payload)
                self.assert_fails('SCHEMA')

    def test_duplicate_json_keys_are_rejected(self):
        directory, _ = self.work()
        (directory / 'project.json').write_text('{"id":"WORK-001","id":"WORK-002"}', encoding='utf-8')
        self.assert_fails('JSON')

    def test_link_checks_ignore_external_anchor_and_fenced_examples(self):
        (self.root / 'README.md').write_text(
            '[source](https://example.com) [anchor](#title)\n```md\n[example](missing.md)\n```\n'
            '[local](spec/acceptance.md)\n', encoding='utf-8')
        self.assertEqual([], validate_project(self.root).errors)
        (self.root / 'README.md').write_text('[broken](missing.md)', encoding='utf-8')
        self.assert_fails('LINK')

    def test_work_selection_cannot_escape_or_select_template(self):
        self.assert_fails('PATH', work='../outside')
        self.assert_fails('WORK_SELECTION', work='01_创作模板')


if __name__ == '__main__':
    unittest.main()
