"""The scorer of the questions evaluation."""

from eval.run_questions_eval import score_answer


def test_numbers_with_commas_and_words():
    q = {"numbers": [6417.7], "words": ["מיקסר"], "forbidden": ["מקרר"]}
    assert score_answer("הוצאתם 6,417.70 ₪, כולל מיקסר", q)[0] == 1


def test_missing_number_or_forbidden_word_fails():
    q = {"numbers": [23], "words": [], "forbidden": ["מקרר"]}
    assert score_answer("נשארו 24 ימים", q)[0] == 0
    assert score_answer("נשארו 23 ימים, וגם המקרר", q)[0] == 0
