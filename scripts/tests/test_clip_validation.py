"""Clip/Shot contract tests; temporary fixtures remain under .harness-tests."""
import copy
import csv
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_project as validator


class ClipValidationTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[2] / '.harness-tests' / uuid4().hex
        for relative in validator.ROOT_REQUIRED:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('测试文档。\n', encoding='utf-8')
        self.work = self.root / '04_作品项目/001_Clip测试'
        for relative in validator.WORK_REQUIRED:
            path = self.work / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('完整设计。\n', encoding='utf-8')
        self.manifest = dict(
            schema_version=1, id='WORK-001', title='双人对话', revision='v001',
            kind='video', scope='prompts', status='PROMPT_READY', prompt_layout='clips',
            clips_file='04_生成提示词/clips.json',
            generation=dict(status='NOT_RUN', tool='', model='', generated_at='', revision='', evidence=[]),
            review=dict(status='NOT_RUN', reviewer='', reviewed_at='', revision='', evidence=[]))
        self.rows = [self.shot('EP01_SH001', 3), self.shot('EP01_SH002', 5)]
        self.payload = dict(schema_version=1, revision='v001', clips=[dict(
            clip_id='EP01_CL001', duration_seconds=8, entry_mode='text_to_video', references=[],
            segments=[self.segment('EP01_SH001', 0, 3, 0, 3),
                      self.segment('EP01_SH002', 0, 5, 3, 8)])])
        self.sent = '### EP01_CL001\n\n```text\n两人同框。切至右侧人物近景，她抬头回答。\n```\n'
        self.save()

    @staticmethod
    def shot(identity, duration):
        return dict(shot_id=identity, duration_seconds=str(duration), scene_id='SCENE-001',
                    character_ids='', description='相机固定，主体抬头，室内柔光。', dialogue='',
                    image_prompt='', video_prompt='', reference_files='')

    @staticmethod
    def segment(shot, start, end, clip_start, clip_end):
        return dict(shot_id=shot, shot_start_seconds=start, shot_end_seconds=end,
                    clip_start_seconds=clip_start, clip_end_seconds=clip_end)

    def save(self):
        (self.work / 'project.json').write_text(json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')
        with (self.work / '03_分镜表.csv').open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=validator.CSV_FIELDS)
            writer.writeheader()
            writer.writerows(self.rows)
        (self.work / '04_生成提示词/clips.json').write_text(json.dumps(self.payload, ensure_ascii=False), encoding='utf-8')
        (self.work / '04_生成提示词/本次发送.md').write_text(self.sent, encoding='utf-8')

    def result(self):
        self.save()
        return validator.validate_project(self.root)

    def assert_error(self, code):
        errors = self.result().errors
        self.assertTrue(any(f'[{code}]' in error for error in errors), errors)

    def reference(self, role, label='@Image1', filename='references/character.png'):
        target = self.work / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b'image fixture; media validity is reviewed separately')
        return dict(label=label, role=role, file=filename)

    def test_multishot_clip_passes_without_duplicate_per_shot_prompts(self):
        self.assertEqual([], self.result().errors)

    def test_one_shot_can_continue_across_two_clips(self):
        self.rows = [self.shot('EP01_SH001', 8)]
        first = self.payload['clips'][0]
        first.update(duration_seconds=3, segments=[self.segment('EP01_SH001', 0, 3, 0, 3)])
        self.payload['clips'].append(dict(first, clip_id='EP01_CL002', duration_seconds=5,
                                         segments=[self.segment('EP01_SH001', 3, 8, 0, 5)]))
        self.sent += '\n### EP01_CL002\n\n承接动作，人物站稳。\n'
        self.assertEqual([], self.result().errors)

    def test_legacy_per_shot_default_remains_valid(self):
        self.manifest.pop('prompt_layout')
        self.manifest.pop('clips_file')
        for row in self.rows:
            row.update(image_prompt='静态起点。', video_prompt='完整动作。')
        self.sent = '### EP01_SH001\n\n第一镜。\n\n### EP01_SH002\n\n第二镜。\n'
        self.assertEqual([], self.result().errors)

    def test_explicit_legacy_layout_still_requires_shot_prompts(self):
        self.manifest['prompt_layout'] = 'per_shot'
        self.manifest.pop('clips_file')
        self.assert_error('REQUIRED_VALUE')

    def test_manifest_layout_and_type_are_validated(self):
        for value in ('typo', [], None):
            with self.subTest(value=value):
                self.manifest['prompt_layout'] = value
                self.assert_error('SCHEMA')
        self.manifest['prompt_layout'] = 'clips'
        self.manifest['kind'] = 'image'
        self.assert_error('SCHEMA')

    def test_clip_identity_duplicate_and_revision_are_validated_even_draft(self):
        self.manifest['status'] = 'DRAFT'
        original = copy.deepcopy(self.payload)
        self.payload['clips'].append(copy.deepcopy(self.payload['clips'][0]))
        self.assert_error('DUPLICATE_CLIP')
        self.payload = copy.deepcopy(original)
        self.payload['clips'][0]['clip_id'] = 'bad'
        self.assert_error('CLIP_ID')
        self.payload = copy.deepcopy(original)
        self.payload['revision'] = 'v002'
        self.assert_error('REVISION')

    def test_clip_and_segment_numeric_fields_reject_invalid_values(self):
        original = copy.deepcopy(self.payload)
        for field in ('duration_seconds', 'shot_start_seconds', 'shot_end_seconds',
                      'clip_start_seconds', 'clip_end_seconds'):
            for value in (True, '2', -1, float('inf'), float('nan'), 10 ** 1000):
                with self.subTest(field=field, value=str(value)[:30]):
                    self.payload = copy.deepcopy(original)
                    target = self.payload['clips'][0]
                    if field != 'duration_seconds':
                        target = target['segments'][0]
                    target[field] = value
                    errors = self.result().errors
                    self.assertTrue(any('[CLIP_TIME]' in e or '[JSON]' in e for e in errors), errors)

    def test_clip_gap_overlap_and_incorrect_duration_fail(self):
        original = copy.deepcopy(self.payload)
        for start, end in ((4, 9), (2, 7), (3, 7)):
            with self.subTest(start=start, end=end):
                self.payload = copy.deepcopy(original)
                self.payload['clips'][0]['segments'][1].update(clip_start_seconds=start, clip_end_seconds=end)
                self.assert_error('CLIP_TIME')

    def test_shot_mapping_rejects_unknown_missing_overlap_and_overrun(self):
        original = copy.deepcopy(self.payload)
        for change in (dict(shot_id='EP01_SH999'), dict(shot_start_seconds=1),
                       dict(shot_end_seconds=6)):
            with self.subTest(change=change):
                self.payload = copy.deepcopy(original)
                self.payload['clips'][0]['segments'][1].update(change)
                self.assert_error('CLIP_MAPPING')
        self.payload = copy.deepcopy(original)
        first = self.payload['clips'][0]
        self.payload['clips'].append(dict(first, clip_id='EP01_CL002'))
        self.sent += '\n### EP01_CL002\n\n重复了整段。\n'
        self.assert_error('CLIP_MAPPING')

    def test_valid_reference_and_frame_routes_pass(self):
        clip = self.payload['clips'][0]
        for mode, roles in (('reference_to_video', ['identity']), ('reference_to_video', ['scene']),
                            ('first_frame', ['first_frame']),
                            ('first_last_frames', ['first_frame', 'last_frame'])):
            with self.subTest(mode=mode, roles=roles):
                clip['entry_mode'] = mode
                clip['references'] = [self.reference(role, f'@Image{i}', f'references/image{i}.png')
                                      for i, role in enumerate(roles, 1)]
                self.assertEqual([], self.result().errors)

    def test_input_route_requires_the_right_reference_roles_at_gate(self):
        clip = self.payload['clips'][0]
        for mode in ('reference_to_video', 'first_frame', 'first_last_frames'):
            with self.subTest(mode=mode):
                clip.update(entry_mode=mode, references=[])
                self.assert_error('CLIP_REFERENCE')
        clip.update(entry_mode='reference_to_video', references=[self.reference('audio', filename='voice.wav')])
        self.assert_error('CLIP_REFERENCE')

    def test_reference_files_labels_and_roles_are_checked(self):
        clip = self.payload['clips'][0]
        clip['entry_mode'] = 'reference_to_video'
        original = self.reference('identity')
        clip['references'] = [original]
        self.assertEqual([], self.result().errors)
        for change in (dict(role='typo'), dict(label=''), dict(file='missing.png'),
                       dict(file='../outside.png'), dict(file='C:/outside.png'), dict(file='C:outside.png')):
            with self.subTest(change=change):
                clip['references'] = [dict(original, **change)]
                self.assertTrue(self.result().errors)
        clip['references'] = [original, dict(original, role='scene')]
        self.assert_error('CLIP_REFERENCE')
        empty = self.work / 'empty.png'
        empty.write_bytes(b'')
        clip['references'] = [dict(original, file='empty.png')]
        self.assert_error('EMPTY')
        text = self.work / 'not-image.txt'
        text.write_text('不能作为身份图。', encoding='utf-8')
        clip['references'] = [dict(original, file='not-image.txt')]
        self.assert_error('CLIP_REFERENCE')

    def test_reference_reparse_path_is_rejected_before_reading(self):
        reference = self.reference('identity')
        self.payload['clips'][0]['references'] = [reference]
        original = validator._reparse
        target = self.work / reference['file']
        with patch('validate_project._reparse', side_effect=lambda path: path == target or original(path)):
            self.assert_error('PATH')

    def test_clip_document_duplicate_json_keys_and_malformed_objects_fail(self):
        for text in ('{"schema_version":1,"schema_version":1}', '[]', 'null'):
            with self.subTest(text=text):
                self.save()
                (self.work / '04_生成提示词/clips.json').write_text(text, encoding='utf-8')
                errors = validator.validate_project(self.root).errors
                self.assertTrue(any('[JSON]' in e or '[CLIP_SCHEMA]' in e for e in errors), errors)
        original = copy.deepcopy(self.payload)
        for change in (dict(schema_version=True), dict(clips={}), dict(clips=[None]),
                       dict(clips=[dict(original['clips'][0], segments={})]),
                       dict(clips=[dict(original['clips'][0], references='image.png')])):
            with self.subTest(change=change):
                self.payload = dict(original, **change)
                self.assert_error('CLIP_SCHEMA')

    def test_clip_file_paths_are_safe_and_file_is_required_at_gate(self):
        for path in ('../outside.json', 'C:/outside.json', 'C:outside.json', 'missing.json'):
            with self.subTest(path=path):
                self.manifest['clips_file'] = path
                self.assertTrue(self.result().errors)

    def test_clip_sending_requires_nonempty_unique_and_exact_headings(self):
        valid = self.sent
        for content, code in (
                ('### EP01_CL001\n\n```text\n \n```\n', 'SEND_EMPTY'),
                ('正文提到 EP01_CL001，缺标题。', 'SEND_CLIP'),
                ('```text\n### EP01_CL001\n完整内容。\n```\n', 'SEND_CLIP'),
                (valid + valid, 'SEND_DUPLICATE'),
                (valid + '\n### EP01_CL002\n\n多余内容。\n', 'SEND_EXTRA'),
                ('### EP01_CL001 EP01_CL002\n\n正文。\n', 'SEND_CLIP'),
                ('### EP01_CL001\n\n```text\n未闭合。', 'SEND_FENCE')):
            with self.subTest(code=code, content=content):
                self.sent = content
                self.assert_error(code)

    def test_draft_allows_incomplete_plan_but_checks_filled_values_and_paths(self):
        self.manifest['status'] = 'DRAFT'
        self.payload['clips'] = [dict(clip_id='EP01_CL001', duration_seconds='',
                                      entry_mode='', references=[], segments=[])]
        self.sent = '\n'  # Required document exists; its unfinished body is allowed in DRAFT.
        self.assertEqual([], self.result().errors)
        self.payload['clips'][0]['duration_seconds'] = True
        self.assert_error('CLIP_TIME')
        self.payload['clips'][0]['duration_seconds'] = ''
        self.payload['clips'][0]['references'] = [dict(label='@Image1', role='identity', file='../unsafe.png')]
        self.assert_error('PATH')

    def test_draft_allows_absent_optional_clip_file_but_not_unsafe_path(self):
        self.manifest['status'] = 'DRAFT'
        self.manifest['clips_file'] = '04_生成提示词/planned-clips.json'
        self.assertEqual([], self.result().errors)
        self.manifest['clips_file'] = '../unsafe.json'
        self.assert_error('PATH')

    def test_clip_layout_keeps_required_shot_description_and_duration(self):
        self.rows[0]['description'] = ''
        self.assert_error('REQUIRED_VALUE')
        self.rows[0]['description'] = '完整画面。'
        self.rows[0]['duration_seconds'] = 'nan'
        self.assert_error('DURATION')

    def test_missing_clip_and_shot_coverage_fails_at_gate(self):
        self.payload['clips'] = []
        self.assert_error('CLIP_SCHEMA')
        self.assert_error('CLIP_MAPPING')

    def test_missing_clip_fields_fail_at_gate(self):
        original = copy.deepcopy(self.payload)
        for key in ('clip_id', 'duration_seconds', 'entry_mode', 'segments'):
            with self.subTest(key=key):
                self.payload = copy.deepcopy(original)
                self.payload['clips'][0].pop(key)
                self.assertTrue(self.result().errors)

    def test_first_last_frames_does_not_accept_identity_as_last_frame(self):
        self.payload['clips'][0].update(entry_mode='first_last_frames', references=[
            self.reference('first_frame', '@Image1', 'first.png'),
            self.reference('identity', '@Image2', 'identity.png')])
        self.assert_error('CLIP_REFERENCE')

    def test_default_clip_path_is_used_when_omitted(self):
        self.manifest.pop('clips_file')
        self.assertEqual([], self.result().errors)

    def test_clip_file_reparse_is_rejected_before_loading(self):
        self.save()
        target = self.work / '04_生成提示词/clips.json'
        original = validator._reparse
        with patch('validate_project._reparse', side_effect=lambda path: path == target or original(path)):
            errors = validator.validate_project(self.root).errors
        self.assertTrue(any('[PATH]' in error for error in errors), errors)

    def test_clips_send_file_rejects_mixed_shot_headings(self):
        self.sent += '\n### EP01_SH001\n\n混入逐镜发送内容。\n'
        self.assert_error('SEND_CLIP')

    def test_declared_text_input_cannot_silently_require_uploaded_reference(self):
        self.payload['clips'][0]['references'] = [self.reference('identity')]
        self.assert_error('CLIP_REFERENCE')

    def test_tiny_shot_cannot_disappear_inside_numeric_tolerance(self):
        self.rows[1]['duration_seconds'] = '0.0000005'
        self.payload['clips'][0].update(duration_seconds=3,
                                       segments=[self.segment('EP01_SH001', 0, 3, 0, 3)])
        self.assert_error('CLIP_MAPPING')

    def test_incomplete_draft_mapping_still_checks_known_interval_bounds(self):
        self.manifest['status'] = 'DRAFT'
        segment = self.payload['clips'][0]['segments'][1]
        segment.update(shot_start_seconds='', shot_end_seconds='', clip_end_seconds=9)
        self.assert_error('CLIP_TIME')
        segment.update(shot_start_seconds=0, shot_end_seconds=6,
                       clip_start_seconds='', clip_end_seconds='')
        self.assert_error('CLIP_MAPPING')

    def test_incomplete_draft_mapping_checks_start_beyond_duration(self):
        self.manifest['status'] = 'DRAFT'
        segment = self.payload['clips'][0]['segments'][1]
        segment.update(shot_start_seconds='', shot_end_seconds='',
                       clip_start_seconds=9, clip_end_seconds='')
        self.assert_error('CLIP_TIME')
        segment.update(shot_start_seconds=6, shot_end_seconds='', clip_start_seconds='')
        self.assert_error('CLIP_MAPPING')

    def test_draft_rejects_later_partial_clip_start_inside_preceding_interval(self):
        self.manifest['status'] = 'DRAFT'
        self.payload['clips'][0]['segments'][1].update(clip_start_seconds=2, clip_end_seconds='')
        self.assert_error('CLIP_TIME')

    def test_draft_rejects_earlier_partial_clip_end_after_next_start(self):
        self.manifest['status'] = 'DRAFT'
        self.payload['clips'][0]['segments'][0].update(clip_start_seconds='', clip_end_seconds=4)
        self.assert_error('CLIP_TIME')

    def test_draft_rejects_partial_shot_interval_overlapping_complete_interval(self):
        self.manifest['status'] = 'DRAFT'
        self.rows = [self.shot('EP01_SH001', 8)]
        self.payload['clips'][0]['segments'][1].update(
            shot_id='EP01_SH001', shot_start_seconds=2, shot_end_seconds='')
        self.assert_error('CLIP_MAPPING')

    def test_draft_allows_partial_intervals_that_can_still_be_disjoint(self):
        self.manifest['status'] = 'DRAFT'
        original = copy.deepcopy(self.payload)
        for index, changes in (
                (1, dict(clip_start_seconds=3, clip_end_seconds='')),
                (0, dict(clip_start_seconds='', clip_end_seconds=3))):
            with self.subTest(index=index, changes=changes):
                self.payload = copy.deepcopy(original)
                self.payload['clips'][0]['segments'][index].update(changes)
                self.assertEqual([], self.result().errors)
        self.rows = [self.shot('EP01_SH001', 8)]
        for first, second in (((0, 3), (3, '')), (('', 3), (3, 8)),
                              ((0, 3), ('', 8)), ((0, ''), (3, 8))):
            with self.subTest(first=first, second=second):
                self.payload = copy.deepcopy(original)
                self.payload['clips'][0]['segments'] = [
                    self.segment('EP01_SH001', *first, 0, 3),
                    self.segment('EP01_SH001', *second, 3, 8)]
                self.assertEqual([], self.result().errors)


if __name__ == '__main__':
    unittest.main()
