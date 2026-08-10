import os
import re
import tempfile
import unittest

from subtitle_generator import generate_subtitle_overlay
from subtitle_structurer import structure_subtitles_from_whisper


class SubtitleGeneratorTests(unittest.TestCase):
    def test_structurer_creates_hook_and_standard_blocks(self):
        words = [
            {"word": "Hey", "start": 0.0, "end": 0.4},
            {"word": "this", "start": 0.4, "end": 0.8},
            {"word": "is", "start": 0.8, "end": 1.2},
            {"word": "a", "start": 1.2, "end": 1.4},
            {"word": "hook", "start": 1.4, "end": 1.8},
            {"word": "for", "start": 1.8, "end": 2.2},
            {"word": "your", "start": 2.2, "end": 2.6},
            {"word": "video", "start": 2.6, "end": 3.0},
            {"word": "later", "start": 3.0, "end": 3.4},
            {"word": "text", "start": 3.4, "end": 3.8},
        ]

        blocks = structure_subtitles_from_whisper(words, api_key=None)
        self.assertTrue(blocks)
        self.assertEqual(blocks[0]["type"], "hook")
        self.assertTrue(any(block["type"] == "standard" for block in blocks))

    def test_structurer_creates_single_word_blocks_for_long_words(self):
        words = [
            {"word": "supercalifragilistic", "start": 0.0, "end": 0.4},
            {"word": "extraordinary", "start": 0.4, "end": 0.8},
            {"word": "moment", "start": 0.8, "end": 1.2},
        ]

        blocks = structure_subtitles_from_whisper(words, api_key=None)
        self.assertTrue(any(block["type"] == "single_word" for block in blocks))

    def test_structurer_preserves_all_words_without_duplicates(self):
        words = [
            {"word": "РАЗ", "start": 0.0, "end": 0.3},
            {"word": "ДВА", "start": 0.3, "end": 0.6},
            {"word": "ТРИ", "start": 0.6, "end": 0.9},
            {"word": "ЧЕТЫРЕ", "start": 0.9, "end": 1.2},
        ]

        blocks = structure_subtitles_from_whisper(words, api_key=None)
        collected = []
        for block in blocks:
            collected.extend(
                words[idx]["word"] for idx in block.get("word_indices", []) if 0 <= idx < len(words)
            )

        self.assertEqual(collected, ["РАЗ", "ДВА", "ТРИ", "ЧЕТЫРЕ"])

    def test_ass_output_includes_structured_line_breaks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "subs.ass")
            generate_subtitle_overlay(
                whisper_words=[
                    {"word": "This", "start": 0.0, "end": 0.4},
                    {"word": "is", "start": 0.4, "end": 0.7},
                    {"word": "a", "start": 0.7, "end": 1.0},
                    {"word": "hook", "start": 1.0, "end": 1.3},
                    {"word": "with", "start": 1.3, "end": 1.6},
                    {"word": "later", "start": 1.6, "end": 2.0},
                    {"word": "words", "start": 2.0, "end": 2.4},
                ],
                keep_segments=[{"start": 0.0, "end": 3.0}],
                output_ass_path=output_path,
            )
            with open(output_path, "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("\\fs", content)
            self.assertIn("\\c", content)
            self.assertIn("Style: Reel,Days One", content)
            self.assertIn("&H80000000&", content)
            self.assertIn("ShadowColour", content)
            self.assertIn("Dialogue:", content)
            self.assertNotIn("\\pos(", content)
            self.assertNotIn("\\an", content)
            self.assertIn("\\N", content)
            self.assertGreaterEqual(content.count("Dialogue:"), 1)

    def test_ass_output_uses_unique_positions_per_time_window(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "subs.ass")
            generate_subtitle_overlay(
                whisper_words=[
                    {"word": "This", "start": 0.0, "end": 0.4},
                    {"word": "is", "start": 0.4, "end": 0.7},
                    {"word": "a", "start": 0.7, "end": 1.0},
                    {"word": "hook", "start": 1.0, "end": 1.3},
                    {"word": "with", "start": 1.3, "end": 1.6},
                    {"word": "later", "start": 1.6, "end": 2.0},
                    {"word": "words", "start": 2.0, "end": 2.4},
                ],
                keep_segments=[{"start": 0.0, "end": 3.0}],
                output_ass_path=output_path,
            )
            with open(output_path, "r", encoding="utf-8") as handle:
                content = handle.read()

            self.assertNotIn("\\pos(", content)
            self.assertNotIn("\\an", content)

    def test_ass_output_avoids_complex_positioning_tags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "subs.ass")
            generate_subtitle_overlay(
                whisper_words=[
                    {"word": "Simple", "start": 0.0, "end": 0.4},
                    {"word": "subtitle", "start": 0.4, "end": 0.8},
                    {"word": "line", "start": 0.8, "end": 1.2},
                ],
                keep_segments=[{"start": 0.0, "end": 2.0}],
                output_ass_path=output_path,
            )
            with open(output_path, "r", encoding="utf-8") as handle:
                content = handle.read()

            self.assertNotIn("\\an", content)
            self.assertNotIn("\\frz", content)
            self.assertNotIn("\\fscx", content)
            self.assertIn("\\N", content)


if __name__ == "__main__":
    unittest.main()
