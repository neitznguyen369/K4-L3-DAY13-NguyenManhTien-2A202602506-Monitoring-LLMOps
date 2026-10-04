from app.pii import scrub_text


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


def test_scrub_cccd_and_credit_card() -> None:
    out = scrub_text("CCCD 012345678901, thẻ 4111 1111 1111 1111 và 5500-0000-0000-0004")
    assert "012345678901" not in out
    assert "4111" not in out
    assert "5500-0000" not in out
    assert "REDACTED_CCCD" in out
    assert out.count("REDACTED_CREDIT_CARD") == 2


def test_scrub_passport_and_address() -> None:
    out = scrub_text("Hộ chiếu B1234567, ở số 12 ngõ 5 Láng Hạ")
    assert "B1234567" not in out
    assert "REDACTED_PASSPORT" in out
    assert "REDACTED_ADDRESS" in out
    assert "Láng Hạ" not in out


def test_scrub_keeps_normal_text_and_numbers() -> None:
    text = "Refunds are available within 7 days, latency 2500 ms, cost 0.001287"
    assert scrub_text(text) == text


def test_card_is_not_mistaken_for_phone() -> None:
    out = scrub_text("Card 5500 0000 0000 0004")
    assert "REDACTED_CREDIT_CARD" in out
    assert "REDACTED_PHONE_VN" not in out
