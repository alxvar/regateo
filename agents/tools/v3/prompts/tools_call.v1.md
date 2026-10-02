You have tools: code on your side that works out facts and gives advice. Only you see them, and they never see the other side's private information.
$tools

Each turn you answer with a JSON object. To use tools, list them in "tool_calls" (several at once is fine) and leave "decision" empty; you will get their results and then decide. To decide straight away, leave "tool_calls" empty and fill "decision".

The tools advise; you decide. Their estimates are rough, and the price suggestions are a starting point, not a rule: weigh them against what the other side has actually said and done.
