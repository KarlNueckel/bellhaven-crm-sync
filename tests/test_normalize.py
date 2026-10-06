import normalize as n


def test_street_suffixes_and_directionals():
    assert n.street("1250 NW Franklin Street") == n.street("1250 Northwest Franklin St")
    assert n.street("3156 W Prospect Rd") == n.street("3156 West Prospect Road")
    assert n.street("3313 Wilmington Pike") == n.street("3313 Wilmington Pk")
    assert n.street("8060 Willow Creek Ln") == n.street("8060 Willow Creek Lane")
    assert n.street("1125 Logan Blvd") == n.street("1125 Logan Boulevard.")


def test_street_ampersand():
    assert n.street("1 Main & Elm") == n.street("1 Main and Elm")


def test_po_box_detection():
    assert n.is_po_box("PO Box 112")
    assert n.is_po_box("P.O. Box 9")
    assert not n.is_po_box("112 Box Elder Rd")


def test_zip_and_phone():
    assert n.zip5("45840-1234") == "45840"
    assert n.phone("(614) 250-9447") == n.phone("+1 614.250.9447") == "6142509447"
    assert n.phone("555-1234") == ""


def test_name_variants():
    assert n.name("Bellhaven Healthcare Centre of Ashland") == n.name("Bellhaven Healthcare Center of Ashland")
    assert n.name("Rehabilitation & Nursing") == n.name("Rehabilitation and Nursing")


def test_care_mapping():
    assert n.care("Short-Term Rehabilitation & Nursing") == "Skilled Nursing"
    assert n.care("Memory Support") == "Memory Care"
    assert n.care("Assisted Living") == "Assisted Living"
