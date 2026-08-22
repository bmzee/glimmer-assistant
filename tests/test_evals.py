from evals.run import load_tasks, score


def task(**kw):
    base = {
        "id": "t1",
        "prompt": "p",
        "expect_tools": [],
        "expect_substrings": [],
        "forbid_tools": [],
    }
    base.update(kw)
    return base


def test_passes_when_expected_tool_ran_and_substring_present():
    result = score(
        task(expect_tools=["list_dir"], expect_substrings=["files"]),
        answer="You have 3 files.",
        tools_used=["list_dir"],
    )
    assert result["passed"] is True
    assert result["missing_tools"] == []


def test_fails_when_expected_tool_missing():
    result = score(
        task(expect_tools=["list_dir"]), answer="whatever", tools_used=[]
    )
    assert result["passed"] is False
    assert result["missing_tools"] == ["list_dir"]


def test_fails_when_substring_absent():
    result = score(
        task(expect_substrings=["calculator"]), answer="I opened Notes.", tools_used=[]
    )
    assert result["passed"] is False
    assert result["missing_substrings"] == ["calculator"]


def test_fails_when_forbidden_tool_ran():
    result = score(
        task(forbid_tools=["send_mail"]), answer="ok", tools_used=["send_mail"]
    )
    assert result["passed"] is False
    assert result["forbidden_used"] == ["send_mail"]


def test_substring_match_is_case_insensitive():
    result = score(task(expect_substrings=["CALCULATOR"]), answer="opened calculator", tools_used=[])
    assert result["passed"] is True


def test_load_tasks_reads_the_shipped_suite():
    tasks = load_tasks("evals/tasks.yaml")
    assert len(tasks) >= 8
    for t in tasks:
        assert t["id"] and t["prompt"]
