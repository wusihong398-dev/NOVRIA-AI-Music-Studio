import tempfile
import unittest
from pathlib import Path

from app.server_batch_rules import (
    build_processing_plan,
    classify_source_candidate,
    finished_song_dir,
    normalize_artist_name,
    title_and_artist,
)
from tools.prepare_server_batch import discover
from app.processed_storage import DiskUsage, configured_processed_roots, select_processed_root


class ServerBatchRulesTests(unittest.TestCase):
    def test_product_storage_prefers_g_then_f_and_preserves_reserve(self):
        roots = configured_processed_roots(Path("G:/Products"), "G:/Products;F:/Products")
        usages = {
            "G:/Products": DiskUsage(1000, 860, 140),
            "F:/Products": DiskUsage(1000, 300, 700),
        }
        selected, snapshot = select_processed_root(
            roots, reserve_ratio=0.15, reserve_min_bytes=100, required_bytes=10,
            usage_provider=lambda root: usages[root.as_posix()],
        )
        self.assertEqual(selected.as_posix(), "F:/Products")
        self.assertFalse(snapshot[0]["eligible"])
        self.assertTrue(snapshot[1]["eligible"])

    def test_product_storage_returns_none_when_both_disks_reach_reserve(self):
        roots = [Path("G:/Products"), Path("F:/Products")]
        selected, snapshot = select_processed_root(
            roots, reserve_ratio=0.15, reserve_min_bytes=100, required_bytes=10,
            usage_provider=lambda _root: DiskUsage(1000, 855, 145),
        )
        self.assertIsNone(selected)
        self.assertTrue(all(not item["eligible"] for item in snapshot))

    def test_single_song_pilot_limit_is_exposed(self):
        server = (Path(__file__).resolve().parents[1] / "server" / "mobile_api.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("limit: int = 0", server)
        self.assertIn('batch_state.get("limit")', server)

    def test_artist_numbers_and_nested_album_are_normalized(self):
        root = Path("D:/MP3")
        path = root / "郑秀文(1)" / "郑秀文-1999 爱情故事" / "CD1" / "02 值得.mp3"
        title, artist = title_and_artist(path, root)
        self.assertEqual((title, artist), ("值得", "郑秀文"))
        self.assertEqual(normalize_artist_name("郑秀文 2"), "郑秀文")

    def test_filters_dj_instrument_fragment_and_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MP3"
            singer = root / "任素汐"
            singer.mkdir(parents=True)
            names = (
                "任素汐-胡广生 (DJ版).mp3",
                "任素汐-亲爱的你啊 (伴奏).mp3",
                "任素汐-亲爱的你啊 (23秒Live弹唱版片段).mp3",
                "任素汐-亲爱的你啊.mp3",
                "01 亲爱的你啊.mp3",
            )
            files = []
            for index, name in enumerate(names, start=1):
                path = singer / name
                path.write_bytes(b"x" * index)
                files.append(path)
            plan = build_processing_plan(files, root)
            counts = {}
            for item in plan:
                counts[item.action] = counts.get(item.action, 0) + 1
            self.assertEqual(counts, {"skip": 2, "review": 1, "duplicate": 1, "process": 1})

    def test_finished_library_has_no_album_layer(self):
        path = finished_song_dir(Path("G:/JuweierMusicProcessed"), "Z", "郑秀文(1)", "02 值得")
        self.assertEqual(
            path.as_posix(),
            "G:/JuweierMusicProcessed/01_Ready/Z/郑秀文/值得",
        )

    def test_recursive_scan_finds_audio_below_album_and_demo_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MP3"
            song = (
                root / "张雨生"
                / "2008 如燕盘旋而来的思念 张雨生全创作精选典藏[台湾]"
                / "张雨生-如燕盘旋而来的思念(DEMO)3"
                / "02 如燕盘旋而来的思念.mp3"
            )
            song.parent.mkdir(parents=True)
            song.write_bytes(b"audio")
            (song.parent / "cover.jpg").write_bytes(b"image")

            self.assertEqual(discover(root), [song])
            decision = classify_source_candidate(song, root)
            self.assertEqual(decision.artist, "张雨生")
            self.assertEqual(decision.title, "如燕盘旋而来的思念")
            self.assertEqual(decision.action, "review")
            self.assertIn("DEMO", decision.reason)


if __name__ == "__main__":
    unittest.main()
