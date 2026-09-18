from triton.tools.cards import show_link_preview, show_map


def test_show_map_with_place():
    result = show_map(place="restaurants in La Rochelle")
    assert "google.com/maps/search" in result
    assert "restaurants%20in%20La%20Rochelle" in result


def test_show_map_with_directions():
    result = show_map(origin="Paris", destination="La Rochelle")
    assert "google.com/maps/dir" in result
    assert "origin=Paris" in result
    assert "destination=La%20Rochelle" in result


def test_show_map_requires_place_or_both_directions_args():
    assert show_map().startswith("error:")
    assert show_map(origin="Paris").startswith("error:")
    assert show_map(destination="La Rochelle").startswith("error:")


def test_show_link_preview_rejects_non_http_url():
    result = show_link_preview(url="ftp://example.com", title="x")
    assert result.startswith("error:")


def test_show_link_preview_includes_title_and_description():
    result = show_link_preview(url="https://example.com", title="Example", description="A page")
    assert "https://example.com" in result
    assert "Example" in result
    assert "A page" in result
