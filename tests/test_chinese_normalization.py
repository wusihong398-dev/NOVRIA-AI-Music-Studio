import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.chinese_normalization import (
    simplified_relative_path,
    simplify_published_tree,
    to_simplified,
)
from app.library_catalog import connect_catalog
from tools.migrate_ready_library_simplified import migrate


class _FakeOpenCC:
    def convert(self, value: str) -> str:
        return (
            value.replace("無賴", "无赖").replace("練習", "练习")
            .replace("風", "风").replace("鄭", "郑")
        )


class ChineseNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.converter = patch("app.chinese_normalization._opencc", return_value=_FakeOpenCC())
        self.converter.start()

    def tearDown(self):
        self.converter.stop()

    def test_visible_names_are_simplified(self):
        self.assertEqual(to_simplified("無賴"), "无赖")
        self.assertEqual(
            simplified_relative_path(Path("stems") / "01 無賴" / "electric_guitar.wav"),
            Path("stems") / "01 无赖" / "electric_guitar.wav",
        )

    def test_tree_content_and_names_convert_but_source_pointer_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / "無賴"
            folder.mkdir()
            payload = {
                "title": "無賴",
                "lyrics": "風中練習",
                "source_path": r"D:\MP3\鄭中基\01 無賴.mp3",
            }
            (folder / "lyrics_timeline.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8",
            )

            simplify_published_tree(root)

            converted = root / "无赖" / "lyrics_timeline.json"
            self.assertTrue(converted.is_file())
            result = json.loads(converted.read_text(encoding="utf-8"))
            self.assertEqual(result["title"], "无赖")
            self.assertEqual(result["lyrics"], "风中练习")
            self.assertEqual(result["source_path"], payload["source_path"])

    def test_server_declares_opencc_dependency(self):
        requirements = (Path(__file__).resolve().parents[1] / "requirements-server.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("opencc-python-reimplemented", requirements)

    def test_existing_ready_product_and_catalog_are_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / "database" / "catalog.sqlite3"
            connection = connect_catalog(database)
            connection.execute(
                """INSERT INTO tracks(
                    fingerprint,source_path,title,artist,source_group,artist_initial,
                    publish_status,processing_status,final_audio_path,artifacts_json
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    "fingerprint", r"D:\MP3\鄭中基\01 無賴.mp3", "無賴", "鄭中基",
                    "鄭中基", "Z", "已发布", "已完成",
                    str(root / "01_Ready" / "Z" / "鄭中基" / "無賴" / "audio" / "original.mp3"),
                    json.dumps({"title": "無賴"}, ensure_ascii=False),
                ),
            )
            connection.commit()
            connection.close()
            product = root / "01_Ready" / "Z" / "鄭中基" / "無賴"
            product.mkdir(parents=True)
            (product / "lead_sheet.html").write_text("風中的無賴", encoding="utf-8")

            result = migrate(database, root, True)

            self.assertEqual(result["published_tracks"], 1)
            converted = root / "01_Ready" / "Z" / "郑中基" / "无赖" / "lead_sheet.html"
            self.assertEqual(converted.read_text(encoding="utf-8"), "风中的无赖")
            connection = connect_catalog(database)
            row = connection.execute("SELECT title,artist,source_path FROM tracks").fetchone()
            connection.close()
            self.assertEqual((row["title"], row["artist"]), ("无赖", "郑中基"))
            self.assertIn("鄭中基", row["source_path"])


if __name__ == "__main__":
    unittest.main()
