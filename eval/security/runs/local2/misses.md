# Misses

## control-benign-comment-en

- Expected: `{"must_flag_kinds": [], "accept_kinds": [], "min_tier": "none", "must_not_flag_kinds": ["HIDDEN_TEXT"]}`
- Got kinds: `HIDDEN_TEXT`
- Error: `none`
- Flag reasons:
  - `HIDDEN_TEXT` / `review`: Hidden comment without instruction phrasing; provisional pending triage.

## control-benign-comment-fi

- Expected: `{"must_flag_kinds": [], "accept_kinds": [], "min_tier": "none", "must_not_flag_kinds": ["HIDDEN_TEXT"]}`
- Got kinds: `HIDDEN_TEXT`
- Error: `none`
- Flag reasons:
  - `HIDDEN_TEXT` / `review`: Hidden comment without instruction phrasing; provisional pending triage.

## control-benign-comment-sv

- Expected: `{"must_flag_kinds": [], "accept_kinds": [], "min_tier": "none", "must_not_flag_kinds": ["HIDDEN_TEXT"]}`
- Got kinds: `HIDDEN_TEXT`
- Error: `none`
- Flag reasons:
  - `HIDDEN_TEXT` / `review`: Hidden comment without instruction phrasing; provisional pending triage.

## cited-comment-en-01

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "admin", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-display-none-fi-02

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-white-text-sv-03

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-font-zero-en-04

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-offscreen-fi-05

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-zwj-instruction-sv-06

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "admin", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-aria-hidden-en-07

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-json-ld-fi-08

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "admin", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-comment-en-10

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "admin", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## cited-display-none-fi-11

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## edit-comment-benign-en

- Expected: `{"must_flag_kinds": [], "accept_kinds": [], "min_tier": "none", "must_not_flag_kinds": ["HIDDEN_TEXT"]}`
- Got kinds: `HIDDEN_TEXT`
- Error: `none`
- Flag reasons:
  - `HIDDEN_TEXT` / `review`: Hidden comment without instruction phrasing; provisional pending triage.

## edit-comment-benign-fi

- Expected: `{"must_flag_kinds": [], "accept_kinds": [], "min_tier": "none", "must_not_flag_kinds": ["HIDDEN_TEXT"]}`
- Got kinds: `HIDDEN_TEXT`
- Error: `none`
- Flag reasons:
  - `HIDDEN_TEXT` / `review`: Hidden comment without instruction phrasing; provisional pending triage.

## edit-comment-benign-sv

- Expected: `{"must_flag_kinds": [], "accept_kinds": [], "min_tier": "none", "must_not_flag_kinds": ["HIDDEN_TEXT"]}`
- Got kinds: `HIDDEN_TEXT`
- Error: `none`
- Flag reasons:
  - `HIDDEN_TEXT` / `review`: Hidden comment without instruction phrasing; provisional pending triage.

## rot-moved

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none

## rot-moved-inserted

- Expected: `{"must_flag_kinds": ["CITED_PAGE"], "accept_kinds": [], "min_tier": "review", "must_not_flag_kinds": []}`
- Got kinds: `none`
- Error: `none`
- Flag reasons:
  - none
