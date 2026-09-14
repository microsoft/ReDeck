import unittest
import tempfile
from pathlib import Path

from pattern_library.scene_primitives import ScenePrimitiveLibrary, format_scene_primitives


class ScenePrimitiveTest(unittest.TestCase):
    def test_compiles_executable_native_visual_language(self):
        with tempfile.TemporaryDirectory() as directory:
            seeds = Path(directory)
            (seeds / "seed_075.html").write_text(
                '<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">'
                '<circle cx="60" cy="60" r="40" fill="#0099cc"/>'
                '<path d="M 20 180 L 100 20 L 180 180 Z" fill="none" stroke="#eeeeee" stroke-width="3"/>'
                '</svg>'
            )
            spec = ScenePrimitiveLibrary(seeds_path=seeds).compile("seed_075", ["big-numbers-KPI"])
        self.assertIn("bg", spec["recipes"])
        self.assertIn("typo", spec["recipes"])
        self.assertIn("deco", spec["recipes"])
        self.assertNotIn("--source-", " ".join(spec["recipes"].values()))
        block = format_scene_primitives(spec)
        self.assertIn("SCENE-NATIVE EXECUTABLE PRIMITIVES", block)
        self.assertIn("```css", block)
        self.assertIn("NATIVE MOTIF PRIMITIVE", block)
        self.assertTrue(spec["motif_program"])
        self.assertIn("SIGNATURE MOTIF PROGRAM", block)
        self.assertNotRegex(" ".join(spec["motif_program"]), r"#[0-9a-fA-F]{3,8}\b")


if __name__ == "__main__":
    unittest.main()
