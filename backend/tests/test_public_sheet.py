from app.integrations.public_sheet import parse_gviz
from app.integrations.sheets_client import FakeSheetsClient, ReadingSheetsClient

_GVIZ = """
/*O_o*/
google.visualization.Query.setResponse({"status":"ok","table":{"cols":[{"label":""},{"label":""},{"label":""}],"rows":[{"c":[{"v":"email"},{"v":"compay name"},{"v":"role"}]},{"c":[{"v":"ada@example.com"},null,{"v":"ai engineer"}]}]}});
"""


def test_header_row_is_taken_from_the_first_data_row_when_google_does_not_label_it() -> None:
    headers, rows = parse_gviz(_GVIZ)
    assert headers == ["email", "compay name", "role"]
    assert rows == [["ada@example.com", "", "ai engineer"]]


def test_unlabeled_sheet_keeps_every_row_as_data() -> None:
    body = """
    google.visualization.Query.setResponse({"status":"ok","table":{"cols":[{"label":""},{"label":""}],"rows":[{"c":[{"v":"ada@example.com"},{"v":"Engineer"}]}]}});
    """
    headers, rows = parse_gviz(body)
    assert headers == ["Column 1", "Column 2"]
    assert rows == [["ada@example.com", "Engineer"]]


def test_missing_spreadsheet_is_loaded_on_read() -> None:
    def fetch(spreadsheet_id: str) -> tuple[list[str], list[list[str]]]:
        assert spreadsheet_id == "public-sheet"
        return ["Email", "Role"], [["ada@example.com", "Engineer"]]

    client = ReadingSheetsClient(FakeSheetsClient(), fetch=fetch)
    grid = client.read_tab("public-sheet", None)
    assert grid.tab_name == "Sheet1"
    assert grid.headers == ["Email", "Role"]
    assert grid.rows == [["ada@example.com", "Engineer"]]
    again = client.read_tab("public-sheet", None)
    assert again.rows == [["ada@example.com", "Engineer"]]


def test_public_sheet_is_reread_when_the_source_changes() -> None:
    grids = [
        (["Email", "Role"], [["ada@example.com", "Engineer"]]),
        (["Email", "Role", "Company"], [["ada@example.com", "Engineer", "Automail"]]),
    ]

    def fetch(spreadsheet_id: str) -> tuple[list[str], list[list[str]]]:
        assert spreadsheet_id == "public-sheet"
        return grids.pop(0)

    client = ReadingSheetsClient(FakeSheetsClient(), fetch=fetch)
    assert client.read_tab("public-sheet", None).rows == [["ada@example.com", "Engineer"]]
    updated = client.read_tab("public-sheet", None)
    assert updated.headers == ["Email", "Role", "Company"]
    assert updated.rows == [["ada@example.com", "Engineer", "Automail"]]
