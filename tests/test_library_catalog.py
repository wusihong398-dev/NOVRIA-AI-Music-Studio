import tempfile
import unittest
import wave
from pathlib import Path

from app.library_catalog import ensure_library_layout, list_catalog, scan_catalog


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


if __name__ == "__main__":
    unittest.main()
