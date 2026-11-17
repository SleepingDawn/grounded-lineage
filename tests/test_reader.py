from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from scholarly_access_agent.runtime.reader import read_pdf


def make_pdf(path: Path, texts: list[str]) -> None:
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref}),
        })
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 50 740 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


class ReaderTests(unittest.TestCase):
    def test_locates_body_beyond_abstract_with_page_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            make_pdf(path, [
                "Abstract: A machine learning study.",
                "Methods: Training used DFT SCAN energies and forces.",
                "Results: Phonon dispersion was compared with DFT.",
            ])
            result = read_pdf(str(path), terms=["SCAN", "phonon", "NEB"])
            self.assertEqual(result["pages_scanned"], [1, 2, 3])
            self.assertEqual(result["pages_read"], [])
            self.assertEqual({item["page"] for item in result["passages"]}, {2, 3})
            self.assertEqual(result["terms_without_hits"], ["NEB"])
            self.assertEqual(result["verification"], "requires_agent_assessment")
            page = read_pdf(str(path), pages="2")
            self.assertIn("Training used DFT", page["passages"][0]["text"])

    def test_abbreviation_does_not_match_inside_other_words(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            make_pdf(path, ["We examine surface energies."])
            result = read_pdf(str(path), terms=["ACE"])
            self.assertEqual(result["passages"], [])
            self.assertEqual(result["terms_without_hits"], ["ACE"])

    def test_blank_pdf_is_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scan.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with path.open("wb") as handle:
                writer.write(handle)
            result = read_pdf(str(path))
            self.assertEqual(result["status"], "no_extractable_text")
            self.assertEqual(result["verification"], "not_verified")

    def test_text_budget_is_enforced_and_marked(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long.pdf"
            make_pdf(path, ["DFT energy " * 300])
            result = read_pdf(str(path), max_chars=1000)
            self.assertTrue(result["truncated"])
            self.assertLessEqual(sum(len(item["text"]) for item in result["passages"]), 1000)

    def test_invalid_page_ranges_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "paper.pdf"
            make_pdf(path, ["Test body."])
            for pages in ["0", "2", "3-1", "1-21", "x"]:
                with self.subTest(pages=pages), self.assertRaises(ValueError):
                    read_pdf(str(path), pages=pages)


if __name__ == "__main__":
    unittest.main()
