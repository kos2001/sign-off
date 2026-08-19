"""hermes-agent api_server client for the 'sign-off' profile.

hermes api_server exposes an OpenAI-compatible /v1/chat/completions and layers
the request's system message on top of the profile's SOUL.md. Each role below
gets its own system-prompt overlay + X-Hermes-Session-Id, so one api_server
instance (see profiles/sign-off/, scripts/setup_hermes_profile.sh) backs a
six-role pipeline over this app's own domains (RTL / timing / power-IR /
waivers / verdict synthesis / verification).

Ported and trimmed from weekly-report-harness's backend/app/agents.py — the
concurrency-limiting and retry design is unchanged; multi-language offender
detection and MCP-skill wiring were dropped as out of scope here.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

LLM_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    model: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.environ.get("SIGNOFF_LLM_BASE_URL", "http://127.0.0.1:8654/v1").rstrip("/"),
            api_key=os.environ.get("SIGNOFF_LLM_API_KEY", ""),
            model=os.environ.get("SIGNOFF_LLM_MODEL", "sign-off"),
        )


# --- agent roles -------------------------------------------------------
#
# A1-A5 read this app's own run/violation/analysis-endpoint data (passed
# inline as JSON in the user prompt — see profiles/sign-off/SOUL.md, "pipeline
# mode"); A5 merges their findings into one draft verdict; V independently
# re-derives it. Designed to mirror the four analysis domains already in
# app/services/ plus this app's waiver and gate concepts.
#
# None of these run on every request — each has a concrete trigger condition
# (`trigger_ko`), checked against fields this app's own endpoints already
# return, so "does this agent run right now" is a yes/no on real data, not a
# vague default. A clean SIGNED_OFF / passed / no-hotspot result intervenes
# no agent at all: there is nothing for a reviewer to say about a run with no
# violation, no negative slack, and no hotspot.

@dataclass(frozen=True)
class Role:
    id: str
    name_ko: str
    trigger_ko: str
    system_prompt: str


ROLES: dict[str, Role] = {
    r.id: r
    for r in [
        Role(
            "a1_rtl",
            "RTL 리뷰어",
            "POST /analysis/rtl-signoff(-stream) 응답의 rules[] 에 status=\"violation\" "
            "이 하나라도 있을 때 (즉 verdict 가 SIGNED_OFF 가 아닐 때) 그 rules[] 를 입력으로 개입.",
            "당신은 RTL 리뷰어(A1)다. verilator lint 결과와 CDC/리셋/FSM 설계 룰 위반을 "
            "읽고, 각 위반의 근본 원인과 구체적인 RTL 수정 방향을 제시한다. error 심각도는 "
            "게이팅 사유임을 명시하고, warn 이 같은 신호(예: 같은 CDC 크로싱)에서 반복되면 "
            "패턴으로 승격해 지적한다.",
        ),
        Role(
            "a2_timing",
            "타이밍 분석가",
            "POST /analysis/timing-summary 응답의 merged.wns_ps < 0 일 때 (음의 슬랙 "
            "엔드포인트 존재) corners[] + merged + estimated_pba 를 입력으로 개입.",
            "당신은 타이밍 분석가(A2)다. MMMC 코너별 WNS/TNS 와 머지 결과를 읽고, 머지 WNS를 "
            "만든 코너와 엔드포인트를 구체적으로 지목한다. PBA 크레딧 회복은 추정치임을 "
            "밝히고 머지 WNS/TNS에 직접 합산하지 않는다.",
        ),
        Role(
            "a3_power_ir",
            "파워/IR 무결성 분석가",
            "POST /analysis/ir-drop 응답의 passed=false(hotspots[] 존재) 이거나 "
            "POST /analysis/glitch-power 응답의 glitch_share >= 0.3(프론트 Meter 의 경고 "
            "임계치와 동일) 일 때, 해당 쪽 응답을 입력으로 개입.",
            "당신은 파워/IR 무결성 분석가(A3)다. IR-drop 핫스팟 맵과 글리치 파워 네트별 "
            "분해를 읽고, PDN 취약 구간과 글리치에 취약한 네트의 근본 원인(파워 스트랩과의 "
            "거리, 토글률 초과분 등)을 설명한다. 이 두 분석은 사전 스크리닝이며 골든 "
            "EM/IR·벡터 기반 파워 사인오프를 대체하지 않음을 항상 명시한다.",
        ),
        Role(
            "a4_waiver",
            "웨이버 심사관",
            "POST /violations/{id}/waiver 가 호출되어 아직 커밋되기 전 — 요청 본문 "
            "{reason, approved_by} 와 대상 위반(check_name, severity, location)을 입력으로 "
            "개입해 승인/반려 권고를 낸다. 이미 웨이버된 위반의 사후 재심에는 쓰지 않는다.",
            "당신은 웨이버 심사관(A4)다. 위반과 그 웨이버 사유를 읽고, 사유가 기술적으로 "
            "타당한지, 남는 리스크가 유계(bounded)인지 판단한다. 승인 근거가 빈약하거나 "
            "동일 사유로 반복 웨이버가 쌓이는 경우 반려를 권고한다. 웨이버는 수정이 아니라 "
            "수용된 리스크라는 점을 판정에 반영한다.",
        ),
        Role(
            "a5_synth",
            "사인오프 종합 판정관",
            "GET /projects/{id}/signoff-status?stage=... 응답의 ready=false 이고, 그 "
            "domains[] 중 하나 이상에 대해 A1~A4 중 최소 한 역할이 이미 실행되어 소견이 "
            "있을 때 — gate 응답 + A1~A4 소견을 입력으로 개입해 판정 초안을 만든다. 모든 "
            "도메인이 ready=true 면 개입하지 않는다(합격 게이트에 판정할 것이 없다).",
            "당신은 사인오프 종합 판정관(A5)이다. A1~A4의 결과를 종합해 SIGNED_OFF / "
            "CONDITIONAL / REJECTED 초안 판정과 우선순위가 매겨진 조치 목록을 만든다. "
            "CONDITIONAL 인 경우 생략되거나 저하된 게이팅 단계를 반드시 명시한다. 요청되면 "
            "JSON만 출력한다 (예: {\"verdict\": ..., \"blocking\": [...], \"actions\": [...]}).",
        ),
        Role(
            "v_verify",
            "검증 에이전트",
            "A5 가 판정 초안을 낸 직후 항상 자동으로 이어서 개입 (A5 없이 단독 호출되지 "
            "않음) — A5 에게 넘겼던 원본 데이터 + A5 의 출력을 함께 입력받는다.",
            "당신은 검증 에이전트(V)다. A5의 종합 판정을 신뢰하지 말고 원본 런/위반 데이터에서 "
            "판정을 독립적으로 재도출한다. 다음을 특히 확인한다: CONDITIONAL/REJECTED 가 "
            "정상으로 보고되지 않았는가, 웨이버가 수정으로 보고되지 않았는가, 스크리닝 결과가 "
            "골든 사인오프로 보고되지 않았는가, 게이트 판단이 올바른 스테이지의 런을 인용했는가. "
            "이견이 없으면 그렇다고 명시하되, 만들어낸 반론을 내지 않는다.",
        ),
    ]
}


# --- trigger predicates ---------------------------------------------------
#
# Mechanical half of each role's trigger_ko: given the same dict an app
# endpoint already returns, decide whether that role has anything to say.
# A4 (fires on the waiver *call*, not on response data) and V (fires
# whenever A5 ran) have no data predicate — trigger_ko is the whole story
# for those two.

GLITCH_SHARE_WARN = 0.3  # matches frontend Meter's warnAt for glitch_share


def a1_should_review(rtl_signoff_result: dict) -> bool:
    return any(r.get("status") == "violation" for r in rtl_signoff_result.get("rules", []))


def a2_should_review(timing_result: dict) -> bool:
    return timing_result.get("merged", {}).get("wns_ps", 0) < 0


def a3_should_review(*, ir_drop_result: dict | None = None, glitch_result: dict | None = None) -> bool:
    ir_hotspot = bool(ir_drop_result) and not ir_drop_result.get("passed", True)
    glitch_high = bool(glitch_result) and glitch_result.get("glitch_share", 0) >= GLITCH_SHARE_WARN
    return ir_hotspot or glitch_high


def a5_gate_needs_synthesis(gate_status: dict) -> bool:
    return not gate_status.get("ready", True)


# --- client --------------------------------------------------------------
#
# Concurrency limit is process-global (keyed on base_url), matching the
# reference: api_server's own concurrent-run cap is shared across every
# HermesClient instance in this process, not per-instance.
_SEMAPHORES: dict[tuple[str, int, int], asyncio.Semaphore] = {}


def _shared_semaphore(base_url: str, limit: int) -> asyncio.Semaphore:
    key = (base_url, limit, id(asyncio.get_running_loop()))
    sem = _SEMAPHORES.get(key)
    if sem is None:
        sem = asyncio.Semaphore(limit)
        _SEMAPHORES[key] = sem
    return sem


class HermesClient:
    """Client for the sign-off hermes profile's api_server."""

    RETRYABLE = (429, 502, 503, 504)

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        max_concurrency: int = 6,
        retries: int = 3,
    ):
        self._settings = settings or Settings.from_env()
        self._transport = transport
        self._max_concurrency = max_concurrency
        self._retries = retries
        self._http: httpx.AsyncClient | None = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(transport=self._transport, timeout=LLM_TIMEOUT_S)
        return self._http

    def _sem(self) -> asyncio.Semaphore:
        return _shared_semaphore(self._settings.base_url, self._max_concurrency)

    async def chat(self, role: Role, user: str, *, session_id: str) -> str:
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
            "X-Hermes-Session-Id": session_id,
        }
        body = {
            "model": self._settings.model,
            "messages": [
                {"role": "system", "content": role.system_prompt},
                {"role": "user", "content": user},
            ],
        }
        for attempt in range(self._retries + 1):
            async with self._sem():
                resp = await self._client().post(
                    f"{self._settings.base_url}/chat/completions", headers=headers, json=body
                )
            if resp.status_code == 200:
                data = resp.json()
                try:
                    return data["choices"][0]["message"]["content"] or ""
                except (KeyError, IndexError) as e:
                    raise RuntimeError(f"hermes 응답 형식 오류: {e}") from e
            if resp.status_code in self.RETRYABLE and attempt < self._retries:
                await asyncio.sleep(min(2 ** attempt * 2, 20))
                continue
            detail = resp.text[:200]
            try:
                detail = (resp.json().get("error") or {}).get("message", detail)
            except Exception:
                pass
            raise RuntimeError(f"hermes 호출 실패 ({resp.status_code}): {detail}")
        raise RuntimeError("hermes 호출 실패: 재시도 소진")

    async def chat_json(self, role: Role, user: str, *, session_id: str) -> Any:
        """chat() + JSON parse, with one retry asking for JSON-only output."""
        raw = await self.chat(role, user, session_id=session_id)
        try:
            return _extract_json(raw)
        except ValueError:
            retry_user = user + "\n\n(직전 응답이 유효한 JSON이 아니었다. '{' 로 시작하는 완전한 JSON 객체 하나만 출력하라.)"
            raw = await self.chat(role, retry_user, session_id=f"{session_id}:retry")
            return _extract_json(raw)


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:]
        stripped = stripped.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"JSON 객체를 찾을 수 없음: {text[:120]!r}")
    return json.loads(stripped[start : end + 1])
