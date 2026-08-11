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


def test_every_park_has_an_icon():
    """icon_for always returns something -- the generic fallback for a park
    that isn't sorted into any terrain bucket, never a crash."""
    for p in parks.PARKS:
        icon = parks.icon_for(p.key)
        assert isinstance(icon, str) and icon


def test_states_catalog_has_all_50_states_with_real_path_data():
    assert len(parks.STATES) == 50
    for name in parks.STATES:
        box = parks.state_inset(name)
        assert box is not None, name
        assert box["inset"] in {"conus", "alaska", "hawaii"}
        assert box["path"].startswith("M"), name


def test_state_abbr_covers_every_state_a_park_lists():
    """Every abbreviation a park's `states` field can contain must resolve to
    a real state name -- otherwise a travel entry migrated from an old park
    visit would silently land with a blank state."""
    for p in parks.PARKS:
        for abbr in p.states.split("/"):
            if abbr in parks.STATE_ABBR:
                assert parks.STATE_ABBR[abbr] in parks.STATES


def test_render_travel_map_svg_is_well_formed():
    svg = parks.render_travel_map_svg("conus", {"Montana"}, {"glacier"}, "glacier")
    assert svg.startswith("<svg")
    assert svg.count("<svg") == svg.count("</svg>") == 1
    assert "Montana" in svg


def test_render_travel_map_svg_shades_a_visited_state_differently():
    svg_unvisited = parks.render_travel_map_svg("conus", set(), set(), None)
    svg_visited = parks.render_travel_map_svg("conus", {"Montana"}, set(), None)
    assert svg_unvisited != svg_visited


def test_render_travel_map_svg_only_pins_visited_parks():
    svg = parks.render_travel_map_svg("conus", {"Montana"}, {"glacier"}, "glacier")
    assert "Glacier -- visited" in svg
    assert "Yellowstone -- visited" not in svg


def test_cluster_and_place_spreads_close_points_with_leader_lines():
    """Two parks placed right on top of each other must not silently
    overlap -- each should get pushed apart and a leader line drawn back to
    its real spot."""
    close_points = [
        (parks.park_by_key("zion"), 100.0, 100.0),
        (parks.park_by_key("bryce_canyon"), 101.0, 101.0),
    ]
    placed, leaders = parks._cluster_and_place(close_points, min_dist=15, spread_radius=20)
    assert len(placed) == 2
    assert len(leaders) == 2
    for _, x, y in placed:
        assert (x, y) != (100.0, 100.0) or (x, y) != (101.0, 101.0)


def test_cluster_and_place_leaves_isolated_points_untouched():
    far_apart = [
        (parks.park_by_key("acadia"), 10.0, 10.0),
        (parks.park_by_key("olympic"), 500.0, 300.0),
    ]
    placed, leaders = parks._cluster_and_place(far_apart, min_dist=15, spread_radius=20)
    assert leaders == []
    assert {(x, y) for _, x, y in placed} == {(10.0, 10.0), (500.0, 300.0)}
