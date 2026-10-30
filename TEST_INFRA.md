# Test Infrastructure & Verification Specification

**Project**: 6-Role Multi-Agent Advertising Campaign Management System (`ai_target`)  
**Document**: `TEST_INFRA.md`  
**Classification**: Test Architecture, Methodology & Quality Gates  
**Integrity Mode**: Strict Requirement-Driven Offline Verification  

---

## 1. Test Philosophy

The testing architecture for the Multi-Agent Advertising Campaign System adheres to four foundational pillars:

1. **Opaque-Box Requirement-Driven Verification**:
   Tests are authored strictly against the authoritative requirements (`ORIGINAL_REQUEST.md`), architectural specifications (`PROJECT.md`), and technical contracts (`spec_report.md` & `workflow_guardrails_report.md`). Tests verify external observable behavior, state transitions, API payload compliance, mathematical formulas, and moderation rules rather than private internal implementation details.

2. **Hermetic Zero-Network Isolation**:
   No external HTTP requests, ad platform API calls, socket connections, or live financial transactions are permitted during test execution. All platform interactions (Meta Graph API, TikTok Marketing API v2.0, Adsly.Pro REST, AdsGram, and Click.ru/eLama) are verified against deterministic mock adapters and static JSON response fixtures. An autouse socket-blocking harness intercepts and terminates any outbound network connection attempts.

3. **Deterministic State-Driven Testing**:
   The multi-agent workflow revolves around the immutable lifecycle of the Pydantic-validated `CampaignState`. Every test sets up its own isolated state, executes an explicit action or transition, verifies post-conditions, and cleans up any runtime artifacts without inter-test dependencies or order sensitivity.

4. **Adversarial & Boundary Rigor**:
   Tests systematically stress boundary conditions: 0 and negative budgets, 159/160/161 character thresholds in Telegram Ads, raw URL moderation checks, 0.09 vs 0.10 TON bid floors, exact $1.5\times$ target CPA spend triggers, frequency thresholds ($2.79$ vs $2.81$), and hard gate payment verification (`payment_verified: false` vs `true`).

---

## 2. Feature Inventory Coverage Matrix

| Req # | Feature Description | Milestone | Contract Module | Test Tier & Primary Test File | Target Coverage |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **R1** | **Supervisor Agent & Intake Dialogue**: CLI and Telegram bot intake dialogue, collection of 4 core parameters (product, GEO, goal, budget), orchestration loop, payment gatekeeping. | M1, M4 | `ai_target.agents.supervisor` | Tier 1, 2, 4<br>`test_tier1_feature_coverage.py`<br>`test_tier2_boundary_corner.py`<br>`test_tier4_real_world.py` | 100% of dialogue states, gate checks, and parameter extractions. |
| **R2** | **Strategist & Billing Agent**: 12% service commission calculation, 3–6% agency cashback (Click.ru, eLama), platform minimum budget enforcement (>=10 USDT/day Reels/AdsGram, CPM >=0.1 TON Adsly). | M2 | `ai_target.agents.strategist` | Tier 1, 2, 3<br>`test_tier1_feature_coverage.py`<br>`test_tier2_boundary_corner.py`<br>`test_tier3_cross_feature.py` | 100% mathematical accuracy on financial formulas and allocation floors. |
| **R3** | **Creative Copywriter Agent**: A/B copy generation, platform moderation (Telegram Ads <=160 chars, no raw links; RichAds push; Reels hooks; Telega.in seeds), UTM tagging engine. | M1, M2 | `ai_target.agents.copywriter`<br>`ai_target.utils.moderation`<br>`ai_target.utils.utm` | Tier 1, 2, 3<br>`test_tier1_feature_coverage.py`<br>`test_tier2_boundary_corner.py`<br>`test_tier3_cross_feature.py` | 100% character boundary rules, URL parsing, and UTM key injection. |
| **R4** | **Technical Executor Agents**: Meta (Campaign -> AdSet -> Ad in PAUSED), TikTok Marketing API v2.0 (DISABLE status), competitor channel parsing simulation, Adsly.Pro TON bidding. | M3 | `ai_target.agents.meta_tiktok`<br>`ai_target.agents.telegram_ecosystem`<br>`ai_target.adapters.*` | Tier 1, 2, 3<br>`test_tier1_feature_coverage.py`<br>`test_tier2_boundary_corner.py`<br>`test_tier3_cross_feature.py` | 100% schema validation for platform payloads and sandbox adapters. |
| **R5** | **Analytics & Guardrails Agent**: 2-hour telemetry simulation, Meta learning phase tracking (50 events), kill-switch (spend >= 1.5x CPA with 0 conversions), creative fatigue (>2.8 frequency), dynamic TON bids. | M4 | `ai_target.agents.analytics` | Tier 1, 2, 4<br>`test_tier1_feature_coverage.py`<br>`test_tier2_boundary_corner.py`<br>`test_tier4_real_world.py` | 100% guardrail triggers, boundary tolerances, and dynamic bid calculations. |
| **R6** | **CampaignState Schema & Lifecycle**: Pydantic v2 schemas (`ClientBrief`, `Financials`, `MediaPlan`, `Creatives`, `LiveDeployments`, `PerformanceMetrics`), FSM transitions, payment gate. | M1 | `ai_target.state.models`<br>`ai_target.state.transitions` | Tier 1, 2, 3, 4<br>All test files across Tiers 1–4 | 100% schema constraints, serialization round-trip, transition rules. |

