from theoclaw.agent import conversation as c


def test_new_conversation_is_just_the_question():
    assert c.follow_up_prompt([], "約翰福音 3:16 講甚麼？") == "約翰福音 3:16 講甚麼？"


def test_recent_turns_in_full_older_by_question_and_a_fixed_budget():
    turns = [(f"問題{i}", "答" * 3000) for i in range(10)]
    p = c.follow_up_prompt(turns, "那第 9 節呢？")
    assert p.endswith("【這一次的問題】\n那第 9 節呢？")
    assert "問題0" in p and "使用者：問題9" in p and "使用者：問題6" not in p  # old turns by question only
    assert "……（後略）" in p and len(p) < c.TOTAL_CHARS + 600
    huge = [("問" * 5000, "答" * 5000)] * 3
    assert "使用者：" in c.history_text(huge) and len(c.history_text(huge)) <= c.TOTAL_CHARS  # never empty, never over
