def test_package_exposes_version():
    import syvern

    assert isinstance(syvern.__version__, str)
    assert syvern.__version__
