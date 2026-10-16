"""Bundle contracts; fixtures remain in .harness-tests (no recursive cleanup)."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    bundle = importlib.import_module('skill_bundle')
except ModuleNotFoundError:
    bundle = None


class SkillBundleTests(unittest.TestCase):
    def setUp(self):
        self.area = Path(__file__).resolve().parents[2] / '.harness-tests' / ('bundle-' + uuid4().hex)
        self.root = self.area / 'repo'
        self.target = self.area / 'installed'
        self.root.mkdir(parents=True)
        self.entries = []
        self.creator = self.skill('aigc-creator', 'orchestrator')
        self.core = self.skill('aigc-prd', 'core', ['aigc-creator'])
        self.catalog()

    def skill(self, name, group, dependencies=None):
        relative = f'skills/{name}' if group == 'orchestrator' else f'skills/core/{name}'
        directory = self.root / relative
        directory.mkdir(parents=True)
        self.write(directory / 'SKILL.md', f'---\nname: {name}\ndescription: "Create useful test materials."\n---\n\n# Test\n')
        self.entries.append(dict(name=name, path=relative, group=group, dependencies=dependencies or []))
        return directory

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding='utf-8')

    def catalog(self):
        self.write(self.root / 'skills/catalog.json', json.dumps(dict(schema_version=1, skills=self.entries)))

    def validate(self):
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        return bundle.validate_bundle(self.root)

    def install(self, **options):
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        return bundle.install_bundle(self.root, self.target, **options)

    def assert_error(self, report, code):
        self.assertTrue(any(f'[{code}]' in error for error in report.errors), report.errors)

    def test_valid_bundle_accepts_nested_resources(self):
        self.write(self.creator / 'references/guide.md', '# Guide\n')
        self.write(self.creator / 'assets/frame.bin', 'frame')
        with (self.creator / 'SKILL.md').open('a', encoding='utf-8') as handle:
            handle.write('[Guide](references/guide.md)\n![Frame](assets/frame.bin)\n')
        self.assertEqual([], self.validate().errors)

    def test_duplicate_skill_names_are_rejected(self):
        self.entries.append(dict(self.entries[0]))
        self.catalog()
        self.assert_error(self.validate(), 'NAME')

    def test_invalid_names_and_source_paths_are_rejected(self):
        for name, relative in [('Bad_Name', 'skills/Bad_Name'), ('con', 'skills/con'),
                               ('aigc-prd', '../outside/aigc-prd'), ('aigc-prd', 'C:/aigc-prd'),
                               ('aigc-prd', '/tmp/aigc-prd'), ('aigc-prd', 'skills\\aigc-prd'),
                               ('aigc-prd', 'skills/other-name')]:
            with self.subTest(name=name, path=relative):
                self.entries[1].update(name=name, path=relative)
                self.catalog()
                self.assertTrue(self.validate().errors)

    def test_missing_dependency_is_rejected(self):
        self.entries[1]['dependencies'].append('aigc-absent')
        self.catalog()
        self.assert_error(self.validate(), 'DEPENDENCY')

    def test_dependency_cycle_is_rejected(self):
        self.skill('aigc-script', 'core', ['aigc-creator', 'aigc-prd'])
        self.entries[1]['dependencies'].append('aigc-script')
        self.catalog()
        self.assert_error(self.validate(), 'CYCLE')

    def test_orchestrator_dependency_contract_is_enforced(self):
        self.entries[1]['dependencies'] = []
        self.entries[0]['dependencies'] = ['aigc-prd']
        self.catalog()
        self.assert_error(self.validate(), 'DEPENDENCY')

    def test_malformed_catalog_is_rejected(self):
        for document in ['{"schema_version":1,"schema_version":1,"skills":[]}',
                         '{"schema_version":true,"skills":[]}',
                         '{"schema_version":1,"skills":{}}',
                         '{"schema_version":1,"skills":[null]}']:
            self.write(self.root / 'skills/catalog.json', document)
            self.assert_error(self.validate(), 'CATALOG')

    def test_missing_entrypoint_is_rejected(self):
        (self.core / 'SKILL.md').rename(self.core / 'SKILL.saved')
        self.assert_error(self.validate(), 'ENTRYPOINT')

    def test_frontmatter_name_and_description_are_validated(self):
        for frontmatter in ['name: other\ndescription: useful', 'name: aigc-prd\ndescription: ""',
                            'name: aigc-prd\ndescription: [invalid]',
                            'name: aigc-prd\nname: aigc-prd\ndescription: useful']:
            self.write(self.core / 'SKILL.md', '---\n' + frontmatter + '\n---\n# Skill\n')
            self.assert_error(self.validate(), 'FRONTMATTER')

    def test_description_must_match_when_catalog_supplies_it(self):
        self.entries[1]['description'] = 'A different declared purpose.'
        self.catalog()
        self.assert_error(self.validate(), 'FRONTMATTER')

    def test_folded_description_and_quoted_colons_are_supported(self):
        self.write(self.core / 'SKILL.md', '---\nname: aigc-prd\ndescription: >-\n  Create: useful materials\n  for a creator.\n---\n# Skill\n')
        self.assertEqual([], self.validate().errors)

    def test_yaml_implicit_scalars_are_not_descriptions(self):
        for scalar in ['0x12', '.inf', '12_000', '2026-10-16', 'yes', 'off']:
            with self.subTest(scalar=scalar):
                self.write(self.core / 'SKILL.md', f'---\nname: aigc-prd\ndescription: {scalar}\n---\n# Skill\n')
                self.assert_error(self.validate(), 'FRONTMATTER')

    def test_unowned_frontmatter_indentation_is_rejected(self):
        self.write(self.core / 'SKILL.md', '---\nname: aigc-prd\ndescription: Useful text\n  invalid: indentation\n---\n# Skill\n')
        self.assert_error(self.validate(), 'FRONTMATTER')

    def test_optional_metadata_still_allows_nested_fields(self):
        self.write(self.core / 'SKILL.md', '---\nname: aigc-prd\ndescription: "Useful text"\nmetadata:\n  short-description: Useful\n---\n# Skill\n')
        self.assertEqual([], self.validate().errors)

    def test_missing_resource_link_is_rejected(self):
        self.write(self.core / 'references/broken.md', '[Need](missing.md)')
        self.assert_error(self.validate(), 'LINK')

    def test_reference_style_missing_resource_is_rejected(self):
        self.write(self.core / 'references/broken.md', '[Need][source]\n\n[source]: missing.md "A title"\n')
        self.assert_error(self.validate(), 'LINK')

    def test_code_examples_and_external_links_are_ignored(self):
        self.write(self.core / 'references/examples.md', '```markdown\n[Example](absent.md)\n```\n`[Example](absent.md)`\n[Web](https://example.com)\n[Here](#heading)\n')
        self.assertEqual([], self.validate().errors)

    def test_balanced_encoded_and_reference_links_work(self):
        self.write(self.core / 'references/a (b).md', '# A\n')
        self.write(self.core / 'references/links.md', '[One](a%20(b).md)\n[Two](<a (b).md> "Title")\n[Three][ref]\n\n[ref]: <a (b).md>\n')
        self.assertEqual([], self.validate().errors)

    def test_link_cannot_escape_its_installable_package(self):
        self.write(self.root / 'outside.md', '# Outside\n')
        self.write(self.core / 'references/broken.md', '[Outside](../../../../outside.md)')
        self.assert_error(self.validate(), 'LINK_PATH')

    def test_preview_creates_no_target_or_backups(self):
        report = self.install()
        self.assertEqual([], report.errors)
        self.assertFalse(report.applied)
        self.assertFalse(self.target.exists())
        self.assertFalse((self.area / 'installed-backups').exists())
        self.assertTrue(report.actions)

    def test_install_flattens_packages_and_preserves_resource_bytes(self):
        resource = self.core / 'assets/nested/data.bin'
        resource.parent.mkdir(parents=True)
        resource.write_bytes(b'\x00\xff\x01')
        report = self.install(apply=True)
        self.assertEqual([], report.errors)
        self.assertTrue(report.applied)
        self.assertTrue((self.target / 'aigc-prd/SKILL.md').is_file())
        self.assertEqual(b'\x00\xff\x01', (self.target / 'aigc-prd/assets/nested/data.bin').read_bytes())
        self.assertFalse((self.target / 'core').exists())

    def test_install_and_repeat_work_without_python311_file_digest(self):
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        resource = self.core / 'assets/million-a.bin'
        resource.parent.mkdir(parents=True)
        resource.write_bytes(b'a' * 1_000_000)
        with patch.dict(vars(bundle.hashlib)):
            vars(bundle.hashlib).pop('file_digest', None)
            try:
                report = self.install(apply=True)
                repeated = self.install(apply=True)
            except AttributeError as exc:
                self.fail(f'Installation must work without Python 3.11-only hashlib APIs: {exc}')
        self.assertEqual([], report.errors)
        self.assertEqual([], repeated.errors)
        action = next(item for item in report.actions if item['source'] == str(resource))
        self.assertEqual('cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0',
                         action['source_sha256'])
        self.assertEqual(b'a' * 1_000_000, (self.target / 'aigc-prd/assets/million-a.bin').read_bytes())
        self.assertTrue(all(item['action'] == 'unchanged' for item in repeated.actions))

    def test_repeat_install_is_noop_without_backup(self):
        self.assertEqual([], self.install(apply=True).errors)
        installed = self.target / 'aigc-prd/SKILL.md'
        before = installed.stat().st_mtime_ns
        report = self.install(apply=True)
        self.assertEqual([], report.errors)
        self.assertEqual(before, installed.stat().st_mtime_ns)
        self.assertIsNone(report.backup_dir)
        self.assertTrue(all(item['action'] == 'unchanged' for item in report.actions))

    def test_one_conflict_blocks_the_entire_batch(self):
        self.write(self.target / 'aigc-prd/SKILL.md', 'User edited this skill.')
        report = self.install(apply=True)
        self.assert_error(report, 'CONFLICT')
        self.assertFalse((self.target / 'aigc-creator').exists())
        self.assertEqual('User edited this skill.', (self.target / 'aigc-prd/SKILL.md').read_text(encoding='utf-8'))

    def test_update_backs_up_every_overwritten_file_outside_target(self):
        self.write(self.target / 'aigc-prd/SKILL.md', 'user prd')
        self.write(self.target / 'aigc-creator/SKILL.md', 'user creator')
        report = self.install(apply=True, update=True)
        self.assertEqual([], report.errors)
        backup = Path(report.backup_dir)
        self.assertFalse(backup.is_relative_to(self.target))
        self.assertEqual('user prd', (backup / 'aigc-prd/SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual('user creator', (backup / 'aigc-creator/SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual((self.core / 'SKILL.md').read_bytes(), (self.target / 'aigc-prd/SKILL.md').read_bytes())

    def test_update_preview_does_not_create_a_backup(self):
        self.write(self.target / 'aigc-prd/SKILL.md', 'user prd')
        report = self.install(update=True)
        self.assertEqual([], report.errors)
        self.assertFalse((self.area / 'installed-backups').exists())
        self.assertEqual('user prd', (self.target / 'aigc-prd/SKILL.md').read_text(encoding='utf-8'))

    def test_extra_target_files_are_reported_and_preserved_without_reading(self):
        self.write(self.target / 'aigc-prd/.env', 'private-content')
        self.write(self.target / 'unrelated-skill/.env', 'other-private-content')
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = Path.open

        def guarded(path, *args, **kwargs):
            if path.name == '.env':
                raise AssertionError('Unknown credential content must not be read')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', guarded):
            report = self.install(apply=True, update=True)
        self.assertEqual([], report.errors)
        self.assertIn('aigc-prd/.env', report.extras)
        self.assertEqual('private-content', (self.target / 'aigc-prd/.env').read_text(encoding='utf-8'))
        self.assertEqual('other-private-content', (self.target / 'unrelated-skill/.env').read_text(encoding='utf-8'))

    def test_directory_file_collisions_block_all_writes(self):
        (self.target / 'aigc-prd/SKILL.md').mkdir(parents=True)
        report = self.install(apply=True, update=True)
        self.assert_error(report, 'TARGET')
        self.assertFalse((self.target / 'aigc-creator').exists())

    def test_source_target_overlap_is_rejected(self):
        self.target = self.root / 'skills'
        report = self.install(apply=True, update=True)
        self.assert_error(report, 'TARGET')

    def test_reparse_source_is_rejected_before_contents_are_read(self):
        self.write(self.core / 'references/safe.md', '# Safe')
        suspicious = self.core / 'references'
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = bundle._reparse
        with patch.object(bundle, '_reparse', side_effect=lambda p: p == suspicious or original(p)):
            self.assert_error(self.validate(), 'PATH')

    def test_reparse_target_is_rejected_before_any_batch_write(self):
        self.write(self.target / 'aigc-prd/SKILL.md', 'User content')
        suspicious = self.target / 'aigc-prd'
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = bundle._reparse
        with patch.object(bundle, '_reparse', side_effect=lambda p: p == suspicious or original(p)):
            report = self.install(apply=True, update=True)
        self.assert_error(report, 'PATH')
        self.assertFalse((self.target / 'aigc-creator').exists())

    def test_reparse_target_ancestor_is_rejected(self):
        self.target.mkdir()
        suspicious = self.area
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = bundle._reparse
        with patch.object(bundle, '_reparse', side_effect=lambda p: p == suspicious or original(p)):
            self.assert_error(self.install(apply=True), 'PATH')
        self.assertEqual([], list(self.target.iterdir()))

    def test_backup_failure_prevents_any_install_write(self):
        self.write(self.target / 'aigc-prd/SKILL.md', 'user prd')
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = Path.open

        def guarded(path, *args, **kwargs):
            if 'installed-backups' in path.parts:
                raise PermissionError('Simulated backup write failure')
            return original(path, *args, **kwargs)

        with patch.object(Path, 'open', guarded):
            report = self.install(apply=True, update=True)
        self.assert_error(report, 'BACKUP')
        self.assertFalse((self.target / 'aigc-creator').exists())
        self.assertEqual('user prd', (self.target / 'aigc-prd/SKILL.md').read_text(encoding='utf-8'))

    def test_hardlinked_target_cannot_modify_another_file(self):
        outside = self.area / 'outside-user-copy.md'
        self.write(outside, 'User file outside the installation')
        linked = self.target / 'aigc-prd/SKILL.md'
        linked.parent.mkdir(parents=True)
        os.link(outside, linked)
        report = self.install(apply=True, update=True)
        self.assert_error(report, 'TARGET')
        self.assertEqual('User file outside the installation', outside.read_text(encoding='utf-8'))
        self.assertFalse((self.target / 'aigc-creator').exists())

    def test_metadata_failure_reports_the_possibly_written_target(self):
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = bundle.shutil.copystat

        def fail_metadata(source, destination, *args, **kwargs):
            if Path(destination).is_relative_to(self.target):
                raise PermissionError('Simulated metadata write failure')
            return original(source, destination, *args, **kwargs)

        with patch.object(bundle.shutil, 'copystat', side_effect=fail_metadata):
            report = self.install(apply=True)
        written_target = self.target / 'aigc-creator/SKILL.md'
        self.assert_error(report, 'WRITE')
        self.assertTrue(written_target.is_file())
        self.assertIn(str(written_target), getattr(report, 'attempted', []))
        self.assertTrue(any(str(written_target) in error for error in report.errors))
        self.assertFalse(report.applied)

    def test_nested_list_resources_are_still_validated(self):
        self.write(self.core / 'references/nested.md', '- Resources:\n    - [Need](missing.md)\n')
        self.assert_error(self.validate(), 'LINK')

    def test_multiline_reference_definition_is_validated(self):
        self.write(self.core / 'references/multiline.md', '[Need][ref]\n\n[ref]:\n  missing.md\n')
        self.assert_error(self.validate(), 'LINK')

    def test_absolute_link_remains_invalid_after_url_decoding(self):
        self.write(self.core / 'references/absolute.md', '[Outside](%2FC%3A%2Foutside.md)\n')
        self.assert_error(self.validate(), 'LINK_PATH')

    def test_reparse_backup_location_blocks_all_changes(self):
        self.write(self.target / 'aigc-prd/SKILL.md', 'user prd')
        backup = self.area / 'installed-backups'
        backup.mkdir()
        self.assertIsNotNone(bundle, 'skill_bundle implementation is missing')
        original = bundle._reparse
        with patch.object(bundle, '_reparse', side_effect=lambda p: p == backup or original(p)):
            report = self.install(apply=True, update=True)
        self.assert_error(report, 'PATH')
        self.assertFalse((self.target / 'aigc-creator').exists())
        self.assertEqual('user prd', (self.target / 'aigc-prd/SKILL.md').read_text(encoding='utf-8'))

    def test_cli_preview_and_failure_exit_codes(self):
        script = Path(__file__).resolve().parents[1] / 'skill_bundle.py'
        self.assertTrue(script.is_file(), 'skill_bundle CLI implementation is missing')
        process = subprocess.run([sys.executable, '-X', 'utf8', str(script), 'install', '--root', str(self.root), '--target', str(self.target)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(0, process.returncode, process.stderr + process.stdout)
        self.assertFalse(self.target.exists())
        self.assertIn('preview', process.stdout.lower())
        self.entries[1]['dependencies'].append('missing')
        self.catalog()
        process = subprocess.run([sys.executable, '-X', 'utf8', str(script), 'validate', '--root', str(self.root)], capture_output=True, text=True, encoding='utf-8')
        self.assertNotEqual(0, process.returncode)


if __name__ == '__main__':
    unittest.main()
