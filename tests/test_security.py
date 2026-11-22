from src.security import redact


def test_card_and_id_numbers_are_hidden():
    text = "כרטיס 4580 1234 5678 9012, ת.ז. 012345678"
    out = redact(text)
    assert "4580" not in out and "9012" in out
    assert "01234" not in out and "5678" in out
