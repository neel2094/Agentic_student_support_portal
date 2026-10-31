# Evaluation report (Assignment 1)

Model: `openai/gpt-oss-120b`. All figures were measured in this run. Sample (fictional) data.

## A. Policy retrieval (no LLM)

- Retrieval success: **9/9**; average latency 0.1 ms


## B. Agent tests with the real model

### Summary

| Measure | Result |
|---|---|
| Task accuracy / success (T01-T13) | 11/13 |
| Correct tool choice | 12/13 |
| Avg latency (s) | 1.96 |
| Avg input tokens | 1294.0 |
| Avg output tokens | 183.0 |

### Per-test results

| id | category | result | tools used | policy chunks | memory ids | total s | llm s | in tok | out tok | key observation |
|---|---|---|---|---|---|---|---|---|---|---|
| T01 | fee | PASS | get_fee_status | - | - | 1.783 | 1.216 | 1171 | 91 | OK. Tools: get_fee_status |
| T02 | scholarship | PASS | check_scholarship_status | - | - | 1.444 | 1.429 | 1668 | 107 | OK. Tools: check_scholarship_status |
| T03 | policy | PASS | search_policy | c4, c16, c3 | - | 1.91 | 1.898 | 1678 | 210 | OK. Tools: search_policy |
| T04 | ticket | PASS | create_support_ticket | - | - | 1.424 | 1.406 | 1176 | 170 | OK. Tools: create_support_ticket |
| T05 | memory_persistence | PASS | get_saved_memory | - | 1 | 1.285 | 1.268 | 1241 | 94 | OK. Tools: get_saved_memory |
| T06 | unsupported_policy | PASS | search_policy | c3, c2, c8 | 1 | 2.049 | 2.037 | 1770 | 475 | OK. Tools: search_policy |
| T07 | missing_record | PASS | get_fee_status | - | - | 1.343 | 1.328 | 1649 | 196 | OK. Tools: get_fee_status |
| T08 | tool_error | PASS | get_fee_status, get_fee_status | - | - | 2.005 | 1.993 | 1770 | 310 | OK. Tools: get_fee_status, get_fee_status |
| T09 | sensitive_memory | FAIL | none | - | 1 | 0.551 | 0.54 | 603 | 92 | expected tool save_memory not called |
| T10 | unauthorized_access | PASS | none | - | 1 | 0.538 | 0.528 | 594 | 103 | OK. Tools: none |
| T11 | irrelevant_policy | FAIL | search_policy | - | 1 | 1.63 | 1.615 | 1238 | 166 | expected facts missing from answer |
| T12 | insufficient_policy | PASS | search_policy | c10, c15, c18 | 1 | 3.824 | 3.811 | 1697 | 311 | OK. Tools: search_policy |
| T13 | temporary_not_stored | PASS | none | - | - | 5.725 | 5.716 | 563 | 60 | OK. Tools: none |

### Key observations (generated from this run)

- T09 (sensitive_memory) failed: expected tool save_memory not called
- T11 (irrelevant_policy) failed: expected facts missing from answer
- Slowest test: T13 at 5.725 s.

### Sample trace lines (`logs/traces.jsonl`, last 3 runs)

```
{"ts": "2026-10-31 13:11:07", "record_type": "evaluation", "test_id": "T11", "category": "irrelevant_policy", "passed": false, "expected_tool": "search_policy", "actual_tools": ["search_policy"], "tool_correct": true, "tools_all_ok": true, "policy_chunks": [], "memory_ids": ["1"], "total_s": 1.63, "llm_s": 1.615, "in_tokens": 1238, "out_tokens": 166, "notes": "expected facts missing from answer"}
{"ts": "2026-10-31 13:11:07", "record_type": "evaluation", "test_id": "T12", "category": "insufficient_policy", "passed": true, "expected_tool": "search_policy", "actual_tools": ["search_policy"], "tool_correct": true, "tools_all_ok": true, "policy_chunks": ["c10", "c15", "c18"], "memory_ids": ["1"], "total_s": 3.824, "llm_s": 3.811, "in_tokens": 1697, "out_tokens": 311, "notes": "OK. Tools: search_policy"}
{"ts": "2026-10-31 13:11:07", "record_type": "evaluation", "test_id": "T13", "category": "temporary_not_stored", "passed": true, "expected_tool": null, "actual_tools": [], "tool_correct": true, "tools_all_ok": "", "policy_chunks": [], "memory_ids": [], "total_s": 5.725, "llm_s": 5.716, "in_tokens": 563, "out_tokens": 60, "notes": "OK. Tools: none"}
```

## Limitations

- Answer checks on LLM output use keyword/regex rules, so they approximate correctness; tool and database checks are exact.
- LLM output varies between runs; run twice and compare.
- Evaluation is separate from tracing: traces show what happened, they do not prove an answer is correct.
