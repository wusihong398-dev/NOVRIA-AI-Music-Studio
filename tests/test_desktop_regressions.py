import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DesktopRegressionTests(unittest.TestCase):
    def test_python_sources_parse(self):
        for relative in ('app/main.py', 'app/launcher.py', 'app/separation_worker_process.py', 'app/uvr_separator.py', 'server/mobile_api.py'):
            ast.parse((ROOT / relative).read_text(encoding='utf-8'))

    def test_release_version_and_brand(self):
        launcher = (ROOT / 'app/launcher.py').read_text(encoding='utf-8')
        mobile_manifest = (ROOT / 'mobile/pubspec.yaml').read_text(encoding='utf-8')
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        self.assertIn('VERSION = "3.3.0"', launcher)
        self.assertIn('version: 3.3.0+330', mobile_manifest)
        self.assertIn('VERSION = "3.3.0"', server)
        self.assertIn('DISPLAY_NAME = "橘味儿音乐"', launcher)

    def test_sidebar_pages_are_real_and_server_library_isolated(self):
        desktop = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        server = (ROOT / "server" / "mobile_api.py").read_text(encoding="utf-8")
        self.assertIn("class WorksCenterPage", desktop)
        self.assertIn("self.stack.addWidget(self.works_center)", desktop)
        self.assertNotIn('Placeholder("作品中心', desktop)
        self.assertIn(r'G:\JuweierMusicLibrary\01_Originals', server)
        self.assertIn('"source_scope": "server"', server)

    def test_v3_account_community_and_soundfont_fallback(self):
        desktop = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        self.assertIn('class CommunityPage', desktop)
        self.assertIn('已跳过（未配置 SoundFont）', desktop)
        self.assertIn('/api/v1/auth/register', server)
        self.assertIn('/api/v1/community/messages', server)
        self.assertIn('/api/v1/auth/sms/send', server)
        self.assertIn('/api/v1/auth/password/reset', server)
        self.assertIn('ALIBABA_CLOUD_ACCESS_KEY_ID', server)
        self.assertNotIn('LTAI', server)

    def test_library_job_routes_stay_inside_cloudflare_library_route(self):
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        mobile = (ROOT / 'mobile/lib/main.dart').read_text(encoding='utf-8')
        self.assertIn('/api/v1/library/mobile/jobs/{job_id}', server)
        self.assertIn('/api/v1/library/mobile/artifacts/{job_id}/{name}', server)
        self.assertIn('/api/v1/library/mobile/health', server)
        self.assertIn("'/api/v1/library/mobile/jobs/$id'", mobile)
        self.assertIn('/api/v1/library/mobile/catalog', server)
        self.assertIn("'/api/v1/library/mobile/catalog", mobile)

    def test_processing_runtime_is_checked_before_accepting_expensive_work(self):
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        mobile = (ROOT / 'mobile/lib/main.dart').read_text(encoding='utf-8')
        self.assertIn('def _runtime_capabilities()', server)
        self.assertIn('def _require_processing_runtime()', server)
        self.assertIn('lyrics_asr_available', server)
        self.assertIn('检查 AI 处理环境', server)
        self.assertIn('定位服务器歌曲', mobile)
        self.assertIn('提交 AI 处理任务', mobile)
        self.assertIn('服务器未安装 AI 分轨运行环境', mobile)

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
        self.assertIn('lyric_units', server)
        self.assertIn('lyricUnits', mobile)

    def test_mobile_can_be_tested_before_sms_and_uses_cached_catalog(self):
        mobile = (ROOT / 'mobile/lib/main.dart').read_text(encoding='utf-8')
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        self.assertIn('enterGuestTesting', mobile)
        self.assertIn('先进入测试（无需验证码）', mobile)
        self.assertIn('_catalogKey', mobile)
        self.assertIn('AUTO_SCAN_LIBRARY', server)
        self.assertIn('_background_catalog_scan', server)
        self.assertIn('artist_initial', server)

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

    def test_v328_mobile_upload_and_route_fallbacks(self):
        mobile = (ROOT / 'mobile/lib/main.dart').read_text(encoding='utf-8')
        server = (ROOT / 'server/mobile_api.py').read_text(encoding='utf-8')
        self.assertIn("field('original_filename', job.fileName)", mobile)
        self.assertIn('filename="${_asciiUploadName(job.fileName)}"', mobile)
        self.assertNotIn('filename="${_safeHeader(job.fileName)}"', mobile)
        self.assertIn("'/api/v1/library/catalog?$params'", mobile)
        self.assertIn("'/api/v1/library?$params'", mobile)
        self.assertIn('original_filename: str = Form("")', server)
        self.assertIn('@app.post("/api/v1/library/jobs", status_code=202)', server)
        self.assertIn("if (job.status == '失败')", mobile)
        self.assertIn("job.serverJobId = '';", mobile)
        self.assertIn('Future<void> removeJob(PipelineJob job)', mobile)
        self.assertIn('Future<void> clearFinishedJobs()', mobile)
        self.assertIn("label: const Text('删除')", mobile)
        self.assertIn("label: const Text('清理')", mobile)

    def test_windows_catalog_is_async_lazy_and_letters_are_visible(self):
        desktop = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        self.assertIn('class ServerCatalogWorker(QThread)', desktop)
        self.assertIn('self.tree.itemExpanded.connect(self._populate_artist_children)', desktop)
        self.assertIn('["展开后加载歌曲",""]', desktop)
        self.assertIn('button.setFixedWidth(50 if value == "全部" else 36)', desktop)
        self.assertNotIn('ai.setExpanded(bool(query.strip()))', desktop)

    def test_v330_catalog_is_cached_incremental_and_never_scans_on_app_start(self):
        desktop = (ROOT / "app/main.py").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile/lib/main.dart").read_text(encoding="utf-8")
        server = (ROOT / "server/mobile_api.py").read_text(encoding="utf-8")
        self.assertIn("catalogVersion", mobile)
        self.assertIn("result['not_modified'] == true", mobile)
        self.assertIn('since and since == current_version', server)
        self.assertIn('JUWEIER_AUTO_SCAN_LIBRARY", "1"', server)
        self.assertIn('_catalog_watch_loop', server)
        self.assertIn("先显示本地缓存，再后台同步增量索引", desktop)
        self.assertNotIn("把歌曲放进 G:", mobile)
        desktop_client = (ROOT / "app/server_library_client.py").read_text(encoding="utf-8")
        self.assertIn('http://127.0.0.1:8001', desktop_client)

    def test_v330_requires_electric_guitar_and_note_aligned_lyrics_for_ready_results(self):
        server = (ROOT / "server/mobile_api.py").read_text(encoding="utf-8")
        uvr = (ROOT / "app/uvr_separator.py").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile/lib/main.dart").read_text(encoding="utf-8")
        self.assertIn('"stem_electric_guitar"', server)
        self.assertIn('"lyrics_note_aligned": lyric_aligned', server)
        self.assertIn('二阶段电吉他识别没有生成有效', uvr)
        self.assertIn("positionSeconds >= noteStart", mobile)
        self.assertIn("positionSeconds >= ((unit['start']", mobile)

    def test_uvr_engine_electric_guitar_and_lyrics_toggle(self):
        desktop = (ROOT / 'app/main.py').read_text(encoding='utf-8')
        uvr = (ROOT / 'app/uvr_separator.py').read_text(encoding='utf-8')
        server_requirements = (ROOT / 'requirements-server.txt').read_text(encoding='utf-8')
        build_requirements = (ROOT / 'requirements-build.txt').read_text(encoding='utf-8')
        self.assertIn('from audio_separator.separator import Separator', uvr)
        self.assertIn('htdemucs_6s.yaml', uvr)
        self.assertIn('electric_guitar.wav', (ROOT / 'app/project_utils.py').read_text(encoding='utf-8'))
        self.assertIn('audio-separator>=0.44.5', server_requirements)
        self.assertIn('onnxruntime>=1.17', server_requirements)
        self.assertIn('onnxruntime>=1.17', build_requirements)
        self.assertIn('matplotlib>=3.8', build_requirements)
        self.assertIn('_seed_offline_uvr_catalog', uvr)
        self.assertIn('demucs/htdemucs_6s-offline-fallback', uvr)
        self.assertIn('guitar_combined.part.wav', (ROOT / 'app/project_utils.py').read_text(encoding='utf-8'))
        self.assertIn('QCheckBox("显示歌词")', desktop)
        self.assertIn('score/show_lyrics', desktop)
        self.assertIn('lyrics_url', desktop)

    def test_actions_do_not_create_nested_delivery_archives(self):
        mobile_workflow = (ROOT / '.github/workflows/build-mobile.yml').read_text(encoding='utf-8')
        ios_workflow = (ROOT / '.github/workflows/build-ios-testflight-package.yml').read_text(encoding='utf-8')
        windows_workflow = (ROOT / '.github/workflows/build-windows-exe.yml').read_text(encoding='utf-8')
        self.assertNotIn('Juweier-Music-v3.2.8-iOS-Simulator.zip', mobile_workflow)
        self.assertNotIn('Juweier-Music-v3.2.8-iOS-TestFlight-Xcode-Project.zip', ios_workflow)
        self.assertNotIn('Compress-Archive', windows_workflow)

    def test_frozen_worker_is_verified_in_windows_ci(self):
        worker = (ROOT / 'app/separation_worker_process.py').read_text(encoding='utf-8')
        spec = (ROOT / 'NOVRIA.spec').read_text(encoding='utf-8')
        workflow = (ROOT / '.github/workflows/build-windows-exe.yml').read_text(encoding='utf-8')
        self.assertIn('--self-test', worker)
        self.assertIn("('audio-separator', 'demucs')", spec.replace('"', "'"))
        self.assertIn('copy_metadata(distribution', spec)
        self.assertIn('& $worker --self-test', workflow)


if __name__ == '__main__':
    unittest.main()
