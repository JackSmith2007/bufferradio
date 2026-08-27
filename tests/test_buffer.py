from bufferradio.buffer import SegmentBuffer


def test_register_then_store() -> None:
    buf = SegmentBuffer()
    buf.register(10, 6.0)
    seg = buf.get(10)
    assert seg is not None
    assert seg.duration == 6.0
    assert seg.data is None  # listed, not downloaded yet

    buf.store(10, b"audio")
    seg = buf.get(10)
    assert seg.data == b"audio"
    assert seg.arrived_at is not None


def test_register_is_idempotent() -> None:
    buf = SegmentBuffer()
    buf.register(1, 6.0)
    buf.store(1, b"x")
    buf.register(1, 6.0)  # every playlist poll re-registers listed segments
    assert buf.get(1).data == b"x"


def test_store_ignores_unknown_and_already_stored() -> None:
    buf = SegmentBuffer()
    buf.store(5, b"orphan")
    assert buf.get(5) is None

    buf.register(6, 6.0)
    buf.store(6, b"first")
    buf.store(6, b"second")
    assert buf.get(6).data == b"first"


def test_missing_segments_form_the_backfill_worklist() -> None:
    buf = SegmentBuffer()
    for seq in (1, 2, 3):
        buf.register(seq, 6.0)
    buf.store(1, b"a")
    buf.store(3, b"c")
    owed = [seq for seq in (1, 2, 3) if buf.get(seq).data is None]
    assert owed == [2]


def test_evict_before_drops_old_segments_and_sets_floor() -> None:
    buf = SegmentBuffer()
    for seq in range(1, 6):
        buf.register(seq, 6.0)

    assert buf.evict_before(3) == 2
    assert buf.get(1) is None
    assert buf.get(2) is None
    assert buf.get(3) is not None
    assert len(buf) == 3
    assert buf.oldest_seq() == 3
    assert buf.latest_seq() == 5

    # A later playlist poll cannot resurrect an evicted (already played) segment.
    buf.register(2, 6.0)
    assert buf.get(2) is None
    assert len(buf) == 3


def test_empty_buffer() -> None:
    buf = SegmentBuffer()
    assert buf.oldest_seq() is None
    assert buf.latest_seq() is None
    assert buf.evict_before(100) == 0
    assert len(buf) == 0
