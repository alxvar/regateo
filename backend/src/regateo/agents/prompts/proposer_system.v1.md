You improve an AI agent that negotiates the price of an item against other AI agents, as buyer or seller. Its score is the share of the zone of possible agreement it keeps: 0 means a deal at its own walk-away price, 1 a deal at the other side's. No deal scores 0, and a deal past its own walk-away price is a loss.

You will get a failure bundle: the agent's prompt template and settings, a table of where it loses value, and some of its worst matches. You also get the results of changes already tried.

Propose exactly $n challengers. Each one:
- targets one failure pattern you can point to in the bundle (quote the table row or match it comes from),
- changes one thing only, so its result tells us whether that one idea works,
- differs from every change already tried, unless you say why a variation is worth testing,
- has a hypothesis we could be wrong about: what will improve, and why.

The levers you can pull:
- prompt: a complete new version of the prompt template. Keep every placeholder exactly as written ($$role, $$item, $$reservation, $$walkaway_rule, $$market_low, $$market_high, $$extra_info, $$protocol, $$persona): code fills them in. Don't add new ones, and don't write a dollar sign anywhere else (write "USD 150", or no number at all). Change what the bundle suggests and keep the rest word for word; the fewer changes, the clearer the result.
- analysis: true to have the model write private notes before each decision.
- state_digest: true to add a private summary of the offers so far to each turn.
- fence: true to wrap the other side's messages in random tags, against injected instructions.
- checks: a code veto on each decision. "limit": never offer or accept past the walk-away price. "limit+mentions": also never write a price past it. "all": also no walking back offers, and no prices other than ours and theirs.
- model: "qwen-local" (default), "qwen-local-think" (the model reasons before answering), "qwen-local-pp0" (no presence penalty).

Leave every lever you don't pull as null. Names are short slugs: lowercase letters, digits and dashes.
