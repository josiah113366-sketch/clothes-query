from pathlib import Path
import tempfile
import unittest

from image.install_jars import install


class DependencySafetyTests(unittest.TestCase):
    def test_version_conflict_does_not_partially_modify_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / 'repo', root / 'base'
            destination.mkdir()
            (destination / 'shared-1.0.jar').write_bytes(b'base')
            for name in ['new', 'shared']:
                path = source / 'example' / name / '2.0' / (name + '-2.0.jar')
                path.parent.mkdir(parents=True)
                path.write_bytes(b'candidate')
            with self.assertRaisesRegex(ValueError, 'version conflict'):
                install(source, destination)
            self.assertEqual([p.name for p in destination.iterdir()], ['shared-1.0.jar'])
            self.assertEqual((destination / 'shared-1.0.jar').read_bytes(), b'base')

    def test_existing_same_version_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, destination = root / 'repo', root / 'base'
            destination.mkdir()
            path = source / 'example' / 'shared' / '1.0' / 'shared-1.0.jar'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'candidate')
            (destination / path.name).write_bytes(b'base')
            install(source, destination)
            self.assertEqual((destination / path.name).read_bytes(), b'base')

    def test_empty_resolution_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'No resolved'):
                install(tmp, tmp)
