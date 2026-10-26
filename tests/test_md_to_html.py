from report.md_to_html import md_to_html


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
