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
    assert [u.unit_key for u in unit_order(units, 'w1')] != [u.unit_key for u in unit_order(units, 'w2')]
