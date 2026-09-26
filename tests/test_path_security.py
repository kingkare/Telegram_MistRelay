import tests  # noqa: F401
import tempfile
import unittest
from pathlib import Path

from path_security import UnsafePathError, resolve_under, validate_child_name


class PathSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "root"
        self.root.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_resolves_normal_relative_and_api_absolute_paths(self):
        self.assertEqual(resolve_under(self.root, "folder/file.txt"), self.root / "folder/file.txt")
        self.assertEqual(resolve_under(self.root, "/folder/file.txt"), self.root / "folder/file.txt")

    def test_rejects_parent_traversal_with_forward_or_backslashes(self):
        for value in ("../secret", "folder/../../secret", "..\\secret"):
            with self.subTest(value=value), self.assertRaises(UnsafePathError):
                resolve_under(self.root, value)

    def test_rejects_symlink_components(self):
        outside = Path(self.temp_dir.name) / "outside"
        outside.mkdir()
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(UnsafePathError):
            resolve_under(self.root, "link/secret.txt")

    def test_can_reject_the_root_directory(self):
        with self.assertRaises(UnsafePathError):
            resolve_under(self.root, "/", allow_root=False)

    def test_validates_upload_file_names(self):
        self.assertEqual(validate_child_name("movie.mp4"), "movie.mp4")
        for value in ("", ".", "..", "../secret", "folder/file", "folder\\file", "bad\x00name"):
            with self.subTest(value=value), self.assertRaises(UnsafePathError):
                validate_child_name(value)


if __name__ == "__main__":
    unittest.main()
