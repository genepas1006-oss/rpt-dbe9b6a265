from report.md_to_html import color_deltas, md_to_html


def test_headings_and_bold():
    out = md_to_html("# Title\n\n**bold** text")
    assert "<h2>Title</h2>" in out
    assert "<strong>bold</strong> text" in out


def test_list_items():
    out = md_to_html("- one\n- two")
    assert "<ul>" in out and "</ul>" in out
    assert "<li>one</li>" in out
    assert "<li>two</li>" in out


def test_escapes_html_special_chars():
    out = md_to_html("- 5<10 & ok")
    assert "5&lt;10 &amp; ok" in out


def test_positive_delta_colored_as_up():
    out = color_deltas("当日+3.89%")
    assert '<span style="color:var(--up)">+3.89%</span>' in out


def test_negative_delta_colored_as_down():
    out = color_deltas("当日-3.00%")
    assert '<span style="color:var(--down)">-3.00%</span>' in out


def test_unsigned_number_not_colored():
    out = color_deltas("的中率41.0%")
    assert "<span" not in out


def test_md_to_html_colors_deltas_in_list_items():
    out = md_to_html("- 当日+3.89% / 高値圏(0.89)で引け")
    assert '<span style="color:var(--up)">+3.89%</span>' in out
