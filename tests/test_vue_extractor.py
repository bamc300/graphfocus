"""Tests for the Vue SFC extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from graphfocus.extractors.vue_extractor import VueExtractor


@pytest.fixture
def extractor() -> VueExtractor:
    return VueExtractor()


@pytest.fixture
def vue_fixture() -> Path:
    return Path(__file__).parent / "fixtures" / "vue" / "UserList.vue"


class TestVueExtractor:
    def test_file_is_a_component(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        comp = next(n for n in result.nodes if n.kind == "component")
        assert comp.label == "UserList"
        assert comp.language == "vue"

    def test_no_errors(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        assert not result.errors

    def test_script_interface_extracted(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        kinds = {n.label: n.kind for n in result.nodes}
        # The User interface defined in <script> should be picked up via
        # the delegated TypeScript extractor.
        assert kinds.get("User") == "interface"

    def test_script_function_extracted(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        labels = {n.label for n in result.nodes}
        assert "reload()" in labels

    def test_template_child_components_referenced(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        uses = [e for e in result.edges if e.relation == "uses"]
        # The template uses both <UserCard> and <user-badge>.
        targets = {e.target for e in uses}
        from graphfocus.extractors.base import make_id
        assert make_id("vue", "UserCard") in targets
        assert make_id("vue", "userbadge") in targets

    def test_native_html_tags_not_treated_as_components(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        uses = [e for e in result.edges if e.relation == "uses"]
        from graphfocus.extractors.base import make_id
        # <section>, <h2>, <button> are native HTML and must not appear.
        forbidden = {make_id("vue", t) for t in ("section", "h2", "button")}
        assert not (forbidden & {e.target for e in uses})

    def test_line_numbers_offset_into_vue_file(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        # The User interface in the fixture lives around line 14-17 of the .vue
        # file; if line offsetting works the recorded location must be >= 10.
        user_iface = next(n for n in result.nodes if n.label == "User")
        assert user_iface.source_location is not None
        assert user_iface.source_location.startswith("L")
        line = int(user_iface.source_location[1:])
        assert line >= 10, f"expected line offset into .vue file, got L{line}"

    def test_source_file_points_to_vue_file(self, extractor, vue_fixture):
        result = extractor.extract(vue_fixture)
        for n in result.nodes:
            assert n.source_file.endswith("UserList.vue")
