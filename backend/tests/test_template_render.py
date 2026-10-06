from app.services.template_render import render_message


def test_render_records_empty_and_unknown_tokens() -> None:
    rendered = render_message(
        "Hi {{ name }}",
        "Role {{role}} at {{company}}. {{mobile}} {{unknown_token}} {{role}}",
        {
            "name": "A",
            "company": "  ",
            "role": "Engineer",
            "location": None,
            "mobile": None,
            "linkedin_url": None,
        },
    )
    assert rendered.subject == "Hi A"
    assert rendered.body == "Role Engineer at .  {{unknown_token}} Engineer"
    assert rendered.empty_variables == ["company", "mobile"]
    assert rendered.unknown_tokens == ["unknown_token"]
