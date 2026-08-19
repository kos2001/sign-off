import httpx
import pytest

from app.hermes import (
    ROLES,
    HermesClient,
    Settings,
    _extract_json,
    a1_should_review,
    a2_should_review,
    a3_should_review,
    a5_gate_needs_synthesis,
)


def test_roles_cover_the_six_designed_agents():
    assert set(ROLES) == {"a1_rtl", "a2_timing", "a3_power_ir", "a4_waiver", "a5_synth", "v_verify"}
    for role in ROLES.values():
        assert role.system_prompt.strip()
        assert role.trigger_ko.strip()


def test_extract_json_plain():
    assert _extract_json('{"verdict": "SIGNED_OFF"}') == {"verdict": "SIGNED_OFF"}


def test_extract_json_fenced():
    text = "```json\n{\"a\": 1}\n```"
    assert _extract_json(text) == {"a": 1}


def test_extract_json_no_object_raises():
    with pytest.raises(ValueError):
        _extract_json("no json here")


@pytest.mark.anyio
async def test_chat_posts_role_prompt_and_session_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = request.headers
        seen["body"] = request.read()
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = HermesClient(
        Settings(base_url="http://test/v1", api_key="k", model="sign-off"),
        transport=httpx.MockTransport(handler),
    )
    result = await client.chat(ROLES["a5_synth"], "hello", session_id="s1")

    assert result == "ok"
    assert seen["headers"]["x-hermes-session-id"] == "s1"
    assert seen["headers"]["authorization"] == "Bearer k"
    import json as _json

    body = _json.loads(seen["body"])
    assert body["messages"][0]["content"] == ROLES["a5_synth"].system_prompt
    assert body["messages"][1]["content"] == "hello"


@pytest.mark.anyio
async def test_chat_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": {"message": "slow down"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    client = HermesClient(
        Settings(base_url="http://test/v1", api_key="k", model="sign-off"),
        transport=httpx.MockTransport(handler),
        retries=2,
    )
    # avoid real sleep in the retry backoff
    import app.hermes as hermes_mod

    orig_sleep = hermes_mod.asyncio.sleep
    hermes_mod.asyncio.sleep = lambda _s: orig_sleep(0)
    try:
        result = await client.chat(ROLES["v_verify"], "hi", session_id="s2")
    finally:
        hermes_mod.asyncio.sleep = orig_sleep

    assert result == "done"
    assert calls["n"] == 2


@pytest.mark.anyio
async def test_chat_raises_on_exhausted_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = HermesClient(
        Settings(base_url="http://test/v1", api_key="k", model="sign-off"),
        transport=httpx.MockTransport(handler),
        retries=0,
    )
    with pytest.raises(RuntimeError, match="hermes 호출 실패"):
        await client.chat(ROLES["a1_rtl"], "hi", session_id="s3")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_a1_triggers_only_on_a_violation():
    assert a1_should_review({"rules": [{"status": "pass"}, {"status": "violation"}]})
    assert not a1_should_review({"rules": [{"status": "pass"}]})
    assert not a1_should_review({"rules": []})


def test_a2_triggers_only_on_negative_merged_wns():
    assert a2_should_review({"merged": {"wns_ps": -30.0}})
    assert not a2_should_review({"merged": {"wns_ps": 0.0}})
    assert not a2_should_review({"merged": {"wns_ps": 120.0}})


def test_a3_triggers_on_ir_hotspot_or_high_glitch_share():
    assert a3_should_review(ir_drop_result={"passed": False})
    assert not a3_should_review(ir_drop_result={"passed": True})
    assert a3_should_review(glitch_result={"glitch_share": 0.5})
    assert not a3_should_review(glitch_result={"glitch_share": 0.1})
    assert not a3_should_review()


def test_a5_triggers_only_when_gate_not_ready():
    assert a5_gate_needs_synthesis({"ready": False})
    assert not a5_gate_needs_synthesis({"ready": True})
