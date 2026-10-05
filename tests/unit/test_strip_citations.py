from localect.text import strip_citations


def test_strips_bracketed_and_bare_ids_and_tidies_spacing():
    s = "طلبك رح يوصل خلال 5 أيام [kb:3ba98fc9f1:101]. رح نبعتلك إيميل [kb:3ba98fc9f1:0]."
    assert strip_citations(s) == "طلبك رح يوصل خلال 5 أيام. رح نبعتلك إيميل."
    assert strip_citations("See gl:12ab and hx:9 here") == "See and here"
    assert strip_citations("clean text stays") == "clean text stays"
