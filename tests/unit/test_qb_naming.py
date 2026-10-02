from engine.quickbattle import naming


def test_object_name_is_bc_style():
    assert naming.object_name("Bird of Prey", 3) == "Bird of Prey-3"


def test_ordinals_only_on_repeats_in_order_none_passes_through():
    names = ["USS Dauntless", None, "USS Dauntless", "USS Venture", "USS Dauntless", None]
    assert naming.with_ordinals(names) == [
        "USS Dauntless", None, "USS Dauntless (2)", "USS Venture", "USS Dauntless (3)", None]


def test_empty_list():
    assert naming.with_ordinals([]) == []
