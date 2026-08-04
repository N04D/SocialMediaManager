import ast
import unittest
from pathlib import Path


class YouTubePluginIndependenceTests(unittest.TestCase):
    def test_destination_does_not_import_source_or_transformation_or_commerce(self):
        root = Path("channels/youtube")
        source = "\n".join(path.read_text() for path in root.glob("*.py"))
        tree = ast.parse(source)
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        self.assertFalse(
            any(
                item.startswith(("plugins.sources.youtube", "plugins.transformations", "plugins.commerce"))
                for item in imports
            )
        )
        self.assertNotIn("source.youtube", source)
