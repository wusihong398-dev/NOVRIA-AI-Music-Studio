import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopRegressionTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for relative in ('app/main.py', 'app/launcher.py', 'app/separation_worker_process.py', 'server/mobile_api.py'):
            ast.parse((ROOT / relative).read_text(encoding='utf-8'))

    def test_release_version_and_brand(self):
        launcher = (ROOT / 'app/launcher.py').read_text(encoding='utf-8')
        self.assertIn('VERSION = "3.2.1"', launcher)
        self.assertIn('DISPLAY_NAME = "橘味儿音乐"', launcher)

    def test_v3_account_community_and_soundfont_fallback(self):
        desktop = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        self.assertIn('class CommunityPage', desktop)
        self.assertIn('已跳过（未配置 SoundFont）', desktop)
        self.assertIn('/api/v1/auth/register', server)
        self.assertIn('/api/v1/community/messages', server)

    def test_g_drive_library_is_global_and_visible_before_processors(self):
        desktop = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        self.assertLess(desktop.index('G 盘歌手歌曲库'), desktop.index('批量 AI 处理器'))
        self.assertIn('全局 G 盘歌曲', desktop)
        self.assertIn('def load_library_track', desktop)
        self.assertIn('self.main.load_library_track(tid)', desktop)
        self.assertIn('加入当前 G 盘歌曲', desktop)

    def test_done_handlers_do_not_destroy_running_qthreads(self):
        source = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        methods = {
            node.name: ast.get_source_segment(source, node) or ''
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertNotIn('self.batch_worker=None', methods['_on_batch_song_done'])
        self.assertNotIn('self.batch_worker=None', methods['_on_batch_song_failed'])
        self.assertNotIn('self.pipeline_batch_worker=None', methods['_pipeline_stems_done'])


if __name__ == '__main__':
    unittest.main()
