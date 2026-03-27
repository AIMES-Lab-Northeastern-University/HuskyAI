# Advanced Exemplars (PEI 70-90)

Use these as calibration anchors for high-scoring conversations.

---

DOMAIN: debugging | PEI: 84 | TURN: 2
USER: "The error only occurs when the user email contains a special character.
       I've already confirmed it's not the regex — the validation passes fine.
       I need to understand if this is a DB encoding issue or an API
       serializer issue. Here's the full stack trace: [...]
       I've already ruled out client-side encoding. The issue is server-side."
WHY HIGH:
  PSQ=91: clear scope (special chars), evidence provided (trace), constraint (already checked regex)
  CCM=85: user has done prior investigation, directs AI to specific layers
  TSI=88: problem isolated to two layers, ruled out third — clear decomposition
  CLM=78: appropriately sized message with all necessary context
  RAS=80: user is testing a hypothesis, not asking AI to guess blindly

---

DOMAIN: coding | PEI: 79 | TURN: 3
USER: "The implementation works but I'm not satisfied with the O(n²) complexity.
       I know we can do better because the data is always sorted.
       Don't give me the solution yet — first explain what patterns
       typically exploit sorted data for search/lookup optimization."
WHY HIGH:
  PSQ=88: specific problem (O(n²)), constraint (data is sorted), clear goal
  CCM=82: user explicitly controls the pace — "don't give me the solution yet"
  TSI=85: user identifies the optimization opportunity independently
  CLM=75: asks for conceptual step before implementation — incremental
  RAS=72: user wants to understand before accepting solution (under-reliance avoided)

---

DOMAIN: data_analysis | PEI: 76 | TURN: 2
USER: "The query returns 847 rows but I expected ~200 based on the business logic.
       I've checked for duplicates in the orders table — none.
       The join is on customer_id which is indexed. Could the issue be in
       how I'm filtering the date range? The business rule is 'orders in Q4'
       but our fiscal year ends March 31, not December 31."
WHY HIGH:
  PSQ=85: specific discrepancy (847 vs 200), evidence of investigation
  CCM=78: user has already debugged, presents a specific hypothesis
  TSI=82: considers indexing, date logic, fiscal year — sophisticated analysis
  CLM=72: well-structured message, not overwhelming
  RAS=75: user is verifying their own hypothesis, not asking AI to start from scratch
