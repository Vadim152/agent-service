from intent.chat_intent import ChatIntentParser


def test_parse_russian_autotest_message_with_jira_key() -> None:
    parser = ChatIntentParser()

    intent = parser.parse("создай автотест SCBC-T123")

    assert intent.kind == "run_trigger"
    assert intent.plugin == "testgen"
    assert intent.jira_key == "SCBC-T123"
    assert intent.should_start_run() is True


def test_parse_autotest_message_extracts_target_path_and_language() -> None:
    parser = ChatIntentParser()

    intent = parser.parse(
        "generate autotest SCBC-T7 targetPath=src/test/resources/features/SCBC-T7.feature language=en"
    )

    assert intent.target_path == "src/test/resources/features/SCBC-T7.feature"
    assert intent.language == "en"
    assert intent.normalized_input["jiraKey"] == "SCBC-T7"
