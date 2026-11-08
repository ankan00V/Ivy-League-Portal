from migrations.neon.migrate_opportunities import COLUMNS, to_row


def _row_by_column(document: dict) -> dict:
    row = to_row(document)
    assert row is not None
    return dict(zip(COLUMNS, row, strict=True))


def test_to_row_derives_feed_columns_for_career_listing() -> None:
    row = _row_by_column(
        {
            "_id": "507f1f77bcf86cd799439011",
            "url": "https://example.com/jobs/data-intern",
            "title": "Data Engineering Intern",
            "description": "Remote internship based in Bengaluru, India.",
            "opportunity_type": "Internship",
            "location": "Bengaluru, India",
            "work_mode": "Remote",
            "source": "company_board",
            "tags": ["Python", "SQL"],
        }
    )

    assert row["portal_category"] == "career"
    assert row["role_track"] == "technical"
    assert set(row["feed_categories"]) == {"india", "remote"}


def test_to_row_derives_competitive_portal_when_source_value_is_missing() -> None:
    row = _row_by_column(
        {
            "_id": "507f1f77bcf86cd799439012",
            "url": "https://example.com/events/buildathon",
            "title": "AI Buildathon 2026",
            "description": "A student hackathon for teams building AI products.",
            "opportunity_type": "Hackathon",
        }
    )

    assert row["portal_category"] == "competitive"
