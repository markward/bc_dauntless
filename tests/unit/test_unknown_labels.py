from engine.appc import unknown_labels


class _Obj:
    pass


def test_placeholders_count_up_and_are_stable():
    unknown_labels.reset()
    a, b = _Obj(), _Obj()
    assert unknown_labels.placeholder(a) == "Unknown 1"
    assert unknown_labels.placeholder(b) == "Unknown 2"
    assert unknown_labels.placeholder(a) == "Unknown 1"


def test_two_contacts_never_share_a_number():
    unknown_labels.reset()
    objs = [_Obj() for _ in range(5)]
    labels = [unknown_labels.placeholder(o) for o in objs]
    assert len(set(labels)) == 5


def test_release_frees_the_lowest_number_for_reuse():
    unknown_labels.reset()
    a, b, c = _Obj(), _Obj(), _Obj()
    unknown_labels.placeholder(a)
    unknown_labels.placeholder(b)
    unknown_labels.release(a)
    assert unknown_labels.current(a) is None
    assert unknown_labels.placeholder(c) == "Unknown 1"
    assert unknown_labels.current(b) == "Unknown 2"


def test_current_never_allocates():
    unknown_labels.reset()
    a = _Obj()
    assert unknown_labels.current(a) is None
    assert unknown_labels.placeholder(_Obj()) == "Unknown 1"
