# Negotiation agent: starter kit and sparring arena

A 1v1 price-negotiation agent plus a local "gym" that plays it against scripted opponents
across the rule variants we don't know yet (what each side knows, round limits, hidden
deadlines, wall-clock limits).

## Run it

```bash
python -m arena.run                          # offline: no API calls, template text
python -m arena.run --show injector          # print one transcript against an opponent
python -m arena.run --sweep                  # try a grid of strategy settings and rank them
python -m arena.run --params '{"keep_share": 0.8}'
pip install anthropic && export ANTHROPIC_API_KEY=...
python -m arena.run --llm --games 2          # Claude parses incoming text and writes our messages
```

Score per game = share of the available surplus we captured (0 if no deal inside the budget).

## How the agent is built

```
opponent text ──> parser ──> opponent model ──> strategy engine ──> writer ──> guardrail ──> our text
                  (LLM or     (guesses their     (plain code:         (LLM or    (exactly our
                   regex)      walk-away price)   picks the number)    template)  price, nothing else)
```

- `negotiation/strategy.py`: the brain. Never reads the opponent's words, only their numbers.
- `negotiation/estimator.py`: estimates the opponent's limit from how they concede.
- `negotiation/language.py`: parser, writer, and the guardrail on outgoing messages.
- `negotiation/scenario.py`: every unknown rule is a knob here.
- `arena/opponents.py`: sparring partners (linear, hardliner, pushover, liar, injector, staller) plus a mirror of ourselves.

## Known gaps / next steps

- Scripted opponents are softer than real LLM agents; add LLM-driven opponents with different personas.
- Hidden deadline: `assumed_rounds` is a real trade-off (short guess = safe but gives value away).
- Last-offer power: when we make the final offer and they have the last word, we could be bolder.
- Multi-issue deals (price + delivery + warranty) are not modelled yet.
