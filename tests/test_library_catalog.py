import tempfile
import unittest
import wave
from pathlib import Path

from app.library_catalog import ensure_library_layout, list_catalog, scan_catalog, scan_catalog_roots


class LibraryCatalogTests(unittest.TestCase):
    def test_scan_search_and_categories(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_library_layout(Path(tmp))
            folder = paths["originals"] / "抖音流行"
            folder.mkdir()
            song = folder / "测试歌手 - 测试歌曲.wav"
            with wave.open(str(song), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 800)

            db = paths["database"] / "catalog.sqlite3"
            result = scan_catalog(paths["originals"], db, paths["covers"])
            self.assertEqual(result["added"], 1)
            rows = list_catalog(db, "测试歌手", "抖音流行")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "测试歌曲")
            self.assertEqual(rows[0]["artist"], "测试歌手")

    def test_scans_nested_singer_folders_and_temp_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_library_layout(Path(tmp))
            singer = paths["originals"] / "按歌手分类(MP3）" / "周杰伦"
            singer.mkdir(parents=True)
            song = singer / "晴天.wav"
            with wave.open(str(song), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 800)
            partial = singer / "还没下载完.mp3.baiduyun.downloading"
            partial.write_bytes(b"partial")
            temp = paths["temp"] / "链接导入"
            temp.mkdir(parents=True)
            linked = temp / "公开歌手 - 测试分享.wav"
            with wave.open(str(linked), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 1200)

            db = paths["database"] / "catalog.sqlite3"
            result = scan_catalog_roots([paths["originals"], paths["temp"]], db, paths["covers"])
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["ignored_partial"], 1)
            singer_rows = list_catalog(db, "周杰伦")
            self.assertEqual(singer_rows[0]["title"], "晴天")
            self.assertEqual(singer_rows[0]["artist"], "周杰伦")
            temp_rows = list_catalog(db, "测试分享", "临时歌曲库")
            self.assertEqual(len(temp_rows), 1)


if __name__ == "__main__":
    unittest.main()
