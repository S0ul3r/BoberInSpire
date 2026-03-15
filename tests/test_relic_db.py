import json
import tempfile
from pathlib import Path

import pytest

# Module under test; we clear its _DB when using custom JSON
import python_app.relic_db as _relic_db_module
from python_app.relic_db import (
    get_short_description,
    get_short_description_only,
    load_relic_db,
    lookup_relic,
    rarity_color,
    rarity_sort_key,
    summarize_relic_bonuses,
    enrich_relic_description,
)


SAMPLE_RELICS_JSON = [
    {
        "id": "ANCHOR",
        "name": "Anchor",
        "description": "Start each combat with 10 Block.",
        "rarity": "Common",
        "pool": "shared",
        "short_description": "+10 Block",
    },
    {
        "id": "AKABEKO",
        "name": "Akabeko",
        "description": "At the start of each combat, gain 8 Vigor.",
        "rarity": "Uncommon",
        "pool": "shared",
        "short_description": "Get +8 Vigor",
    },
    {
        "id": "PURE_GOLD",
        "name": "Pure Gold",
        "description": "Enemies drop 25 additional Gold.",
        "rarity": "Rare",
        "pool": "shared",
        "short_description": "",
    },
]


def _clear_relic_db():
    _relic_db_module._DB = {}


class TestLoadRelicDb:
    def test_load_from_path(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(SAMPLE_RELICS_JSON, f)
            path = Path(f.name)
        try:
            db = load_relic_db(path)
            assert "anchor" in db
            assert db["anchor"]["name"] == "Anchor"
            assert db["anchor"]["short_description"] == "+10 Block"
            assert db["akabeko"]["rarity"] == "uncommon"
        finally:
            path.unlink()

    def test_missing_file_returns_empty(self):
        _clear_relic_db()
        db = load_relic_db(Path("nonexistent_relics_xyz.json"))
        assert db == {}


class TestLookupRelic:
    def test_lookup_exact_name(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(SAMPLE_RELICS_JSON, f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            info = lookup_relic("Anchor")
            assert info is not None
            assert info["name"] == "Anchor"
            assert info["short_description"] == "+10 Block"
        finally:
            path.unlink()


class TestGetShortDescription:
    def test_returns_short_when_present(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(SAMPLE_RELICS_JSON, f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            assert get_short_description("Anchor") == "+10 Block"
            assert get_short_description("Akabeko") == "Get +8 Vigor"
        finally:
            path.unlink()

    def test_returns_empty_for_unknown(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump([], f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            assert get_short_description("Unknown Relic") == ""
        finally:
            path.unlink()


class TestGetShortDescriptionOnly:
    def test_returns_short_when_present(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(SAMPLE_RELICS_JSON, f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            assert get_short_description_only("Anchor") == "+10 Block"
        finally:
            path.unlink()

    def test_returns_empty_when_short_missing_no_fallback(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(SAMPLE_RELICS_JSON, f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            assert get_short_description_only("Pure Gold") == ""
        finally:
            path.unlink()


class TestRaritySortKey:
    def test_ancient_first(self):
        assert rarity_sort_key("Ancient") < rarity_sort_key("Common")

    def test_common_before_starter(self):
        assert rarity_sort_key("Common") < rarity_sort_key("Starter")

    def test_unknown_high(self):
        assert rarity_sort_key("???") == 99


class TestRarityColor:
    def test_known_rarity(self):
        assert rarity_color("Rare") == "#ffd700"
        assert rarity_color("common") == "#cccccc"

    def test_unknown_default(self):
        assert rarity_color("???") == "#cccccc"


class TestSummarizeRelicBonuses:
    def test_damage_and_block_categories(self):
        _clear_relic_db()
        relics = [
            {"name": "A", "description": "Gain 2 Strength at start of combat."},
            {"name": "B", "description": "Start with 5 Block."},
        ]
        lines = summarize_relic_bonuses(relics)
        assert any("DMG:" in line for line in lines)
        assert any("BLK:" in line for line in lines)

    def test_empty_list(self):
        assert summarize_relic_bonuses([]) == []

    def test_energy_category(self):
        relics = [{"name": "E", "description": "Gain 1 additional energy each turn."}]
        lines = summarize_relic_bonuses(relics)
        assert any("NRG:" in line for line in lines)


class TestEnrichRelicDescription:
    def test_returns_description_when_in_db(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump(SAMPLE_RELICS_JSON, f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            desc = enrich_relic_description("Anchor")
            assert "10 Block" in desc
        finally:
            path.unlink()

    def test_returns_empty_for_unknown(self):
        _clear_relic_db()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump([], f)
            path = Path(f.name)
        try:
            load_relic_db(path)
            assert enrich_relic_description("Unknown") == ""
        finally:
            path.unlink()
