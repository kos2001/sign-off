# VC SpyGlass / Jasper CDC·RDC 결과 가져오기

프로젝트의 **보고서 가져오기 → VC SpyGlass / Jasper CDC·RDC**에서 수집기가 만든
`signoff/commercial-cdc-rdc/v1` JSON을 미리 보고 저장한다. 지원 툴과 범위는 Synopsys의
[VC SpyGlass CDC](https://www.synopsys.com/verification/static-and-formal-verification/vc-spyglass/vc-spyglass-cdc.html),
[VC SpyGlass RDC](https://www.synopsys.com/verification/static-and-formal-verification/vc-spyglass/vc-spyglass-rdc.html),
Cadence의 [Jasper CDC App](https://www.cadence.com/en_US/home/tools/system-design-and-verification/formal-and-static-verification/jasper-verification-platform/jaspergold-clock-domain-crossing-app.html)에 맞춘다.

```json
{
  "format": "signoff/commercial-cdc-rdc/v1",
  "tool": "Synopsys VC SpyGlass CDC/RDC",
  "tool_version": "T-2025.06",
  "top": "CHIP",
  "status": "violations",
  "summary": {"clock_domains": 4, "reset_domains": 2, "cdc_crossings": 12, "rdc_crossings": 3},
  "findings": [{"kind": "cdc", "rule": "CDC_UNSYNC_DATA", "name": "status crossing", "severity": "critical", "source_object": "u_src/status_q", "destination_object": "u_dst/status_d", "source_domain": "clk_a", "destination_domain": "clk_b", "message": "Unsynchronized data crossing."}]
}
```

`tool`은 `Synopsys VC SpyGlass CDC/RDC` 또는 `Cadence Jasper CDC`다. 판정은 `clean`,
`violations`, `error`이며 clean 결과에 error/critical finding을 허용하지 않는다. finding kind는
`cdc`, `rdc`, `constraint`, `synchronizer`, `protocol`, `reconvergence`다. 보고서 내부의 waiver나
분류를 서비스 승인으로 변환하지 않는다.

API는 `POST /projects/{id}/imports/commercial-cdc/preview`,
`POST /projects/{id}/imports/commercial-cdc`, `GET /runs/{id}/cdc-findings`다. 원본 SHA-256,
정규화 finding, 제출 신원을 보존하고 error/critical finding을 차단 위반으로 만든다.

서명 없는 clean 보고서는 `incomplete`다. HMAC 증명이 clock/reset, 제약, 계층, 구조·기능 분석,
CDC·RDC 분석과 finding 전체 범위를 결합한 경우에만 clean 결과를 `passed`로 인정한다. RTL 게이트는
회귀·STA와 별도로 CDC/RDC 근거를 요구한다. 증명은 등록 수집기의 선언이며 벤더 서명, 실제 입력이나
호스트 무결성을 증명하지 않는다. 가져오기·판정·탐색에는 AI가 개입하지 않는다.
