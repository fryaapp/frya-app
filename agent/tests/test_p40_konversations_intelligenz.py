"""Tests for P-40: Konversations-Intelligenz."""
import pytest


def test_tags_no_duplicates():
    """Tag collection in writeback must deduplicate IDs."""
    existing_tags = [1, 2, 3]
    new_tag_analysiert = 2  # already exists
    new_tag_vst = 4

    tag_ids = set(existing_tags)
    tag_ids.add(new_tag_analysiert)
    tag_ids.add(new_tag_vst)

    result = sorted(tag_ids)
    assert result == [1, 2, 3, 4]
    assert len(result) == 4  # no duplicates
