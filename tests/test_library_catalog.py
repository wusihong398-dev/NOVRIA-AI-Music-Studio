import os
import tempfile
import unittest
import wave
from pathlib import Path

from app.library_catalog import (
    catalog_artist_name,
    connect_catalog,
    ensure_library_layout,
    infer_artist_from_path,
    list_catalog,
    scan_catalog,
    scan_catalog_roots,
)


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
            singer = paths["originals"] / "按歌手分类(MP3）" / "Z 字母开头歌手" / "周杰伦"
            singer.mkdir(parents=True)
            song = singer / "晴天.wav"
            with wave.open(str(song), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 800)
            partial = singer / "还没下载完.mp3.baiduyun.downloading"
            partial.write_bytes(b"partial")
            temp = paths["temp"] / "链接导入"
            temp.mkdir(parents=True, exist_ok=True)
            linked = temp / "公开歌手 - 测试分享.wav"
            with wave.open(str(linked), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\0\0" * 1200)
            working = paths["temp"] / "working" / "晴天_0123456789ab_work.wav"
            working.parent.mkdir(parents=True)
            with wave.open(str(working), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\1\0" * 900)

            db = paths["database"] / "catalog.sqlite3"
            result = scan_catalog_roots([paths["originals"], paths["temp"]], db, paths["covers"])
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["ignored_partial"], 1)
            singer_rows = list_catalog(db, "周杰伦")
            self.assertEqual(singer_rows[0]["title"], "晴天")
            self.assertEqual(catalog_artist_name(singer_rows[0]), "周杰伦")
            self.assertEqual(singer_rows[0]["source_group"], "周杰伦")
            temp_rows = list_catalog(db, "测试分享", "临时歌曲库")
            self.assertEqual(len(temp_rows), 1)

            connection = connect_catalog(db)
            connection.execute(
                "INSERT INTO tracks(fingerprint,source_path,working_path,title,artist,imported_at) VALUES(?,?,?,?,?,?)",
                ("legacy-work-row", str(working), str(working), "晴天工作副本", "working", 1),
            )
            connection.commit(); connection.close()
            cleanup = scan_catalog_roots([paths["originals"], paths["temp"]], db, paths["covers"])
            self.assertEqual(cleanup["removed_generated"], 1)
            self.assertEqual(len(list_catalog(db)), 2)

    def test_follows_linked_song_folder_and_skips_letter_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            paths = ensure_library_layout(base / "library")
            downloaded = base / "baidu_downloaded"
            singer = downloaded / "A 字母开头歌手" / "阿杜"
            singer.mkdir(parents=True)
            song = singer / "坚持到底.wav"
            with wave.open(str(song), "wb") as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(8000)
                stream.writeframes(b"\0\1" * 800)

            linked = paths["originals"] / "按歌手分类(MP3)"
            try:
                os.symlink(downloaded, linked, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"directory links are unavailable: {error}")

            self.assertEqual(infer_artist_from_path(linked / "A 字母开头歌手" / "阿杜" / song.name, paths["originals"]), "阿杜")
            db = paths["database"] / "catalog.sqlite3"
            result = scan_catalog(paths["originals"], db, paths["covers"])
            self.assertEqual(result["total"], 1)
            self.assertGreaterEqual(result["linked_folders"], 1)
            rows = list_catalog(db, "阿杜")
            self.assertEqual(len(rows), 1)
            self.assertEqual(catalog_artist_name(rows[0]), "阿杜")


if __name__ == "__main__":
    unittest.main()
