---
name: guided-intake
description: Collect a new travel case one question at a time, reuse defaults, support back/save/resume, and avoid duplicate TripCases.
user-invocable: false
---
# guided-intake

Use for a new customer or when a case is missing its basic travel requirements.

- Ask only one missing field at a time: customer, destination, departure, return, travelers, budget.
- Use the saved default departure airport rather than asking every time.
- Understand common shorthand such as `2大1小`, `2大2小`, and budget phrases such as `10萬內`.
- Validate dates before saving. A return date before departure must be corrected, not silently swapped.
- The workflow is persistent: support **上一步**, **先存起來**, and later **繼續**.
- Once a TripCase has been created, editing goes to that existing case. Do not restart the wizard in a way that creates a duplicate case.
- If a field is genuinely unknown, save it as unknown/null and continue when the workflow allows it rather than forcing a guess.

The application state machine is authoritative. Do not invent a separate conversational copy of the case.