---

## 3. Four-Tier Testing Methodology

The verification suite is structured into four progressive tiers:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Tier 4: Real-World Scenarios                          │
│     Full campaign lifecycle: Intake -> Strategy -> Copy -> Execution ->     │
│        Live -> 2-hour monitoring -> Kill-switch / Fatigue / Completion      │
├─────────────────────────────────────────────────────────────────────────────┤
│                    Tier 3: Cross-Feature Interactions                       │
│    Pairwise combinations: State machine + Billing, Copy + UTM injection,    │
│            Executor payloads + Sandbox adapters, Multi-currency             │
├─────────────────────────────────────────────────────────────────────────────┤
│                    Tier 2: Boundary & Corner Cases                          │
│   0/Negative budgets, 159/160/161 chars, 0.09/0.10 TON, 1.49x/1.50x CPA,   │
│         Frequency 2.79/2.81, 49/50 conversions, Payment gate bypass         │
├─────────────────────────────────────────────────────────────────────────────┤
│                    Tier 1: Feature Coverage (Isolation)                     │
│    >=5 tests per feature (R1 to R6): Happy paths, parameter extractions,    │
│          mathematical formulas, moderation checks, payload schemas          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Tier 1: Feature Coverage (Contract & Unit Level)
- **Scope**: Verifies individual functions, components, and schemas in isolation.
- **Criteria**: Minimum 5 dedicated test cases per requirement (R1 through R6), totaling $\ge 30$ tests.
- **File**: `tests/e2e/test_tier1_feature_coverage.py`
- **Focus**:
  - R1: Intake parsing, brief capture, goal normalization, dialogue state progression.
  - R2: 12% commission, net media spend, 3-6% cashback, platform budget allocation.
  - R3: Copy generation, character limits, raw link prohibition, UTM tagging.
  - R4: Meta PAUSED hierarchy, TikTok DISABLE status, channel parsing, Adsly.Pro bids.
  - R5: 2h interval evaluation, 50-event learning phase, kill-switch, fatigue, dynamic bids.
  - R6: State validation, transition rules, model serialization, payment gate enforcement.

### Tier 2: Boundary & Corner Cases (Stress & Invariant Level)
- **Scope**: Stresses numerical limits, boundary thresholds, formatting edges, and illegal states.
- **Criteria**: Minimum 5 dedicated boundary tests per requirement (R1 through R6), totaling $\ge 30$ tests.
- **File**: `tests/e2e/test_tier2_boundary_corner.py`
- **Focus**:
  - Zero and negative budget validation.
  - Character boundary tests: 159 chars (pass), 160 chars (pass), 161 chars (fail).
  - Obfuscated and raw URL patterns in Telegram Ads copy (`https://`, `www.`, `(dot)`).
  - TON bid floor: 0.09 TON (fail) vs 0.10 TON (pass).
  - AdsGram daily minimum: 9.99 USDT (fail) vs 10.00 USDT (pass).
  - Kill-switch boundary: $1.49\times\text{CPA}$ (no trigger) vs $1.50\times\text{CPA}$ (trigger).
  - Frequency boundary: $2.79$ (no alert), $2.80$ (no alert), $2.81$ (alert).
  - Meta learning phase boundary: 49 conversions (LEARNING) vs 50 conversions (LEARNING_COMPLETE).
  - Payment verification gate: `payment_verified = False` strictly prohibits `LIVE` transition.

