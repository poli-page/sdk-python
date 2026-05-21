import poli_page


def test_version_is_exposed() -> None:
    assert isinstance(poli_page.__version__, str)
    assert poli_page.__version__ != ""
