import json
import tempfile
import unittest
import wave
from pathlib import Path

from app.project_utils import (
    atomic_write_json,
    normalized_path,
    repair_text,
    safe_file_stem,
    unique_import_candidates,
)


class ProjectUtilsTests(unittest.TestCase):
    def test_safe_file_stem_preserves_chinese_and_removes_windows_chars(self):
        self.assertEqual(safe_file_stem('橘味儿:测试?.mp3'), '橘味儿_测试_.mp3')

    def test_repair_text_repairs_utf8_mojibake(self):
        broken = '橘味儿音乐'.encode('utf-8').decode('latin-1')
        self.assertEqual(repair_text(broken), '橘味儿音乐')

    def test_atomic_write_json_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            atomic_write_json(path, {'歌曲': '测试', '进度': 100})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['歌曲'], '测试')
            self.assertEqual(list(path.parent.glob('*.tmp')), [])

    def test_source_and_working_file_are_one_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / '歌曲.mp3'
            working = root / '歌曲_123_work.wav'
            source.write_bytes(b'source')
            working.write_bytes(b'working')
            database = {
                'source-fingerprint': {
                    'source': str(source),
                    'working': str(working),
                    'imported_at': 1,
                }
            }
            rows = unique_import_candidates(database, [working], lambda _: 'working-fingerprint')
            self.assertEqual(len(rows), 1)
            self.assertEqual(normalized_path(rows[0][2]), normalized_path(working))


if __name__ == '__main__':
    unittest.main()
