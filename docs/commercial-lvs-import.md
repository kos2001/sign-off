# Calibre / Pegasus LVS 결과 가져오기

프로젝트의 **보고서 가져오기 → Calibre / Pegasus LVS**에서 수집기가 만든
`signoff/commercial-lvs/v1` JSON을 미리 보고 저장한다. 서버는 벤더 텍스트를 추측하지 않고
명시된 필드와 상호 모순을 검증한다.

```json
{
  "format": "signoff/commercial-lvs/v1",
  "tool": "Siemens Calibre nmLVS",
  "tool_version": "2025.2",
  "layout_top": "CHIP",
  "schematic_top": "CHIP",
  "status": "mismatched",
  "summary": {"layout_devices": 120, "schematic_devices": 119, "layout_nets": 88, "schematic_nets": 88},
  "mismatches": [{"kind": "missing_device", "name": "M42", "severity": "error", "layout_object": null, "schematic_object": "M42", "message": "missing in layout"}]
}
```

`tool`은 `Siemens Calibre nmLVS` 또는 `Cadence Pegasus LVS`다. `status`는 `matched`,
`mismatched`, `error` 중 하나이며 matched 결과에는 불일치나 서로 다른 요약 개수를 허용하지
않는다. error 결과는 `error_message`가 필요하다. 불일치 kind는 `open`, `short`,
`missing_device`, `extra_device`, `device_mismatch`, `port_mismatch`, `property_mismatch`이고
심각도는 `error` 또는 `critical`이다.

API는 `POST /projects/{id}/imports/commercial-lvs/preview`,
`POST /projects/{id}/imports/commercial-lvs`, `GET /runs/{id}/lvs-mismatches`다. 저장 시 원본과
SHA-256, 정규화된 요약·불일치, 제출 신원을 불변 근거로 보존하고 차단 위반을 만든다. 탐색 화면은
kind와 이름·객체·메시지 검색 및 페이지 이동을 지원한다.

서명 없는 matched 보고서는 제출된 결과만 보존하므로 `incomplete`이며 게이트를 열지 않는다.
[신뢰된 수집기 커버리지 증명](coverage-attestation.md)이 룰덱·레이아웃·회로도·계층·추출·비교·
finding 범위를 모두 결합하고 불일치가 없을 때만 `passed`가 된다. routing과 final은 DRC와 LVS를
각각 요구한다. HMAC은 등록 수집기의 선언을 확인하지만 벤더 서명, 실제 입력 파일, 라이선스 또는
호스트 무결성을 증명하지 않는다. 가져오기·판정·탐색에는 AI가 개입하지 않는다.
