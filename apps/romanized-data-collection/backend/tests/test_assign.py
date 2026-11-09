from types import SimpleNamespace

from app.assign import MIN_REPEAT_GAP, unit_order


def test_repeats_late_and_apart():
    units = [SimpleNamespace(unit_key=f'u{i}', repeat_of=None) for i in range(260)]
    units += [SimpleNamespace(unit_key=f'r{i}', repeat_of=f'u{i * 7}') for i in range(15)]
    for name in ('w1', 'w2', 'w3'):
        order = unit_order(units, name)
        assert len(order) == 275
        pos = {u.unit_key: i for i, u in enumerate(order)}
        for i in range(15):
            assert pos[f'r{i}'] >= 260 // 2 - 15  # second half (insertions shift positions slightly)
            assert abs(pos[f'r{i}'] - pos[f'u{i * 7}']) >= MIN_REPEAT_GAP
    # every writer sees the same order, so writers who stop early overlap on the same items
    assert [u.unit_key for u in unit_order(units, 'w1')] == [u.unit_key for u in unit_order(units, 'w2')]


def test_same_relative_order_and_finished_items_first():
    from collections import Counter
    units = [SimpleNamespace(id=i, unit_key=f'u{i}', repeat_of=None) for i in range(50)]
    full = [u.unit_key for u in unit_order(units, 'a')]
    part = [u.unit_key for u in unit_order(units[10:], 'b')]
    assert [k for k in full if k in set(part)] == part       # a writer with fewer items keeps the shared order
    first = unit_order(units, 'c', Counter({units[7].id: 3, units[3].id: 2}))
    assert [u.unit_key for u in first[:2]] == ['u7', 'u3']    # items most writers finished come first
