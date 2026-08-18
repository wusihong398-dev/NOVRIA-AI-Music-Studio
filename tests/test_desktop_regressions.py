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
        self.assertIn('VERSION = "3.2.2"', launcher)
        self.assertIn('DISPLAY_NAME = "橘味儿音乐"', launcher)

    def test_sidebar_pages_are_real_and_server_library_isolated(self):
        desktop = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        server = (ROOT / "server" / "mobile_api.py").read_text(encoding="utf-8")
        self.assertIn("class WorksCenterPage", desktop)
        self.assertIn("self.stack.addWidget(self.works_center)", desktop)
        self.assertNotIn('Placeholder("作品中心', desktop)
        self.assertIn(r'G:\JuweierMusicLibrary\01_Originals\按歌手分类(MP3）', server)
        self.assertIn('"source_scope": "server"', server)

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
        self.assertIn('def load_server_library_track', desktop)
        self.assertIn('self.main.load_server_library_track(tid, row)', desktop)
        self.assertIn('本次未读取、未扫描客户端 G 盘', desktop)
        self.assertIn('ServerLibraryClient', desktop)
        self.assertIn('加入当前 G 盘歌曲', desktop)

    def test_server_scores_share_one_synced_lyrics_timeline(self):
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        mobile = (ROOT / 'mobile/lib/main.dart').read_text(encoding='utf-8')
        self.assertIn('transcribe_synced_lyrics', server)
        self.assertIn('lyrics_timeline.json', server)
        self.assertIn('electric_guitar_tab', server)
        self.assertIn('acoustic_guitar_tab', server)
        self.assertIn("lyrics_message", mobile)

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
