from pathlib import Path


def test_coach_prompt_limits_session_facts_to_annotation_slots():
    prompt = (Path(__file__).parents[1] / "prompts" / "coach.md").read_text(
        encoding="utf-8"
    )

    assert "Session facts" in prompt
    assert "`coaching_note`" in prompt
    assert "`segments[].note`" in prompt
    assert "不得新增、刪除、重排或覆寫 Session／Segment" in prompt
    assert "唯一可寫的 Segment annotation slot" in prompt
    assert "唯一可寫的 Session annotation slot" in prompt


def test_coach_prompt_allows_fixed_strength_days_without_distance():
    prompt = (Path(__file__).parents[1] / "prompts" / "coach.md").read_text(
        encoding="utf-8"
    )

    assert "距離型的非休息日" in prompt
    assert '`session_type = "strength_training"`' in prompt
    assert "`distance_km` 必須為 `null`" in prompt
