"""Playground replies include approved solutions and only supplied video links."""

from collections import Counter

import pytest
import yaml

from gab_faq.knowledge import KnowledgeBase
from gab_faq.search import FaqSearch, SearchSettings, split_entries
from gab_faq.tutorials import load_tutorials

from .conftest import ROOT


@pytest.fixture
def tutorial_knowledge(tmp_path):
    (tmp_path / "faq.md").write_text(
        "---\ntitle: Approved FAQ\naudience: all\n---\n\n"
        "PG1. How do I reset the playground environment?\n"
        "Click Reset Environment, wait for completion, and copy the Reset ID.\n\n"
        "A1. Which model is Product A?\nSelect Flash, then Model Locust.\n",
        encoding="utf-8",
    )
    write_catalog(tmp_path, "https://drive.google.com/file/d/synthetic-reset/view")
    return KnowledgeBase(tmp_path)


def write_catalog(directory, url):
    catalog = {
        "videos": [
            {
                "id": "reset",
                "title": "Production - Reset",
                "url": url,
                "faq_ids": ["PG1"],
            }
        ]
    }
    (directory / "playground-videos.yaml").write_text(yaml.safe_dump(catalog), encoding="utf-8")


def test_local_reply_contains_solution_and_supplied_video_link(tutorial_knowledge):
    answer = FaqSearch(tutorial_knowledge, embedder=None).answer(
        "How do I reset the playground environment?"
    )
    assert "copy the Reset ID" in answer.text
    assert "https://drive.google.com/file/d/synthetic-reset/view" in answer.text
    assert "invented.invalid" not in answer.text
    assert "I reset the account" not in answer.text
    assert answer.sources == ["PG1"]


def test_search_reply_contains_solution_and_supplied_video_link(tutorial_knowledge):
    search = FaqSearch(tutorial_knowledge, SearchSettings(), embedder=None)
    answer = search.answer("reset playground environment Reset ID")
    assert answer.sources == ["PG1"]
    assert "Click Reset Environment" in answer.text
    assert "https://drive.google.com/file/d/synthetic-reset/view" in answer.text


def test_pdf_faq_reply_remains_text_without_unrelated_video(tutorial_knowledge):
    answer = FaqSearch(tutorial_knowledge, embedder=None).answer("Which model is Product A?")
    assert "Select Flash, then Model Locust." in answer.text
    assert "Related playground videos" not in answer.text
    assert "https://" not in answer.text


def test_catalog_link_changes_reload_without_editing_faq(tutorial_knowledge):
    brain = FaqSearch(tutorial_knowledge, embedder=None)
    brain.answer("How do I reset the playground environment?")
    write_catalog(tutorial_knowledge.directory, "https://example.org/replacement-video")
    answer = brain.answer("How do I reset the playground environment?")
    assert "https://example.org/replacement-video" in answer.text
    assert "synthetic-reset" not in answer.text


def test_catalog_changes_also_reload_in_search(tutorial_knowledge):
    search = FaqSearch(tutorial_knowledge, SearchSettings(), embedder=None)
    write_catalog(tutorial_knowledge.directory, "https://example.org/new-search-video")
    answer = search.answer("reset playground environment Reset ID")
    assert "https://example.org/new-search-video" in answer.text


def test_missing_video_url_is_honest_and_keeps_solution(tutorial_knowledge):
    write_catalog(tutorial_knowledge.directory, None)
    answer = FaqSearch(tutorial_knowledge, embedder=None).answer(
        "How do I reset the playground environment?"
    )
    assert "copy the Reset ID" in answer.text
    assert "Production - Reset (ask your QM for the video link)" in answer.text
    assert "https://" not in answer.text and "file://" not in answer.text


@pytest.mark.parametrize(
    "url",
    [
        "file:///C:/Downloads/Reset.mp4",
        "javascript:alert(1)",
        "http://example.org/reset",
        "https://user:password@example.org/reset",
        "https://example.org/reset\n@everyone",
        "https://example.org/reset><@123>",
        ["https://example.org/reset"],
    ],
)
def test_catalog_rejects_invalid_video_urls(tmp_path, url):
    write_catalog(tmp_path, url)
    with pytest.raises(ValueError):
        load_tutorials(tmp_path / "playground-videos.yaml")


def test_bad_catalog_update_keeps_last_good_knowledge(tutorial_knowledge):
    write_catalog(tutorial_knowledge.directory, "file:///C:/private/Reset.mp4")
    answer = FaqSearch(tutorial_knowledge, embedder=None).answer(
        "How do I reset the playground environment?"
    )
    assert "https://drive.google.com/file/d/synthetic-reset/view" in answer.text
    assert "file:///" not in answer.text


def test_archive_inventory_has_no_unmapped_or_duplicate_paths():
    directory = ROOT / "knowledge" / "current"
    catalog = yaml.safe_load((directory / "playground-videos.yaml").read_text(encoding="utf-8"))
    videos = catalog["videos"]
    archive_videos = [video for video in videos if "archive_paths" in video]
    assert len(archive_videos) == 11
    # All 13 videos have a supplied link (the last three were added from the shared Playgrounds folder).
    assert len([video for video in videos if video.get("url")]) == 13
    paths = [path for video in archive_videos for path in video["archive_paths"]]
    assert len(paths) == 21 and len(set(paths)) == 21
    assert len({video["sha256"] for video in archive_videos}) == 11
    entries = [entry for doc in KnowledgeBase(directory).documents for entry in split_entries(doc)]
    counts = Counter(entry.id for entry in entries)
    assert all(count == 1 for count in counts.values())
    for video in load_tutorials(directory / "playground-videos.yaml"):
        assert all(ref in counts for ref in video.faq_ids)
        assert any(ref.startswith("PG") for ref in video.faq_ids)
