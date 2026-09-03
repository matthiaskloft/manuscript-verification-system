"""The bundled demo manuscripts are demos, not test fixtures.

They were the same files until they were split apart: src/openrefcheck/assets held
byte-identical copies of tests/fixtures/synthetic. That coupling pulled in two
directions — a fixture wants a long, adversarial reference list and a frozen entry
count, a demo wants to finish quickly on a public deployment where every reference is
a live Crossref/OpenAlex lookup — so neither could change without disturbing the other.

Nothing here asserts parser behaviour on the demo documents. That is the point: a demo
carries no baseline, so resizing one is a product decision rather than a parser
decision. What is checked is that the split stays a split.
"""

import json
from pathlib import Path

import pytest

from openrefcheck.webui.pages.upload import DEMO_GROUPS

ASSETS = Path(__file__).resolve().parents[1] / "src" / "openrefcheck" / "assets"
SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
MANIFEST = json.loads((ASSETS / "demo_manifest.json").read_text(encoding="utf-8"))

DEMO_LIMIT = MANIFEST["entry_limit"]


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=lambda d: d["asset"])
def test_demo_document_stays_within_the_reference_limit(doc):
    """A demo run is a handful of live lookups, not a benchmark.

    Raising this ceiling makes every first-time visitor wait longer before seeing a
    result; it is a deliberate decision, so it has to be made in build_demo_assets.py
    where the reasoning lives, not by quietly regenerating a bigger document.
    """
    assert doc["entry_count"] <= DEMO_LIMIT, (
        f"{doc['asset']} carries {doc['entry_count']} references, over the "
        f"{DEMO_LIMIT}-reference demo limit"
    )


@pytest.mark.parametrize("doc", MANIFEST["documents"], ids=lambda d: d["asset"])
def test_demo_document_exists(doc):
    assert (ASSETS / doc["asset"]).is_file()


def test_demo_picker_offers_exactly_the_manifest_documents():
    """The menu and the manifest are written in different files and drift apart.

    A demo missing from the menu is invisible; a menu entry with no file behind it
    fails only when a user clicks it, on the deployment, in front of them.
    """
    offered = {path.name for _group, demos in DEMO_GROUPS for path in demos.values()}
    declared = {doc["asset"] for doc in MANIFEST["documents"]}

    assert offered == declared


def test_no_demo_asset_is_a_copy_of_a_test_fixture():
    """The regression these two directories used to be one set of files.

    Byte-identity is the specific thing that was wrong: it meant regenerating the
    fixtures silently changed what the application shipped, and shrinking a demo
    silently moved a parser baseline.
    """
    fixture_bytes = {
        path.read_bytes() for path in SYNTHETIC.rglob("*.pdf")
    }
    shared = [
        path.name for path in ASSETS.glob("*.pdf") if path.read_bytes() in fixture_bytes
    ]

    assert not shared, f"demo assets identical to test fixtures: {shared}"
