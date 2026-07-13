from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from catalog import (  # noqa: E402
    CacheCatalog,
    InvalidCatalogInput,
    NameConflict,
    strip_passthrough,
    url_hash,
    with_passthrough,
)


HASH = "998117f977edf08f"
OTHER_HASH = "fedcba9876543210"


class FakeActivity:
    def __init__(self):
        self.forgotten = []
        self.boosted = []

    def all_frecency(self):
        return {HASH: {"raw_count": 4, "rank": 2, "last_seen": 100,
                       "age_multiplier": 2.0, "frecency_score": 4.0}}

    def boost(self, hash_, n=3):
        self.boosted.append((hash_, n))
        return n

    def forget(self, hash_):
        self.forgotten.append(hash_)
        return 7


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name) / "cache"
        self.root.mkdir()
        self.activity = FakeActivity()
        self.catalog = CacheCatalog(self.root, self.activity)

    def tearDown(self):
        self.temp.cleanup()

    def add_entry(self, hash_=HASH, name="Book", source="https://EXAMPLE.com/docs/book.pdf?revision=old"):
        entry = self.root / hash_
        entry.mkdir()
        canonical = entry / f"{name}.html"
        canonical.write_text(f"<title>{name}</title>", encoding="utf-8")
        with self.catalog.mappings_path.open("a", encoding="utf-8") as mappings:
            mappings.write(f"2026-01-01\t{source}\t{hash_}\t{canonical}\n")
        return entry, canonical

    def test_remote_resolution_strips_query_from_identity_and_passthrough(self):
        self.add_entry()
        signed = "https://EXAMPLE.com/docs/book.pdf?revision=new&_pdfvw=passthrough"
        resolved = self.catalog.resolve_source(signed)
        self.assertEqual(resolved.hash, HASH)
        self.assertEqual(resolved.source_ref, "https://EXAMPLE.com/docs/book.pdf?revision=new")
        self.assertEqual(url_hash(signed), HASH)
        self.assertEqual(with_passthrough(strip_passthrough(signed)).count("_pdfvw=passthrough"), 1)

    def test_local_mapping_wins_without_reading_source(self):
        missing = pathlib.Path(self.temp.name) / "cloud" / "book.pdf"
        self.add_entry(source=str(missing))
        resolved = self.catalog.resolve_source(missing)
        self.assertEqual(resolved.hash, HASH)
        self.assertIsNotNone(resolved.representation)

    def test_browser_url_resolution_content_hashes_unmapped_local_file(self):
        pdf = pathlib.Path(self.temp.name) / "new.pdf"
        pdf.write_bytes(b"pdf bytes")
        expected = self.catalog.resolve_source(pdf).hash
        self.assertEqual(self.catalog.hash_for_browser_url(pdf.as_uri()), expected)
        self.assertEqual(
            self.catalog.hash_for_browser_url(f"http://localhost:7435/view?path={pdf}"),
            expected,
        )

    def test_malformed_and_duplicate_mappings_use_last_valid_row(self):
        _entry, canonical = self.add_entry(name="Old")
        renamed_path = canonical.with_name("Latest.html")
        self.catalog.mappings_path.write_text(
            "malformed\n"
            f"1\t/a.pdf\t{HASH}\t{canonical}\n"
            f"2\t/b.pdf\t{HASH}\t{renamed_path}\n",
            encoding="utf-8",
        )
        mapping = self.catalog.mappings()[HASH]
        self.assertEqual(mapping.source_ref, "/b.pdf")
        self.assertEqual(mapping.name, "Latest")

    def test_light_preference_falls_back_to_canonical(self):
        entry, canonical = self.add_entry()
        self.assertEqual(self.catalog.locate_representation(HASH, prefer_light=True).selected, canonical)
        light = entry / "Book.light.html"
        light.write_text("light", encoding="utf-8")
        representation = self.catalog.locate_representation(HASH, prefer_light=True)
        self.assertEqual(representation.canonical, canonical)
        self.assertEqual(representation.selected, light)

    def test_disabled_state_is_sorted_compatible_and_filters_invalid_hashes(self):
        self.add_entry()
        self.catalog.disabled_path.write_text(json.dumps(["not-a-hash", OTHER_HASH]), encoding="utf-8")
        self.assertFalse(self.catalog.is_disabled(HASH))
        self.assertTrue(self.catalog.is_disabled(OTHER_HASH))
        self.assertTrue(self.catalog.set_disabled(HASH, True))
        self.assertEqual(json.loads(self.catalog.disabled_path.read_text())["disabled"], [HASH, OTHER_HASH])
        self.assertTrue(self.catalog.extension_entries()[0]["disabled"])

    def test_library_lists_searches_and_drops_stale_mappings(self):
        entry, canonical = self.add_entry(name="Linear Algebra", source="/courses/math/book.pdf")
        light = entry / "Linear Algebra.light.html"
        light.write_text("light", encoding="utf-8")
        self.catalog.mappings_path.write_text(
            self.catalog.mappings_path.read_text()
            + f"1\t/missing.pdf\t{OTHER_HASH}\t{self.root / OTHER_HASH / 'Gone.html'}\n",
            encoding="utf-8",
        )
        entries = self.catalog.list_entries()
        self.assertEqual([entry["hash"] for entry in entries], [HASH])
        self.assertEqual(self.catalog.search_entries("MATH")[0]["name"], "Linear Algebra")
        self.assertEqual(entries[0]["frecency_score"], 4.0)
        self.assertEqual(entries[0]["href"], f"/{HASH}/{light.name}")
        self.assertEqual(entries[0]["canonical_href"], f"/{HASH}/{canonical.name}")

    def test_rename_updates_both_representations_mapping_and_titles(self):
        entry, _canonical = self.add_entry()
        (entry / "Book.light.html").write_text("<title>Book</title>", encoding="utf-8")
        result = self.catalog.rename(HASH, "../New/Name.html")
        self.assertEqual(result["new_name"], "-New-Name")
        self.assertTrue((entry / "-New-Name.html").is_file())
        self.assertTrue((entry / "-New-Name.light.html").is_file())
        self.assertIn("<title>-New-Name</title>", (entry / "-New-Name.html").read_text())
        self.assertEqual(self.catalog.mappings()[HASH].html_path, entry / "-New-Name.html")
        self.assertEqual(self.activity.boosted, [(HASH, 3)])

    def test_rename_refuses_existing_canonical_or_light_target(self):
        entry, _canonical = self.add_entry()
        (entry / "Taken.light.html").write_text("occupied", encoding="utf-8")
        with self.assertRaises(NameConflict):
            self.catalog.rename(HASH, "Taken")

    def test_delete_is_atomic_across_catalog_state_and_activity(self):
        entry, _canonical = self.add_entry(source="https://example.com/book.pdf?_pdfvw=passthrough")
        self.catalog.set_disabled(HASH, True)
        result = self.catalog.delete(HASH)
        self.assertFalse(entry.exists())
        self.assertNotIn(HASH, self.catalog.mappings())
        self.assertFalse(self.catalog.is_disabled(HASH))
        self.assertEqual(result["source_ref"], "https://example.com/book.pdf")
        self.assertEqual(result["visits_deleted"], 7)

    def test_mutations_reject_traversal_and_symlink_escape(self):
        with self.assertRaises(InvalidCatalogInput):
            self.catalog.delete("../outside")
        outside = pathlib.Path(self.temp.name) / "outside"
        outside.mkdir()
        (self.root / HASH).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(InvalidCatalogInput):
            self.catalog.delete(HASH)
        self.assertTrue(outside.is_dir())


if __name__ == "__main__":
    unittest.main()
