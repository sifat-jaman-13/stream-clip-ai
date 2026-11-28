import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import autoclip

class CreatorDatabaseTests(unittest.TestCase):
    def test_creator_profiles_and_live_settings_persist_and_cascade_delete(self):
        persisted = {"min_score": 81}
        def load_shared_settings():
            return autoclip.clean_cfg(persisted)
        def save_shared_settings(values):
            persisted.clear()
            persisted.update(values)
        with tempfile.TemporaryDirectory() as folder, patch.multiple(
            autoclip, _data_root=Path(folder),
            load_settings=MagicMock(side_effect=load_shared_settings),
            save_settings=MagicMock(side_effect=save_shared_settings),
            apply_storage_paths=MagicMock(), streamlink_available=MagicMock(return_value=True),
        ):
            core = autoclip.Core()
            core.push = MagicMock()
            first = core.add_creator({"name": "Creator One", "target": "https://twitch.tv/one"})["creator"]["id"]
            second = core.add_creator({"name": "Creator Two", "target": "https://twitch.tv/two"})["creator"]["id"]
            core.save_creator_settings(first, {"min_score": 93, "color": "Pink"})
            reloaded = autoclip.Core()
            self.assertEqual(reloaded.creators[first]["name"], "Creator One")
            self.assertEqual(reloaded.get_creator_settings(first)["min_score"], 93)
            self.assertEqual(reloaded.get_creator_settings(first)["color"], "Pink")
            self.assertEqual(reloaded.get_creator_settings(second)["min_score"], 93)
            reloaded.push = MagicMock()
            reloaded.remove_creator(first)
            db = sqlite3.connect(Path(folder) / "streamsnip.db")
            try:
                self.assertIsNone(db.execute("SELECT id FROM creators WHERE id=?", (first,)).fetchone())
                self.assertIsNone(db.execute("SELECT creator_id FROM creator_settings WHERE creator_id=?", (first,)).fetchone())
                self.assertIsNotNone(db.execute("SELECT creator_id FROM creator_settings WHERE creator_id=?", (second,)).fetchone())
            finally:
                db.close()

    def test_open_creators_folder_opens_shared_per_creator_root(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(autoclip, "_data_root", Path(folder)):
                with patch.object(autoclip, "open_folder") as open_folder:
                    core = object.__new__(autoclip.Core)
                    result = core.open_creators_folder()
                    expected = Path(folder) / "creators"
                    self.assertTrue(expected.is_dir())
                    self.assertEqual(result["path"], str(expected))
                    open_folder.assert_called_once_with(expected)

    def test_legacy_creator_json_is_migrated_and_removed(self):
        with tempfile.TemporaryDirectory() as folder, patch.multiple(
            autoclip, _data_root=Path(folder),
            load_settings=MagicMock(return_value=autoclip.clean_cfg({})),
            apply_storage_paths=MagicMock(),
        ):
            legacy = Path(folder) / "creators.json"
            legacy.write_text(json.dumps([{"id":"old1","name":"Legacy","target":"https://twitch.tv/legacy"}]), encoding="utf-8")
            core = autoclip.Core()
            self.assertIn("old1", core.creators)
            self.assertFalse(legacy.exists())
            self.assertTrue((Path(folder) / "streamsnip.db").is_file())

if __name__ == "__main__":
    unittest.main()
