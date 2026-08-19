import httpx
import pytest

from app.hermes import ROLES, HermesClient, Settings, _extract_json


def test_roles_cover_the_six_designed_agents():
    assert set(ROLES) == {"a1_rtl", "a2_timing", "a3_power_ir", "a4_waiver", "a5_synth", "v_verify"}
    for role in ROLES.values():
        assert role.system_prompt.strip()


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
