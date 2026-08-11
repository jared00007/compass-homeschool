"""The National Parks catalog and map projection. Coverage focuses on the
things that would be silently wrong with no obvious symptom: a duplicate or
missing park, a coordinate that doesn't land where its region says it
should, or a park that quietly stops appearing on the map because its
coordinates drifted outside every inset's bounding box.
"""

from __future__ import annotations

from compass import national_parks as parks


def test_catalog_has_all_63_parks_with_unique_keys():
    assert len(parks.PARKS) == 63
    assert len({p.key for p in parks.PARKS}) == 63
    assert len({p.name for p in parks.PARKS}) == 63


def test_every_park_has_real_looking_coordinates():
    for p in parks.PARKS:
        assert -180 <= p.lon <= 180, p.name
        assert -90 <= p.lat <= 90, p.name
        assert p.region in parks.REGIONS, f"{p.name} has unknown region {p.region!r}"


def test_every_region_in_use_is_declared():
    used = {p.region for p in parks.PARKS}
    assert used <= set(parks.REGIONS)


def test_park_by_key_finds_a_real_park_and_none_for_junk():
    assert parks.park_by_key("yellowstone") is not None
    assert parks.park_by_key("yellowstone").name == "Yellowstone"
    assert parks.park_by_key("not-a-real-park") is None


def test_map_insets_have_real_path_data():
    insets = parks.map_insets()
    assert set(insets) == {"conus", "alaska", "hawaii"}
    for name, box in insets.items():
        assert box["path"].startswith("M"), name
        assert box["w"] > 0 and box["h"] > 0


def test_project_places_a_lower_48_park_in_conus():
    result = parks.project(44.60, -110.50)  # Yellowstone
    assert result is not None
    inset, x, y = result
    assert inset == "conus"
    assert 0 <= x <= parks.map_insets()["conus"]["w"]
    assert 0 <= y <= parks.map_insets()["conus"]["h"]


def test_project_places_an_alaska_park_in_the_alaska_inset():
    inset, x, y = parks.project(63.07, -151.00)  # Denali
    assert inset == "alaska"


def test_project_places_a_hawaii_park_in_the_hawaii_inset():
    inset, x, y = parks.project(19.38, -155.20)  # Hawaii Volcanoes
    assert inset == "hawaii"


def test_project_returns_none_for_a_territory_outside_every_inset():
    assert parks.project(-14.25, -170.68) is None  # American Samoa


def test_every_catalog_park_projects_somewhere_or_is_a_known_territory():
    """Regression: a typo'd coordinate should be caught here, not discovered
    as a pin that silently never showed up on the map."""
    known_outside_insets = {"american_samoa", "virgin_islands"}
    for p in parks.PARKS:
        placed = parks.project(p.lat, p.lon)
        if placed is None:
            assert p.key in known_outside_insets, f"{p.name} doesn't project anywhere"
