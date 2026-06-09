from app.services.interview_service import _sanitize_chat_question_with_metadata


def test_question_sanitizer_trims_russian_a_ne_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Какие 2 поля в response были критичны и как вы понимали, что нашли проблему, а не?",
        language="ru",
    )

    assert question == "Какие 2 поля в response были критичны и как вы понимали, что нашли проблему?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_english_or_not_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "What two checks proved this was a real defect, or not?",
        language="en",
    )

    assert question == "What two checks proved this was a real defect?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_english_dangling_phrase_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "What are the first two things you check, and what's the safest action you'd take in the?",
        language="en",
    )

    assert question == "What are the first two things you check, and what's the safest action you'd take?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_english_how_did_you_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "What was the exact bottleneck, what change did you make, and how did you?",
        language="en",
    )

    assert question == "What was the exact bottleneck, what change did you make?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_russian_chto_ne_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Как вы проверили, что изменение помогло, а просадка больше не повторилась, и что не?",
        language="ru",
    )

    assert question == "Как вы проверили, что изменение помогло, а просадка больше не повторилась?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_russian_dlya_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Какой архитектурный выбор дал эффект и что именно вы сделали лично для?",
        language="ru",
    )

    assert question == "Какой архитектурный выбор дал эффект и что именно вы сделали лично?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_russian_a_ne_prosto_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Что он проверял, и по какому признаку вы поняли бы, что он ловит регрессию, а не просто?",
        language="ru",
    )

    assert question == "Что он проверял, и по какому признаку вы поняли бы, что он ловит регрессию?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_russian_chto_single_word_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Какие поля в ответе важнее всего и что именно подтвердит, что гипотеза?",
        language="ru",
    )

    assert question == "Какие поля в ответе важнее всего и что именно подтвердит?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_russian_po_kakim_number_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Как вы решаете, что ставить первым, и по каким 2–3?",
        language="ru",
    )

    assert question == "Как вы решаете, что ставить первым?"
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"


def test_question_sanitizer_trims_russian_kak_vy_pronoun_tail():
    question, meta = _sanitize_chat_question_with_metadata(
        "Стейкхолдер не соглашался с экспериментом. Как вы его?",
        language="ru",
    )

    assert question == (
        "Давайте перейдём к конкретному полному примеру: что вы сделали лично, "
        "как выбрали следующий шаг и какой результат подтвердил решение?"
    )
    assert meta["question_truncated"] is True
    assert meta["sanitizer_action"] == "fallback_trim"
