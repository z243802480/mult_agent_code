from asteria_runtime.core.chat_intent_policy import ChatIntentPolicy


def test_chat_intent_policy_classifies_debug_and_progress_questions() -> None:
    policy = ChatIntentPolicy()

    assert policy.classify("请显示调试细节：run_id 和 model route 是什么？") == (
        "debug_question"
    )
    assert policy.classify("当前任务到什么状态了？需要我执行什么吗？") == (
        "next_step_question"
    )
    assert policy.classify("再次评估研发计划") == "plan_question"
    assert policy.classify("解释一下 schema validation 的作用") == "ordinary_chat"
