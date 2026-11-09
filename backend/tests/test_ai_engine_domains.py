from app.services.ai_engine import AIEngine


def test_domain_classifier_uses_word_boundaries_for_short_keywords():
    result = AIEngine().classify_opportunity(
        "Help retail customers understand product features and complete purchases.",
        title="Retail Sales Intern",
    )

    assert result["primary_domain"] == "Sales and Support"
    assert "AI and Machine Learning" not in result["relevant_domains"]


def test_domain_classifier_prioritizes_the_role_title_over_body_mentions():
    result = AIEngine().classify_opportunity(
        "Work alongside the engineering and analytics teams on campaign reports.",
        title="Digital Marketing Intern",
    )

    assert result["primary_domain"] == "Marketing"


def test_domain_classifier_keeps_cybersecurity_roles_in_engineering():
    result = AIEngine().classify_opportunity(
        "Support threat modelling, cloud security controls, and incident triage.",
        title="Cybersecurity Intern",
    )

    assert result["primary_domain"] == "Engineering"
