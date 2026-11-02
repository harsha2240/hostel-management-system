from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class StaticFilesConfigurationTests(SimpleTestCase):
    def test_collectstatic_has_a_separate_destination(self):
        static_root = Path(settings.STATIC_ROOT).resolve()
        source_dirs = {
            Path(directory).resolve() for directory in settings.STATICFILES_DIRS
        }
        self.assertEqual(static_root, (settings.BASE_DIR / "staticfiles").resolve())
        self.assertNotIn(static_root, source_dirs)
        self.assertIsInstance(settings.SECURE_HSTS_SECONDS, int)
        self.assertGreaterEqual(settings.SECURE_HSTS_SECONDS, 0)
