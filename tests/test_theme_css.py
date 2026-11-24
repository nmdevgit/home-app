"""Guards for phone compatibility (iPhone Safari / Samsung Internet) in ui/theme.css."""
import re

from ui import theme


def test_css_is_wrapped_and_free_of_user_placeholders() -> None:
    assert theme.CSS.startswith("<style>") and theme.CSS.endswith("</style>")
    assert "{{" not in theme.CSS and "%s" not in theme.CSS


def test_inputs_keep_16px_so_ios_does_not_zoom() -> None:
    assert re.search(r"textarea[^{]*\{[^}]*font-size:\s*16px", theme.CSS)


def test_safe_area_and_text_size_adjust_present() -> None:
    assert "env(safe-area-inset-bottom)" in theme.CSS
    assert "-webkit-text-size-adjust: 100%" in theme.CSS


def test_every_color_mix_declaration_has_a_fallback_before_it() -> None:
    css = re.sub(r"/\*.*?\*/", "", theme.CSS, flags=re.S)  # comments mention color-mix too
    for match in re.finditer(r"([^;{}]*color-mix\([^;]*;)", css):
        before = css[: match.start()]
        prop = match.group(1).strip().split(":")[0]
        # the declaration immediately before must set the same property (rgba fallback)
        last = [d for d in re.split(r"[;{]", before) if d.strip()][-1]
        assert last.strip().startswith(prop), f"no fallback for {prop}"


def test_signed_out_nav_covers_every_signed_in_path() -> None:
    from ui import nav
    paths = nav.url_paths()
    assert len(paths) == len(set(paths)) and "tasks" in paths
    names = {nav.login_stub(lambda: None, p).__name__ for p in paths}
    assert len(names) == len(paths)
