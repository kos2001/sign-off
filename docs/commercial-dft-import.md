# TestMAX / Tessent / Modus DFT 결과 가져오기

프로젝트의 **보고서 가져오기 → TestMAX / Tessent / Modus DFT**에서 수집기가 만든
`signoff/commercial-dft/v1` JSON을 미리 보고 저장한다. 지원 범위는
[Synopsys TestMAX ATPG](https://www.synopsys.com/implementation-and-signoff/test-automation/testmax-atpg.html),
[Cadence Modus DFT](https://www.cadence.com/en_US/home/tools/digital-design-and-signoff/test-automation/modus-test.html)와
Siemens Tessent TestKompress의 scan/ATPG 결과다.

```json
{"format":"signoff/commercial-dft/v1","tool":"Synopsys TestMAX ATPG","tool_version":"T-2025.06","top":"CHIP","status":"passed","summary":{"scan_chains":32,"scan_cells":10000,"broken_chains":0,"dft_rule_violations":0},"fault_models":[{"name":"stuck_at","total_faults":1000,"detected_faults":900,"untestable_faults":100,"aborted_faults":0,"coverage_percent":100.0,"required_coverage_percent":99.0,"pattern_count":120}],"findings":[]}
```

fault model은 `stuck_at`, `transition`, `bridging`, `cell_aware`, `path_delay`를 지원한다. 서버는
`detected / (total - untestable) × 100`을 다시 계산하고 제출 coverage와 1e-6 이내로 일치하는지
검사한다. passed 결과에는 broken chain, DFT rule 위반, aborted fault, coverage 미달 또는
error/critical finding이 없어야 한다.

API는 `POST /projects/{id}/imports/commercial-dft/preview`,
`POST /projects/{id}/imports/commercial-dft`, `GET /runs/{id}/dft-findings`다. 서명 없는 passed
보고서는 `incomplete`다. HMAC 증명이 DFT insertion, scan, rule check, fault model, ATPG, fault
simulation, coverage, pattern validation과 finding 전체 범위를 결합해야만 `passed`가 된다.
synthesis와 final 게이트는 DFT를 별도 필수 도메인으로 요구한다. AI는 계산·판정·탐색에 개입하지 않는다.