### Tier 3: Cross-Feature Combinations (Pairwise & Integration Level)
- **Scope**: Evaluates multi-component workflows and pairwise combinatorial variations.
- **File**: `tests/e2e/test_tier3_cross_feature.py`
- **Focus**:
  - State machine lifecycle combined with billing aggregator flow.
  - Creative copywriter generation combined with UTM injection and link validation across platforms.
  - Platform executors combined with mock sandbox adapters (Meta + TikTok + Telegram round-trip).
  - Financial allocation combined with platform threshold enforcement across multiple currencies.
  - Kill-switch action dispatching pause commands across all active platform adapters.
  - Creative fatigue detection triggering copywriter variant hot-swap.

### Tier 4: Real-World Scenarios (End-to-End Simulation Level)
- **Scope**: Multi-step realistic campaign operational scenarios from intake to resolution.
- **File**: `tests/e2e/test_tier4_real_world.py`
- **Focus**:
  - `Scenario 1: Happy Path E2E`: Intake -> Strategy -> Copy -> Staging -> Payment -> LIVE -> 24h stable telemetry -> Completed.
  - `Scenario 2: Early Kill-Switch Bleed`: Campaign goes live -> 0 conversions -> Spend reaches $1.5\times$ target CPA -> Kill-switch halts all ad delivery and alerts supervisor.
  - `Scenario 3: Creative Fatigue & Hot-Swap`: Running campaign saturates audience -> Frequency crosses $2.85$ -> Fatigue detected -> Copywriter rotates fresh variant.
  - `Scenario 4: TON Dynamic Auction Surge`: Channel competition index spikes -> Dynamic bidder raises bid while respecting TON floor and ceiling.
  - `Scenario 5: Payment Halt & Recovery`: Client attempts unverified launch -> Blocked by gatekeeper -> Payment webhook arrives -> Launch resumes successfully.

---

## 4. Offline Test Harness & Mock Architecture

### 4.1 Zero-Network Enforcement (`tests/conftest.py`)
All tests run with socket connections intercepted. Attempting any external network access raises `RuntimeError("Network access disabled during offline tests!")`.

### 4.2 Static Mock Fixtures (`tests/fixtures/`)
Deterministic JSON fixtures simulate all external ad platforms and financial partners:
- `meta_responses.json`: Mock Meta Graph API responses for Campaign, AdSet, and Ad creation in `PAUSED` status.
- `tiktok_responses.json`: Mock TikTok Marketing API v2.0 responses for Campaign, AdGroup, and Ad in `DISABLE` status.
- `adsly_responses.json`: Mock Adsly.Pro REST responses for competitor channel search and TON ad creation (CPM >= 0.1 TON).
- `adsgram_responses.json`: Mock AdsGram responses for rewarded/interstitial campaigns with daily budget >= 10 USDT.
- `billing_responses.json`: Mock Click.ru / eLama responses for invoicing, payment webhooks, and cashback ledger calculations.

---

## 5. Coverage Thresholds & Quality Gates

| Metric | Minimum Threshold | Enforcement Mechanism |
| :--- | :--- | :--- |
| **Feature Coverage (Tier 1)** | $\ge 5$ tests per feature (R1–R6) | Static test count audit & `run_tests.py` suite inspection |
| **Boundary Coverage (Tier 2)**| $\ge 5$ tests per feature (R1–R6) | Boundary test validation against specification formulas |
| **Pairwise Tests (Tier 3)**   | $\ge 6$ multi-component tests    | Cross-agent state and adapter execution validation |
| **E2E Scenarios (Tier 4)**    | $\ge 5$ complete scenarios       | Simulation loop and lifecycle verification |
| **Total Test Count**          | $\ge 70$ automated tests        | `run_tests.py` automated test discovery |
| **Network Leakage**           | **0 external calls** (0 bytes)   | Autouse socket-blocking fixture |
| **Test Pass Rate**            | **100% passing** (Exit Code 0)  | Test runner exit code verification |
